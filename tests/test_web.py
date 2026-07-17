"""Tests for src.web."""
from fastapi.testclient import TestClient

from src.web import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_report_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web.REPORT_OUTPUT_DIR", tmp_path)
    response = client.get("/reports/2099-Q1.html")
    assert response.status_code == 404
