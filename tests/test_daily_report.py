"""Tests for src.daily_report."""
import asyncio

import pytest

from src.signals.base import Signal, SignalStrength


def _signal(title="高盛看多A股"):
    from datetime import datetime, timezone
    return Signal(
        title=title, source="news", published_at=datetime.now(timezone.utc),
        summary="摘要", companies=[], strength=SignalStrength.MEDIUM, url=None,
    )


class _FakeClient:
    """Scripted LLM client: returns one text block; records call count."""

    def __init__(self, text):
        self.text = text
        self.calls = 0
        self.messages = self._Messages(self)

    class _Messages:
        def __init__(self, outer):
            self._outer = outer

        async def create(self, **kwargs):
            self._outer.calls += 1

            class _Block:
                pass

            class _Resp:
                pass

            block = _Block()
            block.text = self._outer.text
            resp = _Resp()
            resp.content = [block]
            return resp


def _patch_storage(monkeypatch, cached=None, signals=None):
    saved = {}
    monkeypatch.setattr("src.daily_report.get_daily_report", lambda d: cached)
    monkeypatch.setattr("src.daily_report.get_signals_by_date", lambda d: signals or [])
    monkeypatch.setattr(
        "src.daily_report.save_daily_report",
        lambda d, text, count=0: saved.update(date=d, text=text, count=count),
    )
    monkeypatch.setattr("src.daily_report.get_default_llm_model", lambda: None)
    return saved


def _patch_llm(monkeypatch, text="## 今日高盛观点\n看多。\n\n## 今日披露变动\n无。\n\n## 一句话投资启示\n关注。"):
    client = _FakeClient(text)
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: client)
    monkeypatch.setattr(
        "src.daily_report.resolve_llm_config",
        lambda db_model: {"api_key": None, "auth_token": "tok", "base_url": "https://x.test", "model": "m"},
    )
    return client


@pytest.mark.asyncio
async def test_cache_hit_returns_without_llm(monkeypatch):
    from src.daily_report import generate_daily_report
    _patch_storage(monkeypatch, cached={"report_text": "旧日报", "signal_count": 3})
    client = _patch_llm(monkeypatch)
    result = await generate_daily_report("2026-07-27")
    assert result["cached"] is True
    assert result["report"] == "旧日报"
    assert result["signal_count"] == 3
    assert client.calls == 0


@pytest.mark.asyncio
async def test_no_signals_returns_notice_without_llm(monkeypatch):
    from src.daily_report import generate_daily_report
    _patch_storage(monkeypatch, signals=[])
    client = _patch_llm(monkeypatch)
    result = await generate_daily_report("2026-07-27")
    assert result["signal_count"] == 0
    assert "暂无情报" in result["report"]
    assert client.calls == 0


@pytest.mark.asyncio
async def test_no_llm_config_returns_error_not_cached(monkeypatch):
    from src.daily_report import generate_daily_report
    saved = _patch_storage(monkeypatch, signals=[_signal()])
    monkeypatch.setattr(
        "src.daily_report.resolve_llm_config",
        lambda db_model: {"api_key": None, "auth_token": None, "base_url": None, "model": "m"},
    )
    result = await generate_daily_report("2026-07-27")
    assert result["error"] == "no_llm_configured"
    assert "大模型" in result["report"]
    assert saved == {}


@pytest.mark.asyncio
async def test_llm_success_saves_and_returns(monkeypatch):
    from src.daily_report import generate_daily_report
    saved = _patch_storage(monkeypatch, signals=[_signal()])
    client = _patch_llm(monkeypatch)
    result = await generate_daily_report("2026-07-27")
    assert client.calls == 1
    assert "今日高盛观点" in result["report"]
    assert result["cached"] is False
    assert saved["date"] == "2026-07-27"
    assert "今日高盛观点" in saved["text"]
    assert saved["count"] == 1


@pytest.mark.asyncio
async def test_llm_failure_returns_fallback_not_cached(monkeypatch):
    from src.daily_report import generate_daily_report
    saved = _patch_storage(monkeypatch, signals=[_signal()])
    _patch_llm(monkeypatch)

    class _Fail:
        def __init__(self, **kw):
            self.messages = self._M()

        class _M:
            async def create(self, **kw):
                raise RuntimeError("gateway down")

    monkeypatch.setattr("anthropic.AsyncAnthropic", _Fail)
    result = await generate_daily_report("2026-07-27")
    assert "error" in result
    assert "失败" in result["report"]
    assert saved == {}


@pytest.mark.asyncio
async def test_ensure_returns_none_when_cached(monkeypatch):
    import src.daily_report as dr
    _patch_storage(monkeypatch, cached={"report_text": "x", "signal_count": 1})
    assert await dr.ensure_daily_report("2026-07-27") is None


@pytest.mark.asyncio
async def test_ensure_dedupes_concurrent_calls(monkeypatch):
    import src.daily_report as dr
    dr._report_tasks.clear()
    _patch_storage(monkeypatch, signals=[_signal()])
    client = _patch_llm(monkeypatch)
    t1 = await dr.ensure_daily_report("2026-07-27")
    t2 = await dr.ensure_daily_report("2026-07-27")
    assert t1 is not None and t1 is t2
    await t1
    assert client.calls == 1


@pytest.mark.asyncio
async def test_ensure_swallows_generation_errors(monkeypatch):
    import src.daily_report as dr
    dr._report_tasks.clear()
    _patch_storage(monkeypatch, signals=[_signal()])
    _patch_llm(monkeypatch)
    monkeypatch.setattr(
        "src.daily_report.generate_daily_report",
        _raise := lambda d: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    task = await dr.ensure_daily_report("2026-07-27")
    await task  # must not raise
