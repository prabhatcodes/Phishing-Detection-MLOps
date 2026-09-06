"""API contract tests. No model on disk -> /predict must 503, not 500."""
import io

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import app as app_module
    return TestClient(app_module.app)


def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_predict_rejects_a_csv_with_missing_columns(client):
    csv = io.BytesIO(b"a,b,c\n1,2,3\n")
    r = client.post("/predict", files={"file": ("bad.csv", csv, "text/csv")})
    # 422 when a model exists, 503 when it does not. Never a 500 traceback.
    assert r.status_code in (422, 503)


def test_predict_rejects_unparseable_upload(client):
    blob = io.BytesIO(b"\x00\x01\x02notacsv")
    r = client.post("/predict", files={"file": ("bad.bin", blob, "application/octet-stream")})
    assert r.status_code in (400, 422, 503)


def test_train_requires_api_key_when_one_is_configured(monkeypatch):
    monkeypatch.setenv("TRAIN_API_KEY", "secret")
    import importlib

    import app as app_module
    importlib.reload(app_module)
    c = TestClient(app_module.app)
    assert c.post("/train").status_code == 401
    assert c.post("/train", headers={"X-API-Key": "wrong"}).status_code == 401
