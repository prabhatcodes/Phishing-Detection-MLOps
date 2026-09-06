import os
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Tests must never talk to Mongo, MLflow or S3.
os.environ.pop("MONGO_DB_URL", None)
os.environ.pop("MONGODB_URL_KEY", None)
os.environ["MLFLOW_TRACKING_URI"] = ""
os.environ["TRAINING_BUCKET_NAME"] = ""
os.environ.setdefault("TRAIN_API_KEY", "")

# Several modules resolve paths (schema, Network_Data, final_model) relative to
# the working directory, so anchor every test run at the repo root.
os.chdir(REPO_ROOT)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def raw_df() -> pd.DataFrame:
    return pd.read_csv(REPO_ROOT / "Network_Data" / "phisingData.csv")


@pytest.fixture(scope="session")
def feature_columns() -> list:
    from networksecurity.constant.training_pipeline import SCHEMA_FILE_PATH, TARGET_COLUMN
    from networksecurity.utils.main_utils.utils import read_yaml_file

    schema = read_yaml_file(str(REPO_ROOT / SCHEMA_FILE_PATH))
    cols = [list(e.keys())[0] for e in schema["columns"]]
    return [c for c in cols if c != TARGET_COLUMN]
