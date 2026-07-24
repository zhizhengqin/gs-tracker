"""Tests for src.web."""
import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import src.web
from src import storage
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


def test_api_reports_sorted_newest_first(tmp_path, monkeypatch):
    """Dashboard badges reports[0] as latest, so the API must return newest first."""
    monkeypatch.setattr("src.web.REPORT_OUTPUT_DIR", tmp_path)
    (tmp_path / "2025-Q4.html").write_text("<html>Q4</html>", encoding="utf-8")
    (tmp_path / "2026-Q2.html").write_text("<html>Q2</html>", encoding="utf-8")
    (tmp_path / "2026-Q1.html").write_text("<html>Q1</html>", encoding="utf-8")

    response = client.get("/api/reports")
    assert response.status_code == 200
    quarters = [r["quarter"] for r in response.json()]
    assert quarters == ["2026-Q2", "2026-Q1", "2025-Q4"]


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


def test_api_signals_not_found_when_no_run(signals_db):
    response = client.get("/api/signals/2099-Q4")
    assert response.status_code == 404
    assert response.json()["detail"] == "该季度暂无信号数据"


def test_api_signals_invalid_quarter_returns_422(signals_db):
    for bad in ("foo", "2026", "2026-q1", "2026-Q5", "2026-Q0"):
        response = client.get(f"/api/signals/{bad}")
        assert response.status_code == 422, bad


def test_api_signals_fresh_db_initialized_at_startup(tmp_path, monkeypatch):
    """Fresh deployment: startup init creates tables, so the endpoint 404s (not 500s)."""
    db_file = tmp_path / "fresh.db"
    monkeypatch.setattr("src.storage.DATABASE_URL", f"sqlite:///{db_file}")
    with TestClient(app) as startup_client:
        response = startup_client.get("/api/signals/2026-Q1")
    assert response.status_code == 404
    assert response.json()["detail"] == "该季度暂无信号数据"


def test_api_signals_returns_saved_signals(signals_db, make_signal):
    storage.save_signal_run(
        "2026-Q1",
        source_status={"13F": "ok", "news": "error"},
        errors=["news failed: timeout"],
    )
    storage.save_signals("2026-Q1", [make_signal()])

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
    assert s["published_at"] == "2026-03-31T12:00:00+00:00"


def test_api_signals_empty_run_returns_empty_list(signals_db):
    storage.save_signal_run("2026-Q1", source_status={"13F": "ok"}, errors=[])
    storage.save_signals("2026-Q1", [])

    response = client.get("/api/signals/2026-Q1")
    assert response.status_code == 200
    data = response.json()
    assert data["signals"] == []
    assert data["source_status"] == {"13F": "ok"}
    assert data["errors"] == []


# ====== Pipeline trigger endpoints ======


@pytest.fixture
def reset_pipeline_state():
    """Reset the module-level pipeline state before and after each test."""
    src.web._pipeline_state.update(
        running=False,
        last_started_at=None,
        last_finished_at=None,
        last_error=None,
    )
    yield src.web._pipeline_state
    src.web._pipeline_state.update(
        running=False,
        last_started_at=None,
        last_finished_at=None,
        last_error=None,
    )


def test_pipeline_run_returns_202_and_completes(reset_pipeline_state, monkeypatch):
    mock_run = AsyncMock()
    monkeypatch.setattr("src.web.run_pipeline", mock_run)

    response = client.post("/api/pipeline/run")
    assert response.status_code == 202

    # The background task runs on the app's loop; poll until it finishes
    for _ in range(50):
        status = client.get("/api/pipeline/status").json()
        if not status["running"]:
            break
        time.sleep(0.05)

    mock_run.assert_awaited_once()
    status = client.get("/api/pipeline/status").json()
    assert status["running"] is False
    assert status["last_error"] is None
    assert status["last_started_at"] is not None
    assert status["last_finished_at"] is not None


def test_pipeline_run_conflict_while_running(reset_pipeline_state):
    src.web._pipeline_state["running"] = True

    response = client.post("/api/pipeline/run")
    assert response.status_code == 409
    assert "运行中" in response.json()["detail"]


