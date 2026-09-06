# Phishing Detection MLOps Pipeline

Trains a classifier on the UCI phishing-websites feature set and serves it behind a FastAPI
endpoint. The pipeline is split into four components that each write versioned artifacts to
disk, so any stage can be re-run and inspected on its own.

```
data source ──► ingestion ──► validation ──► transformation ──► model trainer ──► FastAPI
(Mongo Atlas          │             │               │                  │              │
 or local CSV)   feature store  drift report    train/test.npy     model.pkl      Docker
                 train/test.csv  (KS test)      preprocessing.pkl   metrics       ECR ─► EC2
```

Every external dependency is optional. With no environment variables set, the pipeline reads
the bundled CSV, skips MLflow tracking and skips the S3 sync, so it runs offline on a laptop.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # optional; defaults work as-is

pytest                        # 14 tests, no network required
python main.py                # run the full training pipeline (~4 min)
uvicorn app:app --port 8080   # then open http://localhost:8080/docs
```

Docker:

```bash
docker build -t phishing-detection .
docker run -p 8080:8080 phishing-detection
curl localhost:8080/health
```

## Components

**Data ingestion** reads from a MongoDB Atlas collection when `MONGO_DB_URL` is set, otherwise
from `Network_Data/phisingData.csv`. Writes the raw pull to a feature store, then a stratified
train/test split with a fixed `random_state` so runs are reproducible.

**Data validation** checks the frame against `data_schema/schema.yaml` (31 declared columns,
by name and by count) and fails the run on a mismatch, because training on a wrong-shaped frame
produces a model that is silently wrong. It then runs a two-sample Kolmogorov-Smirnov test per
column between train and test and writes every p-value to `drift_report/report.yaml`.
`validation_status` is False if any column's p-value falls below 0.05.

*Known limitation:* KS is a test for continuous distributions and these features are ordinal
(-1/0/1), so the p-values are approximate. A chi-square or PSI test on the categorical columns
would be the correct instrument. The KS check is kept because it still catches gross shifts, and
the drift report is advisory rather than a hard gate.

**Data transformation** imputes missing values with a KNN imputer (k=3) inside an sklearn
Pipeline, and persists the fitted pipeline so serving applies exactly the transform training
used. No scaling and no resampling: the classes are roughly balanced (about 56/44) and the
tree-based models that win selection are scale-invariant.

**Model trainer** grid-searches five classifiers (Random Forest, Gradient Boosting, Decision
Tree, AdaBoost, Logistic Regression) with 3-fold CV and picks the best by **F1 on the held-out
test set**. The run aborts rather than promoting anything if the best F1 falls below
`MODEL_TRAINER_EXPECTED_SCORE`. Metrics and parameters go to MLflow when a tracking URI is
configured.

## API

| Method | Path            | Notes |
| ------ | --------------- | ----- |
| GET    | `/health`       | liveness, whether a model is loaded, last training state |
| POST   | `/train`        | returns 202 and runs in the background; requires `X-API-Key` when `TRAIN_API_KEY` is set |
| GET    | `/train/status` | `idle` / `running` / `succeeded` / `failed` |
| POST   | `/predict`      | CSV upload, validated against the schema, returns an HTML table |

Training is minutes long and would otherwise block the single uvicorn worker, so `/train` hands
off to a background task and the caller polls `/train/status`.

## Configuration

All settings are environment variables. See `.env.example` for the full list.

| Variable | Effect when unset |
| -------- | ----------------- |
| `MONGO_DB_URL` | ingestion falls back to the bundled CSV |
| `MLFLOW_TRACKING_URI` | experiment tracking is skipped |
| `TRAINING_BUCKET_NAME` | S3 artifact sync is skipped |
| `TRAIN_API_KEY` | `/train` is unauthenticated (local dev only) |
| `ALLOWED_ORIGINS` | CORS allows any origin without credentials |
| `PORT` | 8080 |

## Tests

```bash
pytest -q
```

The suite covers the schema check, drift detection on both an unshifted and a synthetically
shifted frame, F1-based model ranking against a constant baseline, and API contracts
(`/predict` returns 422 or 503 on a bad upload, never a 500). CI runs `ruff` and `pytest` on
every push and pull request; the deploy job does not run if either fails.

## CI/CD

Push to `main` runs lint and tests, builds a multi-stage image, pushes it to ECR tagged with
both `latest` and the 7-character commit SHA, then a self-hosted runner on EC2 pulls that tag,
replaces the running container and polls `/health` before reporting success. The SHA tag is
what makes a rollback possible: `docker run` the previous tag.

Required GitHub secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`,
`ECR_REPOSITORY_NAME`, and optionally `TRAINING_BUCKET_NAME`, `TRAIN_API_KEY`,
`MONGODB_URL_KEY`, `MLFLOW_TRACKING_URI`, `MLFLOW_TRACKING_USERNAME`, `MLFLOW_TRACKING_PASSWORD`.

## Known gaps

Honest list of what this does not do yet, in rough priority order.

- No model registry gate. The newest trained model overwrites `final_model/`, with no comparison
  against the currently deployed one. Promotion should be conditional on beating the champion.
- No inference monitoring. Drift is only measured at training time, on the training data. There
  is no record of what the deployed model is actually being asked to predict.
- Single container on a single EC2 instance. No autoscaling, no zero-downtime deploy; the
  replace step drops requests for a few seconds.
- Long-lived AWS access keys in GitHub secrets. OIDC role assumption would remove the standing
  credential entirely.
- The KS drift test on ordinal features, described above.

## Project structure

```
networksecurity/
  components/     ingestion, validation, transformation, model trainer
  entity/         config and artifact dataclasses
  pipeline/       training and batch prediction orchestration
  cloud/          S3 artifact sync (boto3)
  utils/          model wrapper, metrics, IO helpers
  exception/      custom exception carrying file and line
  logging/        logger setup
data_schema/      schema.yaml (31 columns)
tests/            pytest suite
app.py            FastAPI service
main.py           run the pipeline from the CLI
```

## Author

**Prabhat Singh Tomar** — [LinkedIn](https://www.linkedin.com/in/prabhat-singh-tomar/)
