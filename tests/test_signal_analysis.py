"""Tests for src.signal_analysis (shared per-signal AI analysis)."""
from datetime import datetime, timezone

import pytest

from src.signals.base import Signal, SignalStrength


def _signal(strength=SignalStrength.HIGH, sid="sig-1"):
    return Signal(
        title="高盛上调评级", source="news", published_at=datetime.now(timezone.utc),
        summary="摘要", companies=[], strength=strength, url=None, id=sid,
    )


class _FakeClient:
    """Scripted LLM client: returns queued texts ("" = empty completion)."""

    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0
        self.messages = self._Messages(self)

    class _Messages:
        def __init__(self, outer):
            self._outer = outer

        async def create(self, **kwargs):
            self._outer.calls += 1
            text = self._outer.texts.pop(0) if self._outer.texts else "解读"

            class _Block:
                pass

            class _Resp:
                pass

            block = _Block()
            block.text = text
            resp = _Resp()
            resp.content = [block] if text else []
            return resp


def _patch_storage(monkeypatch, cached=None):
    saved = {}
    monkeypatch.setattr("src.signal_analysis.get_signal_analysis", lambda i: cached)
    monkeypatch.setattr(
        "src.signal_analysis.save_signal_analysis",
        lambda i, text: saved.update(id=i, text=text),
    )
    monkeypatch.setattr("src.signal_analysis.get_default_llm_model", lambda: None)
    return saved


def _patch_llm(monkeypatch, texts=("这是解读",), with_key=True):
    client = _FakeClient(texts)
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: client)
    monkeypatch.setattr(
        "src.signal_analysis.resolve_llm_config",
        lambda db_model: {
            "api_key": None,
            "auth_token": "tok" if with_key else None,
            "base_url": "https://x.test",
            "model": "m",
        },
    )
    return client


@pytest.mark.asyncio
async def test_generate_success_caches(monkeypatch):
    import src.signal_analysis as sa
    saved = _patch_storage(monkeypatch)
    client = _patch_llm(monkeypatch)

    text = await sa.generate_signal_analysis("sig-1", "标题", "摘要", "news")
    assert text == "这是解读"
    assert client.calls == 1
    assert saved == {"id": "sig-1", "text": "这是解读"}


@pytest.mark.asyncio
async def test_generate_retries_empty_completion_once(monkeypatch):
    """第一次返回空时重试一次，第二次有内容则成功。"""
    import src.signal_analysis as sa
    saved = _patch_storage(monkeypatch)
    client = _patch_llm(monkeypatch, texts=("", "重试后的解读"))

    text = await sa.generate_signal_analysis("sig-1", "标题", "摘要", "news")
    assert text == "重试后的解读"
    assert client.calls == 2
    assert saved["text"] == "重试后的解读"


@pytest.mark.asyncio
async def test_generate_raises_after_two_empty_completions(monkeypatch):
    """两次都为空则抛错且不写缓存（下次还能重试）。"""
    import src.signal_analysis as sa
    saved = _patch_storage(monkeypatch)
    _patch_llm(monkeypatch, texts=("", ""))

    with pytest.raises(sa.AnalysisError):
        await sa.generate_signal_analysis("sig-1", "标题", "摘要", "news")
    assert saved == {}


@pytest.mark.asyncio
async def test_generate_raises_without_llm_config(monkeypatch):
    import src.signal_analysis as sa
    saved = _patch_storage(monkeypatch)
    _patch_llm(monkeypatch, with_key=False)

    with pytest.raises(sa.AnalysisError, match="no_llm_configured"):
        await sa.generate_signal_analysis("sig-1", "标题", "摘要", "news")
    assert saved == {}


@pytest.mark.asyncio
async def test_ensure_returns_none_when_cached(monkeypatch):
    import src.signal_analysis as sa
    sa._analysis_tasks.clear()
    _patch_storage(monkeypatch, cached="已有解读")
    client = _patch_llm(monkeypatch)

    assert await sa.ensure_signal_analysis("sig-1", "t", "s", "news") is None
    assert client.calls == 0


@pytest.mark.asyncio
async def test_ensure_treats_sentinel_as_miss(monkeypatch):
    import src.signal_analysis as sa
    sa._analysis_tasks.clear()
    _patch_storage(monkeypatch, cached=sa.ANALYSIS_FAILURE_SENTINEL)
    _patch_llm(monkeypatch)

    task = await sa.ensure_signal_analysis("sig-1", "t", "s", "news")
    assert task is not None
    assert await task == "这是解读"


@pytest.mark.asyncio
async def test_ensure_dedupes_in_flight(monkeypatch):
    """流水线自动生成中用户又点了按钮，复用同一个任务，不重复调 LLM。"""
    import src.signal_analysis as sa
    sa._analysis_tasks.clear()
    _patch_storage(monkeypatch)
    client = _patch_llm(monkeypatch)

    t1 = await sa.ensure_signal_analysis("sig-1", "t", "s", "news")
    t2 = await sa.ensure_signal_analysis("sig-1", "t", "s", "news")
    assert t1 is not None and t1 is t2
    await t1
    assert client.calls == 1


@pytest.mark.asyncio
async def test_auto_analyze_only_high_strength(monkeypatch):
    """只有高优先级信号自动生成解读，其它等级跳过。"""
    import src.signal_analysis as sa
    sa._analysis_tasks.clear()
    _patch_storage(monkeypatch)
    client = _patch_llm(monkeypatch, texts=("解读A", "解读B", "解读C"))

    signals = [
        _signal(SignalStrength.HIGH, "h1"),
        _signal(SignalStrength.MEDIUM, "m1"),
        _signal(SignalStrength.LOW, "l1"),
        _signal(SignalStrength.HIGH, "h2"),
    ]
    count = await sa.auto_analyze_high_signals(signals)
    assert count == 2
    assert client.calls == 2  # 中/低优先级没有调 LLM


@pytest.mark.asyncio
async def test_auto_analyze_swallows_individual_failures(monkeypatch):
    """单个信号生成失败不影响其它信号，也不抛出。"""
    import src.signal_analysis as sa
    sa._analysis_tasks.clear()
    _patch_storage(monkeypatch)
    # h1 两次都空（失败），h2 正常
    client = _patch_llm(monkeypatch, texts=("", "", "解读B"))

    signals = [_signal(SignalStrength.HIGH, "h1"), _signal(SignalStrength.HIGH, "h2")]
    count = await sa.auto_analyze_high_signals(signals)
    assert count == 2  # 两个都尝试了
    assert client.calls == 3
