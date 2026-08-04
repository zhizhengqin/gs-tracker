"""Tests for src.cross_analysis (GS vs JPM divergence read)."""
from datetime import datetime, timezone

import pytest

import src.cross_analysis as ca
from src.signals.base import Signal, SignalStrength


def _signal(sid="s1", inst="gs", companies=None, title="标题", source="news"):
    return Signal(
        title=title, source=source, published_at=datetime.now(timezone.utc),
        summary="摘要", companies=companies or [], strength=SignalStrength.MEDIUM,
        url=None, id=sid, institution_id=inst,
    )


# ====== find_counterparts（纯函数） ======

def test_counterpart_other_institution_shared_company():
    sig = _signal(inst="gs", companies=["NVIDIA CORP"])
    cands = [
        _signal(sid="s2", inst="jpm", companies=["NVIDIA CORP"]),
        _signal(sid="s3", inst="gs", companies=["NVIDIA CORP"]),   # 同机构不算
        _signal(sid="s4", inst="jpm", companies=["APPLE INC"]),    # 不同标的不算
        _signal(sid="s5", inst="all", companies=["NVIDIA CORP"]),  # 聚合源不算
    ]
    out = ca.find_counterparts(sig, cands)
    assert [c.id for c in out] == ["s2"]


def test_counterpart_excludes_self_and_institution_tokens():
    sig = _signal(inst="jpm", companies=["高盛"])
    cands = [_signal(sid="s2", inst="gs", companies=["高盛"])]
    assert ca.find_counterparts(sig, cands) == []
    # 信号自己只有机构自指词时也没有对手方
    assert ca.find_counterparts(_signal(inst="gs", companies=["摩根大通"]), cands) == []


def test_counterpart_company_case_insensitive():
    sig = _signal(inst="gs", companies=["Nvidia Corp"])
    cands = [_signal(sid="s2", inst="jpm", companies=["NVIDIA CORP"])]
    assert len(ca.find_counterparts(sig, cands)) == 1


def test_counterpart_excludes_itself():
    sig = _signal(sid="s1", inst="gs", companies=["TESLA"])
    out = ca.find_counterparts(sig, [sig])
    assert out == []


# ====== generate_cross_analysis ======

class _FakeClient:
    def __init__(self, text="## 一致点\n都看多"):
        self.text = text
        self.messages = self._Messages(self)

    class _Messages:
        def __init__(self, outer):
            self._outer = outer

        async def create(self, **kwargs):
            class _Block:
                pass

            class _Resp:
                pass

            block = _Block()
            block.text = self._outer.text
            resp = _Resp()
            resp.content = [block] if self._outer.text else []
            return resp


def _patch_common(monkeypatch, signal, candidates, cached=None):
    saved = {}
    monkeypatch.setattr(ca, "get_cross_analysis", lambda i: cached)
    monkeypatch.setattr(ca, "save_cross_analysis",
                        lambda i, text: saved.update(id=i, text=text))
    monkeypatch.setattr(ca, "get_signal_by_id", lambda i: signal)
    monkeypatch.setattr(ca, "get_signals_in_range", lambda a, b: candidates)
    monkeypatch.setattr(ca, "get_default_llm_model", lambda: None)
    return saved


@pytest.mark.asyncio
async def test_cached_short_circuits(monkeypatch):
    _patch_common(monkeypatch, None, [], cached="旧解读")
    assert await ca.generate_cross_analysis("s1") == "旧解读"


@pytest.mark.asyncio
async def test_missing_signal_raises_keyerror(monkeypatch):
    _patch_common(monkeypatch, None, [])
    with pytest.raises(KeyError):
        await ca.generate_cross_analysis("nope")


@pytest.mark.asyncio
async def test_no_counterparts_returns_notice_not_cached(monkeypatch):
    sig = _signal(inst="gs", companies=["NVIDIA CORP"])
    saved = _patch_common(monkeypatch, sig, [])
    text = await ca.generate_cross_analysis("s1")
    assert "暂未发现其他机构" in text
    assert saved == {}  # 不缓存，未来对手方出现后还能再试


@pytest.mark.asyncio
async def test_no_llm_raises_not_cached(monkeypatch):
    sig = _signal(inst="gs", companies=["NVIDIA CORP"])
    cands = [_signal(sid="s2", inst="jpm", companies=["NVIDIA CORP"])]
    saved = _patch_common(monkeypatch, sig, cands)
    monkeypatch.setattr(
        ca, "resolve_llm_config",
        lambda m: {"api_key": None, "auth_token": None, "base_url": None, "model": "x"},
    )
    with pytest.raises(ca.CrossAnalysisError):
        await ca.generate_cross_analysis("s1")
    assert saved == {}


@pytest.mark.asyncio
async def test_success_caches_and_prompt_mentions_both(monkeypatch):
    sig = _signal(inst="gs", companies=["NVIDIA CORP"], title="高盛看多英伟达")
    cands = [_signal(sid="s2", inst="jpm", companies=["NVIDIA CORP"], title="JPM raises NVDA")]
    saved = _patch_common(monkeypatch, sig, cands)
    monkeypatch.setattr(
        ca, "resolve_llm_config",
        lambda m: {"api_key": "k", "auth_token": None, "base_url": None, "model": "x"},
    )
    client = _FakeClient("## 一致点\n两家都看多")
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: client)
    text = await ca.generate_cross_analysis("s1")
    assert text == "## 一致点\n两家都看多"
    assert saved["id"] == "s1"


@pytest.mark.asyncio
async def test_empty_llm_response_raises(monkeypatch):
    sig = _signal(inst="gs", companies=["NVIDIA CORP"])
    cands = [_signal(sid="s2", inst="jpm", companies=["NVIDIA CORP"])]
    saved = _patch_common(monkeypatch, sig, cands)
    monkeypatch.setattr(
        ca, "resolve_llm_config",
        lambda m: {"api_key": "k", "auth_token": None, "base_url": None, "model": "x"},
    )
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: _FakeClient(""))
    with pytest.raises(ca.CrossAnalysisError):
        await ca.generate_cross_analysis("s1")
    assert saved == {}
