import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app

GOOD_CSV = b"""timestamp,value
2026-01-01T00:00:00,10
2026-01-01T01:00:00,11
2026-01-01T02:00:00,9
2026-01-01T03:00:00,10
2026-01-01T04:00:00,120
"""


@pytest.fixture()
def client():
    # In-memory SQLite shared across connections; no Postgres needed to run tests.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def upload(client, data=GOOD_CSV, filename="sensor.csv"):
    return client.post(
        "/datasets", files={"file": (filename, io.BytesIO(data), "text/csv")}
    )


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_upload_accepts_valid_csv(client):
    r = upload(client)
    assert r.status_code == 201
    body = r.json()
    assert body["accepted"] == 5
    assert body["rejected"] == 0
    assert body["dataset"]["value_column"] == "value"


def test_upload_reports_rejected_rows_by_reason(client):
    messy = b"""timestamp,value
2026-01-01T00:00:00,10
not-a-date,11
2026-01-01T02:00:00,abc
2026-01-01T03:00:00,
2026-01-01T04:00:00,12
"""
    body = upload(client, messy).json()
    assert body["accepted"] == 2
    assert body["rejected"] == 3
    assert body["reasons"] == {
        "bad_timestamp": 1,
        "non_numeric_value": 1,
        "missing_value": 1,
    }


def test_upload_rejects_csv_without_timestamp_column(client):
    r = upload(client, b"foo,bar\n1,2\n")
    assert r.status_code == 422
    assert "timestamp" in r.json()["detail"]


def test_summary_matches_uploaded_values(client):
    dataset_id = upload(client).json()["dataset"]["id"]
    s = client.get(f"/datasets/{dataset_id}/summary").json()
    assert s["count"] == 5
    assert s["min"] == 9
    assert s["max"] == 120
    assert s["mean"] == 32.0


def test_anomalies_flag_the_spike(client):
    dataset_id = upload(client).json()["dataset"]["id"]
    r = client.get(f"/datasets/{dataset_id}/anomalies", params={"threshold": 1.5}).json()
    assert r["count"] == 1
    assert r["anomalies"][0]["value"] == 120


def test_missing_dataset_returns_404(client):
    assert client.get("/datasets/999/summary").status_code == 404


def test_delete_removes_dataset(client):
    dataset_id = upload(client).json()["dataset"]["id"]
    assert client.delete(f"/datasets/{dataset_id}").status_code == 204
    assert client.get(f"/datasets/{dataset_id}").status_code == 404
