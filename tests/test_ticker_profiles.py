"""Tests for src.ticker_profiles."""
import json
import sys
import types

import pytest

import src.ticker_profiles as tp


def _holdings():
    return [
        {"name_of_issuer": "NVIDIA CORP", "value": 50.0},
        {"name_of_issuer": "NVIDIA CORP", "value": 10.0},  # second row, same issuer
        {"name_of_issuer": "APPLE INC", "value": 30.0},
        {"name_of_issuer": "TESLA INC", "value": 10.0},
    ]


def test_aggregate_top_holdings_merges_issuer_and_computes_pct():
    top = tp.aggregate_top_holdings(_holdings())
    assert [p["ticker"] for p in top] == ["NVIDIA CORP", "APPLE INC", "TESLA INC"]
    assert top[0]["value"] == 60.0
    assert top[0]["pct"] == 60.0
    assert sum(p["pct"] for p in top) == pytest.approx(100.0)


def test_extract_json_array_tolerates_code_fences():
    text = '前言\n```json\n[{"ticker": "A", "intro": "简介"}]\n```\n后记'
    assert tp._extract_json_array(text) == [{"ticker": "A", "intro": "简介"}]
    assert tp._extract_json_array("没有数组") is None
    assert tp._extract_json_array("[{broken]") is None


def test_merge_profiles_matches_by_ticker():
    base = [
        {"ticker": "A", "value": 1.0, "pct": 50.0, "cn_name": "", "sector": "", "themes": [], "intro": ""},
        {"ticker": "B", "value": 1.0, "pct": 50.0, "cn_name": "", "sector": "", "themes": [], "intro": ""},
    ]
    ai = [{"ticker": "B", "cn_name": "乙公司", "sector": "半导体", "themes": "AI算力，芯片", "intro": "做芯片的。"}]
    merged = tp._merge_profiles(base, ai)
    assert merged[0]["cn_name"] == ""  # unmatched stays base-only
    assert merged[1]["cn_name"] == "乙公司"
    assert merged[1]["themes"] == ["AI算力", "芯片"]


@pytest.mark.asyncio
async def test_cache_hit_returns_cached_profiles(monkeypatch):
    cached = {"profiles_json": json.dumps([{"ticker": "A", "intro": "旧缓存"}])}
    monkeypatch.setattr(tp, "get_ticker_profiles", lambda q, inst="gs": cached)
    result = await tp.generate_ticker_profiles("2026-Q1")
    assert result["cached"] is True
    assert result["profiles"][0]["intro"] == "旧缓存"


@pytest.mark.asyncio
async def test_no_holdings_returns_message(monkeypatch):
    monkeypatch.setattr(tp, "get_ticker_profiles", lambda q, inst="gs": None)
    monkeypatch.setattr(tp, "get_holdings", lambda cik, q: [])
    result = await tp.generate_ticker_profiles("2026-Q1")
    assert result["profiles"] == []
    assert "暂无持仓数据" in result["message"]


@pytest.mark.asyncio
async def test_no_llm_returns_base_profiles_with_error(monkeypatch):
    monkeypatch.setattr(tp, "get_ticker_profiles", lambda q, inst="gs": None)
    monkeypatch.setattr(tp, "get_holdings", lambda cik, q: _holdings())
    monkeypatch.setattr(tp, "get_default_llm_model", lambda: None)
    monkeypatch.setattr(
        tp, "resolve_llm_config",
        lambda m: {"api_key": None, "auth_token": None, "base_url": None, "model": "x"},
    )
    result = await tp.generate_ticker_profiles("2026-Q1")
    assert result["error"] == "no_llm_configured"
    assert result["profiles"][0]["ticker"] == "NVIDIA CORP"
    assert result["profiles"][0]["intro"] == ""


def _fake_anthropic(reply_text):
    """Build a fake `anthropic` module whose client returns reply_text."""
    module = types.ModuleType("anthropic")

    class _Messages:
        async def create(self, **kwargs):
            return types.SimpleNamespace(content=[types.SimpleNamespace(text=reply_text)])

    class AsyncAnthropic:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    module.AsyncAnthropic = AsyncAnthropic
    return module


@pytest.mark.asyncio
async def test_llm_success_merges_and_caches(monkeypatch):
    saved = {}
    monkeypatch.setattr(tp, "get_ticker_profiles", lambda q, inst="gs": None)
    monkeypatch.setattr(tp, "get_holdings", lambda cik, q: _holdings())
    monkeypatch.setattr(tp, "get_default_llm_model", lambda: None)
    monkeypatch.setattr(
        tp, "resolve_llm_config",
        lambda m: {"api_key": "k", "auth_token": None, "base_url": None, "model": "x"},
    )
    monkeypatch.setattr(tp, "save_ticker_profiles", lambda q, payload, inst="gs": saved.setdefault("json", payload))
    reply = json.dumps([
        {"ticker": "NVIDIA CORP", "cn_name": "英伟达", "sector": "半导体",
         "themes": ["AI算力", "GPU"], "intro": "全球 GPU 龙头。"},
    ], ensure_ascii=False)
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic(reply))

    result = await tp.generate_ticker_profiles("2026-Q1")
    assert result["cached"] is False
    top = result["profiles"][0]
    assert top["cn_name"] == "英伟达"
    assert top["themes"] == ["AI算力", "GPU"]
    assert top["pct"] == 60.0
    assert "json" in saved  # merged profiles were cached


@pytest.mark.asyncio
async def test_llm_unparseable_falls_back_to_base(monkeypatch):
    monkeypatch.setattr(tp, "get_ticker_profiles", lambda q, inst="gs": None)
    monkeypatch.setattr(tp, "get_holdings", lambda cik, q: _holdings())
    monkeypatch.setattr(tp, "get_default_llm_model", lambda: None)
    monkeypatch.setattr(
        tp, "resolve_llm_config",
        lambda m: {"api_key": "k", "auth_token": None, "base_url": None, "model": "x"},
    )
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic("抱歉，我无法回答"))

    result = await tp.generate_ticker_profiles("2026-Q1")
    assert result["error"] == "llm_parse_failed"
    assert result["profiles"][0]["ticker"] == "NVIDIA CORP"
