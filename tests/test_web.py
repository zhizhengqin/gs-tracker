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


def test_root_serves_dashboard(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web.REPORT_OUTPUT_DIR", tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    # Dashboard renders with GS-Tracker branding
    assert "GS-Tracker" in response.text
    assert "高盛动向情报系统" in response.text
    # Dashboard has sidebar navigation
    assert "sidebar" in response.text


def test_root_fallback_when_no_dashboard(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web.REPORT_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("src.web.DASHBOARD_TEMPLATE", tmp_path / "nonexistent.html")
    response = client.get("/")
    assert response.status_code == 200
    assert "暂无报告" in response.text


def test_api_reports(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web.REPORT_OUTPUT_DIR", tmp_path)
    (tmp_path / "2026-Q1.html").write_text("<html>Q1</html>", encoding="utf-8")

    response = client.get("/api/reports")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["quarter"] == "2026-Q1"
    assert data[0]["title"] == "高盛动向情报板 — 2026-Q1"
    assert data[0]["path"] == "/reports/2026-Q1.html"


def test_api_reports_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web.REPORT_OUTPUT_DIR", tmp_path)
    response = client.get("/api/reports")
    assert response.status_code == 200
    assert response.json() == []


def test_get_report_success(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web.REPORT_OUTPUT_DIR", tmp_path)
    (tmp_path / "2026-Q1.html").write_text("<html>高盛 Q1 报告</html>", encoding="utf-8")

    response = client.get("/reports/2026-Q1.html")
    assert response.status_code == 200
    assert "高盛 Q1 报告" in response.text