def test_pipeline_run_records_error(reset_pipeline_state, monkeypatch):
    mock_run = AsyncMock(side_effect=RuntimeError("API key missing"))
    monkeypatch.setattr("src.web.run_pipeline", mock_run)

    asyncio.run(src.web._run_pipeline_tracked())

    state = src.web._pipeline_state
    assert state["running"] is False
    assert "API key missing" in state["last_error"]
    assert state["last_finished_at"] is not None


# ====== Shared daily intel SSE job ======

from datetime import datetime, timedelta, timezone  # noqa: E402


@pytest.fixture
def reset_daily_job():
    old_job = src.web._daily_job
    src.web._daily_job = None
    yield
    src.web._daily_job = old_job


def test_daily_job_attach_or_start(reset_daily_job, monkeypatch):
    """While a job runs, new connections attach to it instead of re-running;
    within the grace window after finish, reconnects replay the same job;
    only after the grace window does a new run start."""
    async def fake_runner(job):
        await asyncio.sleep(3600)  # never finishes within the test

    monkeypatch.setattr(src.web, "_daily_job_runner", fake_runner)

    async def scenario():
        job1 = src.web._get_or_start_daily_job()
        job2 = src.web._get_or_start_daily_job()
        assert job1 is job2  # attach, no duplicate run

        # Finished just now → still replayable
        job1.done = True
        job1.finished_at = datetime.now(timezone.utc)
        assert src.web._get_or_start_daily_job() is job1

        # Past the grace window → a brand-new run starts
        job1.finished_at = datetime.now(timezone.utc) - timedelta(
            seconds=src.web._DAILY_JOB_GRACE_SECONDS + 10
        )
        job4 = src.web._get_or_start_daily_job()
        assert job4 is not job1

    asyncio.run(scenario())


# ====== LLM config resolution and env seeding ======

def test_llm_client_kwargs_db_model_wins():
    db_model = {
        "auth_token": "db-token",
        "base_url": "https://db.test",
        "model_name": "db-model",
    }
    kwargs = src.web._llm_client_kwargs(db_model)
    assert kwargs["auth_token"] == "db-token"
    assert kwargs["base_url"] == "https://db.test"
    assert kwargs["model"] == "db-model"


def test_llm_client_kwargs_env_fallback_includes_api_key(monkeypatch):
    """Regression: env fallback must pass ANTHROPIC_API_KEY, not just auth_token."""
    monkeypatch.setattr("src.config.ANTHROPIC_API_KEY", "ak-123")
    monkeypatch.setattr("src.config.ANTHROPIC_AUTH_TOKEN", "")
    monkeypatch.setattr("src.config.ANTHROPIC_BASE_URL", "")
    monkeypatch.setattr("src.config.GS_LLM_MODEL", "env-model")

    kwargs = src.web._llm_client_kwargs(None)
    assert kwargs["api_key"] == "ak-123"
    assert kwargs["auth_token"] is None
    assert kwargs["base_url"] is None
    assert kwargs["model"] == "env-model"


def test_seed_default_llm_from_env(signals_db, monkeypatch):
    """Empty model table + env credentials → seed one default model; idempotent."""
    monkeypatch.setattr("src.config.ANTHROPIC_AUTH_TOKEN", "sk-test-token")
    monkeypatch.setattr("src.config.ANTHROPIC_API_KEY", "")
    monkeypatch.setattr("src.config.ANTHROPIC_BASE_URL", "https://example.test")
    monkeypatch.setattr("src.config.GS_LLM_MODEL", "test-model")

    src.web._seed_default_llm_from_env()
    models = storage.get_llm_models()
    assert len(models) == 1
    assert models[0]["is_default"] == 1
    assert models[0]["auth_token"] == "sk-test-token"
    assert models[0]["base_url"] == "https://example.test"
    assert models[0]["model_name"] == "test-model"

    src.web._seed_default_llm_from_env()  # second call must be a no-op
    assert len(storage.get_llm_models()) == 1


def test_seed_default_llm_skips_without_env(signals_db, monkeypatch):
    monkeypatch.setattr("src.config.ANTHROPIC_AUTH_TOKEN", "")
    monkeypatch.setattr("src.config.ANTHROPIC_API_KEY", "")
    src.web._seed_default_llm_from_env()
    assert storage.get_llm_models() == []
