"""Tests for src.web."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from src import storage
from src.signals.base import Signal, SignalStrength
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


@pytest.fixture
def signals_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr("src.storage.DATABASE_URL", f"sqlite:///{db_file}")
    storage.init_db()
    return db_file


def _make_signal(**overrides) -> Signal:
    defaults = dict(
        title="高盛增持苹果",
        source="13F",
        published_at=datetime(2026, 3, 31, 12, 0, 0),
        summary="苹果占组合 12.3%",
        companies=["AAPL"],
        strength=SignalStrength.HIGH,
        url="https://example.com/a",
        cross_refs=["news:高盛看好苹果"],
        id="sig00001",
    )
    defaults.update(overrides)
    return Signal(**defaults)


def test_api_signals_not_found_when_no_run(signals_db):
    response = client.get("/api/signals/2099-Q4")
    assert response.status_code == 404
    assert response.json()["detail"] == "该季度暂无信号数据"


def test_api_signals_returns_saved_signals(signals_db):
    storage.save_signal_run(
        "2026-Q1",
        source_status={"13F": "ok", "news": "error"},
        errors=["news failed: timeout"],
    )
    storage.save_signals("2026-Q1", [_make_signal()])

    response = client.get("/api/signals/2026-Q1")
    assert response.status_code == 200
    data = response.json()
    assert data["quarter"] == "2026-Q1"
    assert data["source_status"] == {"13F": "ok", "news": "error"}
    assert data["errors"] == ["news failed: timeout"]

    assert len(data["signals"]) == 1
    s = data["signals"][0]
    assert s["id"] == "sig00001"
    assert s["title"] == "高盛增持苹果"
    assert s["source"] == "13F"
    assert s["strength"] == "high"
    assert s["companies"] == ["AAPL"]
    assert s["summary"] == "苹果占组合 12.3%"
    assert s["url"] == "https://example.com/a"
    assert s["cross_refs"] == ["news:高盛看好苹果"]
    assert s["published_at"] == "2026-03-31T12:00:00"


def test_api_signals_empty_run_returns_empty_list(signals_db):
    storage.save_signal_run("2026-Q1", source_status={"13F": "ok"}, errors=[])
    storage.save_signals("2026-Q1", [])

    response = client.get("/api/signals/2026-Q1")
    assert response.status_code == 200
    data = response.json()
    assert data["signals"] == []
    assert data["source_status"] == {"13F": "ok"}
    assert data["errors"] == []
