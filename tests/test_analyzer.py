"""Tests for src/analyzer."""
import pytest

from src.analyzer import GSAnalyzer, AnalysisResult


def test_analysis_result_structure():
    result = AnalysisResult(
        summary="测试摘要",
        concentration_analysis="",
        top_holdings_analysis="",
        sector_preference="",
        trading_signals="",
        risk_warnings="",
        retail_insights="",
        key_tickers=["AAPL"],
        sentiment="bullish",
        confidence=0.8,
    )
    assert result.sentiment == "bullish"


@pytest.mark.asyncio
async def test_analyze_holdings_calls_claude(monkeypatch):
    monkeypatch.setattr("src.analyzer.ANTHROPIC_API_KEY", "test-key")
    analyzer = GSAnalyzer()

    class FakeResponse:
        content = [type("Block", (), {"text": "测试分析结果"})()]

    called = False
    async def fake_create(*args, **kwargs):
        nonlocal called
        called = True
        return FakeResponse()

    monkeypatch.setattr(analyzer.client.messages, "create", fake_create)

    import pandas as pd
    df = pd.DataFrame({
        "cusip": ["A"],
        "name_of_issuer": ["Apple"],
        "value": [1000000.0],
        "shares": [1000],
    })
    result = await analyzer.analyze_holdings(df)
    assert called
    assert isinstance(result, AnalysisResult)
