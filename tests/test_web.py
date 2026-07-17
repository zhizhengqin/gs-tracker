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


def test_root_lists_reports(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web.REPORT_OUTPUT_DIR", tmp_path)
    (tmp_path / "2026-Q2.html").write_text("<html>Q2</html>", encoding="utf-8")
    (tmp_path / "2026-Q1.html").write_text("<html>Q1</html>", encoding="utf-8")

    response = client.get("/")
    assert response.status_code == 200
    assert "GS-Tracker 报告列表" in response.text
    assert "2026-Q1" in response.text
    assert "2026-Q2" in response.text
    # Verify ordering and link format.
    q1_pos = response.text.find("2026-Q1")
    q2_pos = response.text.find("2026-Q2")
    assert q1_pos < q2_pos
    assert '/reports/2026-Q1.html"' in response.text


def test_root_empty_reports(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web.REPORT_OUTPUT_DIR", tmp_path)
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
