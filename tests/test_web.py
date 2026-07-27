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


def test_dashboard_contains_user_guide(tmp_path, monkeypatch):
    """The dashboard ships an in-app user guide reachable from the sidebar."""
    monkeypatch.setattr("src.web.REPORT_OUTPUT_DIR", tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    # Sidebar nav entry
    assert 'data-view="guide"' in response.text
    assert "使用指南" in response.text
    # Guide content explains the three SEC signal sources for beginners
    assert "13F" in response.text
    assert "8-K" in response.text
    assert "13D" in response.text and "13G" in response.text
    # Beginner-friendly explanations of what each form means
    assert "季度" in response.text  # 13F is a quarterly filing
    assert "重大事件" in response.text  # 8-K covers material events
    assert "5%" in response.text  # 13D/13G ownership threshold


def test_dashboard_holdings_aggregation(tmp_path, monkeypatch):
    """The holdings panel aggregates duplicate issuers into one row per company."""
    monkeypatch.setattr("src.web.REPORT_OUTPUT_DIR", tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    # Client-side aggregation helper
    assert "aggregateHoldingsByName" in response.text
    # Toggle between aggregated and raw views
    assert "按公司汇总" in response.text
    assert "原始明细" in response.text


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


def test_purge_non_gs_news_signals(signals_db, make_signal):
    """One-time purge drops news without a GS angle, keeps GS news & other sources."""
    from src.storage import get_signals, save_signals_incremental

    gs_news = make_signal(id="gs1", source="news", title="高盛研报：看好A股", summary="高盛认为…")
    off_topic = make_signal(id="oth1", source="news", title="A股三大股指跌超1%", summary="市场概述…")
    other_source = make_signal(id="k1", source="8-K", title="Goldman 8-K filing", summary="…")
    save_signals_incremental("2026-Q3", [gs_news, off_topic, other_source])

    src.web._purge_non_gs_news_signals()

    remaining = {s.id for s in get_signals("2026-Q3")}
    assert "gs1" in remaining
    assert "oth1" not in remaining
    assert "k1" in remaining
    assert storage.get_setting("news_gs_purge_v1") == "1"


# ====== Signal AI analysis caching behavior ======

class _EmptyFakeClient:
    """LLM client whose completions are always empty (transient gateway hiccup)."""

    class _Messages:
        async def create(self, **kwargs):
            class _Resp:
                content = []
            return _Resp()

    def __init__(self, **kwargs):
        self.messages = self._Messages()


class _TextFakeClient:
    """LLM client returning a fixed analysis text."""

    class _Messages:
        async def create(self, **kwargs):
            class _Block:
                text = "新的解读"

            class _Resp:
                content = [_Block()]
            return _Resp()

    def __init__(self, **kwargs):
        self.messages = self._Messages()


def test_analyze_signal_empty_completion_not_cached(signals_db, monkeypatch):
    """Empty LLM completions → 502, and must NOT be cached (retry stays possible)."""
    monkeypatch.setattr("anthropic.AsyncAnthropic", _EmptyFakeClient)
    storage.add_llm_model("m1", "t", "https://x.test", "tok", "model-x")

    resp = client.post(
        "/api/signals/sig-empty/analyze",
        json={"title": "高盛测试", "summary": "内容", "source": "news"},
    )
    assert resp.status_code == 502
    assert storage.get_signal_analysis("sig-empty") is None


def test_analyze_signal_regenerates_after_sentinel(signals_db, monkeypatch):
    """A cached 'AI 未生成有效解读' is treated as a miss and regenerated."""
    monkeypatch.setattr("anthropic.AsyncAnthropic", _TextFakeClient)
    storage.add_llm_model("m1", "t", "https://x.test", "tok", "model-x")
    storage.save_signal_analysis("sig-x", src.web._ANALYSIS_FAILURE_SENTINEL)

    resp = client.post(
        "/api/signals/sig-x/analyze",
        json={"title": "t", "summary": "s", "source": "news"},
    )
    assert resp.status_code == 200
    assert resp.json()["analysis"] == "新的解读"
    assert resp.json()["cached"] is False
    assert storage.get_signal_analysis("sig-x") == "新的解读"


# ====== Custom source settings API ======

def _custom_payload(**overrides):
    payload = {
        "name": "caixin",
        "label": "财新网",
        "url": "https://example.com/rss",
        "filter_policy": "all",
    }
    payload.update(overrides)
    return payload


def test_custom_source_crud_cycle(signals_db):
    resp = client.post("/api/settings/sources/custom", json=_custom_payload())
    assert resp.status_code == 201

    sources = client.get("/api/settings/sources").json()
    custom = [s for s in sources if s["name"] == "caixin"]
    assert len(custom) == 1
    assert custom[0]["builtin"] is False
    assert custom[0]["filter_policy"] == "all"
    assert custom[0]["enabled"] is True

    resp = client.put("/api/settings/sources/custom/caixin", json={"label": "财新", "enabled": False})
    assert resp.status_code == 200
    custom = [s for s in client.get("/api/settings/sources").json() if s["name"] == "caixin"]
    assert custom[0]["label"] == "财新"
    assert custom[0]["enabled"] is False

    resp = client.delete("/api/settings/sources/custom/caixin")
    assert resp.status_code == 200
    assert not [s for s in client.get("/api/settings/sources").json() if s["name"] == "caixin"]


def test_custom_source_validation(signals_db):
    assert client.post("/api/settings/sources/custom", json=_custom_payload(name="Bad Name")).status_code == 422
    assert client.post("/api/settings/sources/custom", json=_custom_payload(url="ftp://x")).status_code == 422
    assert client.post("/api/settings/sources/custom", json=_custom_payload(filter_policy="weird")).status_code == 422
    assert client.post("/api/settings/sources/custom", json=_custom_payload(label="")).status_code == 422


def test_custom_source_duplicate_rejected(signals_db):
    assert client.post("/api/settings/sources/custom", json=_custom_payload()).status_code == 201
    assert client.post("/api/settings/sources/custom", json=_custom_payload()).status_code == 409
    assert client.post("/api/settings/sources/custom", json=_custom_payload(name="news")).status_code == 409


def test_custom_source_delete_builtin_rejected(signals_db):
    assert client.delete("/api/settings/sources/custom/news").status_code == 400
    assert client.delete("/api/settings/sources/custom/nosuch").status_code == 404


def test_custom_source_edit_builtin_rejected(signals_db):
    assert client.put("/api/settings/sources/custom/news", json={"label": "x"}).status_code == 404


def test_test_source_endpoint(signals_db, monkeypatch, make_signal):
    class _FakeSource:
        def __init__(self, **kwargs):
            pass

        async def fetch(self, quarter):
            return [
                make_signal(id="t1", title="标题一"),
                make_signal(id="t2", title="标题二"),
            ]

        async def close(self):
            pass

    monkeypatch.setattr("src.signals.news_source.NewsSource", _FakeSource)
    # Hermetic no-LLM config regardless of developer-shell env credentials
    monkeypatch.setattr("src.web.resolve_llm_config",
                        lambda m: {"api_key": None, "auth_token": None, "base_url": None, "model": "m"})
    resp = client.post("/api/settings/sources/test", json={"url": "https://example.com/rss"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 2
    assert data["sample_titles"] == ["标题一", "标题二"]
    # No LLM configured in the test DB → no triage preview, all kept
    assert data["items"] == [{"title": "标题一", "kept": True}, {"title": "标题二", "kept": True}]
    assert data["ai_used"] is False

    resp = client.post("/api/settings/sources/test", json={"url": "not-a-url"})
    assert resp.status_code == 422


def test_webpage_source_crud(signals_db):
    payload = _custom_payload(name="gs_page", type="webpage", instruction="提取高盛观点")
    assert client.post("/api/settings/sources/custom", json=payload).status_code == 201

    sources = client.get("/api/settings/sources").json()
    entry = [s for s in sources if s["name"] == "gs_page"][0]
    assert entry["type"] == "webpage"
    assert entry["instruction"] == "提取高盛观点"

    resp = client.put("/api/settings/sources/custom/gs_page", json={"instruction": "提取目标价"})
    assert resp.status_code == 200
    entry = [s for s in client.get("/api/settings/sources").json() if s["name"] == "gs_page"][0]
    assert entry["instruction"] == "提取目标价"


def test_webpage_source_requires_instruction(signals_db):
    resp = client.post(
        "/api/settings/sources/custom",
        json=_custom_payload(type="webpage", instruction=""),
    )
    assert resp.status_code == 422


def test_webpage_edit_cannot_drop_instruction(signals_db):
    payload = _custom_payload(name="wp", type="webpage", instruction="提取要点")
    assert client.post("/api/settings/sources/custom", json=payload).status_code == 201
    resp = client.put("/api/settings/sources/custom/wp", json={"instruction": "  "})
    assert resp.status_code == 422


def test_bad_source_type_rejected(signals_db):
    resp = client.post("/api/settings/sources/custom", json=_custom_payload(type="topic"))
    assert resp.status_code == 422


def test_test_source_webpage_preview(signals_db, monkeypatch, make_signal):
    """Webpage test runs extraction + AI triage preview with per-item keep flags."""
    class _FakeWebSource:
        def __init__(self, **kwargs):
            self.fetch_note = ""

        async def fetch(self, quarter):
            return [make_signal(id="w1", title="要点一"), make_signal(id="w2", title="要点二")]

        async def close(self):
            pass

    class _FakeTriage:
        def __init__(self, *a, **kw):
            pass

        async def triage(self, items, label, policy):
            from src.signals.ai_triage import TriageResult
            return TriageResult(kept_indices=[0], fallback_used=False, note="")

    monkeypatch.setattr("src.signals.webpage_source.WebpageSource", _FakeWebSource)
    monkeypatch.setattr("src.web.AiTriage", _FakeTriage)
    monkeypatch.setattr("src.web.resolve_llm_config",
                        lambda m: {"api_key": None, "auth_token": "t", "base_url": "u", "model": "m"})

    resp = client.post("/api/settings/sources/test", json={
        "url": "https://example.com/page", "type": "webpage", "instruction": "提取要点",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 2
    assert data["ai_used"] is True
    assert data["items"] == [{"title": "要点一", "kept": True}, {"title": "要点二", "kept": False}]


def test_test_source_webpage_requires_instruction(signals_db):
    resp = client.post("/api/settings/sources/test",
                       json={"url": "https://example.com/p", "type": "webpage"})
    assert resp.status_code == 422


def test_topic_source_crud(signals_db):
    payload = _custom_payload(name="gs_china_view", type="topic", url="",
                              instruction="高盛对中国股市的最新观点")
    assert client.post("/api/settings/sources/custom", json=payload).status_code == 201

    sources = client.get("/api/settings/sources").json()
    entry = [s for s in sources if s["name"] == "gs_china_view"][0]
    assert entry["type"] == "topic"
    assert entry["url"] == ""
    assert entry["instruction"] == "高盛对中国股市的最新观点"


def test_topic_source_requires_topic(signals_db):
    resp = client.post(
        "/api/settings/sources/custom",
        json=_custom_payload(type="topic", url="", instruction=""),
    )
    assert resp.status_code == 422


def test_topic_source_rejects_bad_url(signals_db):
    resp = client.post(
        "/api/settings/sources/custom",
        json=_custom_payload(type="topic", url="ftp://x", instruction="主题"),
    )
    assert resp.status_code == 422


def test_topic_edit_cannot_drop_instruction(signals_db):
    payload = _custom_payload(name="tp", type="topic", url="", instruction="主题")
    assert client.post("/api/settings/sources/custom", json=payload).status_code == 201
    resp = client.put("/api/settings/sources/custom/tp", json={"instruction": " "})
    assert resp.status_code == 422


def test_test_source_topic_preview(signals_db, monkeypatch, make_signal):
    """Topic test runs a real search + triage preview with per-item keep flags."""
    class _FakeTopicSource:
        def __init__(self, **kwargs):
            self.fetch_note = ""

        async def fetch(self, quarter):
            return [make_signal(id="t1", title="要点一"), make_signal(id="t2", title="要点二")]

        async def close(self):
            pass

    class _FakeTriage:
        def __init__(self, *a, **kw):
            pass

        async def triage(self, items, label, policy):
            from src.signals.ai_triage import TriageResult
            return TriageResult(kept_indices=[1], fallback_used=False, note="")

    monkeypatch.setattr("src.signals.topic_source.TopicSource", _FakeTopicSource)
    monkeypatch.setattr("src.web.AiTriage", _FakeTriage)
    monkeypatch.setattr("src.web.resolve_llm_config",
                        lambda m: {"api_key": None, "auth_token": "t", "base_url": "u", "model": "m"})

    resp = client.post("/api/settings/sources/test", json={
        "type": "topic", "instruction": "高盛对中国股市的最新观点", "filter_policy": "gs_only",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["ai_used"] is True
    assert data["items"] == [{"title": "要点一", "kept": False}, {"title": "要点二", "kept": True}]


def test_test_source_topic_requires_instruction(signals_db):
    resp = client.post("/api/settings/sources/test", json={"type": "topic"})
    assert resp.status_code == 422


def test_daily_report_endpoint_delegates(monkeypatch):
    import src.web as web

    async def _fake(date):
        return {"date": date, "report": "伪日报", "signal_count": 1, "cached": True}

    monkeypatch.setattr(web, "generate_daily_report", _fake)

    async def _none(date):
        return None

    monkeypatch.setattr(web, "ensure_daily_report", _none)
    resp = client.get("/api/daily-report/2026-07-27")
    assert resp.status_code == 200
    assert resp.json()["report"] == "伪日报"


def test_daily_report_endpoint_bad_date():
    resp = client.get("/api/daily-report/2026-13-99")
    assert resp.status_code == 422


def test_quarter_insight_endpoint_delegates(monkeypatch):
    import src.web as web

    async def _fake(quarter, previous=None, force=False):
        return {"quarter": quarter, "report": "伪季度洞察", "cached": True}

    monkeypatch.setattr(web, "generate_quarter_insight", _fake)

    async def _none(quarter, previous=None):
        return None

    monkeypatch.setattr(web, "ensure_quarter_insight", _none)
    resp = client.get("/api/quarter-insight/2026-Q1?previous=2025-Q4")
    assert resp.status_code == 200
    assert resp.json()["report"] == "伪季度洞察"


def test_quarter_insight_endpoint_bad_quarter():
    resp = client.get("/api/quarter-insight/2026-Q5")
    assert resp.status_code == 422


def test_quarter_insight_regenerate(monkeypatch):
    import src.web as web

    async def _fake(quarter, previous=None, force=False):
        assert force is True
        return {"quarter": quarter, "report": "重新生成的洞察", "cached": False}

    monkeypatch.setattr(web, "generate_quarter_insight", _fake)
    resp = client.post("/api/quarter-insight/2026-Q1/regenerate")
    assert resp.status_code == 200
    assert resp.json()["report"] == "重新生成的洞察"


def test_dashboard_quarter_view_layout(tmp_path, monkeypatch):
    """Quarter reports live in the main content area like the daily view:
    a quarter selector replaces the sidebar quarter list, and in-content
    tabs offer both a stacked long page and per-module views."""
    monkeypatch.setattr("src.web.REPORT_OUTPUT_DIR", tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    # Quarter selector in the content header; sidebar quarter list gone
    assert 'id="quarterSelect"' in response.text
    assert 'id="quarterList"' not in response.text
    assert 'id="moduleSection"' not in response.text
    # In-content tabs: stacked long page + per-module views + QoQ changes
    # (tab keys are rendered dynamically from QUARTER_TABS)
    assert "data-qtab" in response.text
    assert "'changes'" in response.text
    assert "持仓变化" in response.text
    # AI quarterly insight wiring
    assert "quarter-insight" in response.text


def test_dashboard_mobile_date_picker_min_width(tmp_path, monkeypatch):
    """On mobile the date input keeps a min-width so the full date stays
    visible instead of being squeezed to '2026/07'."""
    monkeypatch.setattr("src.web.REPORT_OUTPUT_DIR", tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "min-width: 160px" in response.text


def test_dashboard_recon_source_report(tmp_path, monkeypatch):
    """Manual quarterly reconciliation shows a per-source fetch report,
    like the daily intel progress panel."""
    monkeypatch.setattr("src.web.REPORT_OUTPUT_DIR", tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "showReconReport" in response.text
    assert "季度对账信息源汇报" in response.text
