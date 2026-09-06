"""FastAPI service for the phishing-detection model.

Endpoints
    GET  /health        liveness + whether a model is loaded
    POST /train         kicks off the training pipeline in the background
    GET  /train/status  state of the last training run
    POST /predict       CSV upload -> HTML table of predictions
"""

import os
import threading
from datetime import datetime, timezone

import certifi
import pandas as pd
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from starlette.responses import JSONResponse, RedirectResponse
from uvicorn import run as app_run

from networksecurity.constant.training_pipeline import (
    DATA_INGESTION_COLLECTION_NAME,
    DATA_INGESTION_DATABASE_NAME,
    SCHEMA_FILE_PATH,
    TARGET_COLUMN,
)
from networksecurity.logging.logger import logging
from networksecurity.pipeline.training_pipeline import TrainingPipeline
from networksecurity.utils.main_utils.utils import load_object, read_yaml_file
from networksecurity.utils.ml_utils.model.estimator import NetworkModel

load_dotenv()
ca = certifi.where()

MODEL_PATH = os.getenv("MODEL_PATH", "final_model/model.pkl")
PREPROCESSOR_PATH = os.getenv("PREPROCESSOR_PATH", "final_model/preprocessor.pkl")
PORT = int(os.getenv("PORT", "8080"))
TRAIN_API_KEY = os.getenv("TRAIN_API_KEY", "").strip()
ALLOWED_ORIGINS = [o for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o]

# Mongo is optional. Without a URL the pipeline reads the bundled CSV, so the
# service runs end to end with no external dependencies.
mongo_db_url = os.getenv("MONGODB_URL_KEY") or os.getenv("MONGO_DB_URL")
if mongo_db_url:
    import pymongo

    client = pymongo.MongoClient(mongo_db_url, tlsCAFile=ca)
    database = client[DATA_INGESTION_DATABASE_NAME]
    collection = database[DATA_INGESTION_COLLECTION_NAME]
else:
    logging.info("No Mongo URL configured - reading from the local CSV instead.")
    client = None

app = FastAPI(title="Phishing Detection API", version="1.0.0")

# allow_credentials=True with allow_origins=["*"] is rejected by browsers and
# is unsafe intent regardless. Credentials are only enabled for an explicit
# origin list supplied via ALLOWED_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_credentials=bool(ALLOWED_ORIGINS),
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="./templates")

_train_state = {"status": "idle", "started_at": None, "finished_at": None, "detail": None}
_train_lock = threading.Lock()


def _expected_feature_columns() -> list:
    schema = read_yaml_file(SCHEMA_FILE_PATH)
    cols = [list(e.keys())[0] for e in schema["columns"]]
    return [c for c in cols if c != TARGET_COLUMN]


def _require_key(x_api_key: str | None) -> None:
    """No-op when TRAIN_API_KEY is unset (local dev); enforced in deployment."""
    if TRAIN_API_KEY and x_api_key != TRAIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def _run_training() -> None:
    try:
        TrainingPipeline().run_pipeline()
        with _train_lock:
            _train_state.update(
                status="succeeded",
                finished_at=datetime.now(timezone.utc).isoformat(),
                detail=None,
            )
    except Exception as exc:  # noqa: BLE001 - surfaced through /train/status
        logging.exception("Training pipeline failed")
        with _train_lock:
            _train_state.update(
                status="failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                detail=str(exc),
            )


@app.get("/", include_in_schema=False)
async def index():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["ops"])
async def health():
    """Used by the container HEALTHCHECK and by any load balancer in front."""
    return {
        "status": "ok",
        "model_loaded": os.path.exists(MODEL_PATH) and os.path.exists(PREPROCESSOR_PATH),
        "training": _train_state["status"],
    }


@app.post("/train", tags=["training"])
async def train_route(background_tasks: BackgroundTasks, x_api_key: str | None = Header(default=None)):
    """Training takes minutes and would block the single uvicorn worker, so it
    runs in the background and the caller polls /train/status."""
    _require_key(x_api_key)
    with _train_lock:
        if _train_state["status"] == "running":
            raise HTTPException(status_code=409, detail="A training run is already in progress")
        _train_state.update(
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            finished_at=None,
            detail=None,
        )
    background_tasks.add_task(_run_training)
    return JSONResponse(status_code=202, content={"status": "accepted", "poll": "/train/status"})


@app.get("/train/status", tags=["training"])
async def train_status():
    with _train_lock:
        return dict(_train_state)


@app.post("/predict", tags=["inference"])
async def predict_route(request: Request, file: UploadFile = File(...)):
    if not (os.path.exists(MODEL_PATH) and os.path.exists(PREPROCESSOR_PATH)):
        raise HTTPException(status_code=503, detail="No trained model available. Run POST /train first.")

    try:
        df = pd.read_csv(file.file)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {exc}") from exc

    # Validate the upload before it reaches the model. Without this, a wrong
    # file produces either a confusing sklearn traceback or silent nonsense.
    expected = _expected_feature_columns()
    df = df.drop(columns=[TARGET_COLUMN], errors="ignore")
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Uploaded CSV is missing {len(missing)} required column(s): {missing[:10]}",
        )
    df = df[expected]

    network_model = NetworkModel(
        preprocessor=load_object(PREPROCESSOR_PATH),
        model=load_object(MODEL_PATH),
    )
    df["predicted_column"] = network_model.predict(df)

    os.makedirs("prediction_output", exist_ok=True)
    df.to_csv("prediction_output/output.csv", index=False)

    table_html = df.to_html(classes="table table-striped")
    return templates.TemplateResponse(request, "table.html", {"table": table_html})


if __name__ == "__main__":
    app_run(app, host="0.0.0.0", port=PORT)
