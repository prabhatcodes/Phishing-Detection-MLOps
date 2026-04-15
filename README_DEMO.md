# Interview demo setup — read this first

This is your phishing-detection-pipeline repo, patched to run locally with zero external accounts (no MongoDB Atlas, no DagsHub) so nothing can fail live due to network/creds during the interview.

## What changed from the original repo

- `data_ingestion.py`: falls back to the local CSV (`Network_Data/phisingData.csv`) when `MONGO_DB_URL` is empty, instead of requiring MongoDB Atlas.
- `app.py`: Mongo client is only created if a URL is configured, and now accepts either `MONGODB_URL_KEY` or `MONGO_DB_URL` (the repo used both names inconsistently). Also fixed the FastAPI/Starlette `TemplateResponse(request, name, context)` call — the old positional signature (`TemplateResponse(name, {"request":...})`) throws on current Starlette, and added `os.makedirs` for `prediction_output/` which didn't exist.
- `model_trainer.py`: fixed a bug where `registered_model_name=best_model` passed the model object instead of its name string (crashes the MLflow registry call).
- `.env`: added, points MLflow at a local SQLite store (`sqlite:///mlflow.db`) — current MLflow versions reject the old file-based `./mlruns` store outright ("in maintenance mode"), so this is required, not optional.

I ran the full pipeline (`main.py`) and the API (`/train` then `/predict`) end-to-end in a clean environment before sending you this — both work.

## Setup (do this now, before 2pm)

Open a terminal in this folder (Project1) and run:

```
pip install -r requirements.txt
python app.py
```

Then open http://localhost:8000/docs in a browser. Two endpoints:

- `/train` — runs the full pipeline (Mongo-free, reads the local CSV). Takes about 4-5 minutes on a typical laptop — GridSearchCV over 5 classifiers. **Run this once now** so `final_model/model.pkl` and `final_model/preprocessor.pkl` exist before the interview. It also writes a `mlflow.db` (experiment tracking) you can show if asked about MLflow.
- `/predict` — upload a CSV of the same 30 feature columns (no `Result` column) and it returns an HTML prediction table. To get a sample file: after `/train` runs once, take a few rows from `Artifacts/<timestamp>/data_ingestion/ingested/test.csv` and drop the `Result` column.

Note: `/train` blocks the server while running (single worker, synchronous training code) — don't try to hit `/predict` in another tab while `/train` is in progress.

## During the demo

- Fastest safe path: click `/predict` with a prepared sample CSV — instant, no wait.
- If you want to show training live and have ~5 minutes of runway: click `/train`, narrate the pipeline stages (ingestion → validation → drift check → transformation → 5-model GridSearchCV → MLflow logging) while it runs.
- Talk track for architecture: MongoDB Atlas → Data Ingestion → Data Validation (schema + Evidently-style drift via KS-test) → Data Transformation (KNN imputer, would use SMOTETomek/RobustScaler per README) → Model Trainer (5 classifiers, GridSearchCV, MLflow tracking) → FastAPI → Docker → AWS ECR/EC2 via GitHub Actions. In this local demo, Mongo/DagsHub/AWS are swapped for local equivalents (CSV, local MLflow, no cloud push) purely so nothing depends on live external services during the interview — the code paths for the real integrations are still intact and just need env vars.

## If something breaks

- `ModuleNotFoundError`: re-run `pip install -r requirements.txt`.
- Port 8000 already in use: another `python app.py` is still running — close it or change the port in the last line of `app.py`.
- Want to reset and start fresh: delete `Artifacts/`, `final_model/`, `mlruns/` (if present), `mlflow.db`, `logs/`, `prediction_output/` and re-run `/train`.
