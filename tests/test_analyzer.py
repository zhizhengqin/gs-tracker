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
async def test_analyze_holdings_parses_json_response(monkeypatch):
    monkeypatch.setattr("src.analyzer.ANTHROPIC_API_KEY", "test-key")
    analyzer = GSAnalyzer()

    fake_json = """{
        "summary": "总体摘要",
        "concentration_analysis": "集中度分析",
        "top_holdings_analysis": "重仓分析",
        "sector_preference": "行业偏好",
        "trading_signals": "交易信号",
        "risk_warnings": "风险提示",
        "retail_insights": "散户启示",
        "sentiment": "bullish",
        "confidence": 0.75
    }"""

    class FakeResponse:
        content = [type("Block", (), {"text": fake_json})()]

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
    assert result.summary == "总体摘要"
    assert result.trading_signals == "交易信号"
    assert result.sentiment == "bullish"
    assert result.confidence == 0.75


@pytest.mark.asyncio
async def test_analyze_holdings_falls_back_to_raw_text(monkeypatch):
    monkeypatch.setattr("src.analyzer.ANTHROPIC_API_KEY", "test-key")
    analyzer = GSAnalyzer()

    class FakeResponse:
        content = [type("Block", (), {"text": "测试分析结果"})()]

    async def fake_create(*args, **kwargs):
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
    assert result.summary == "测试分析结果"
    assert result.sentiment == "neutral"
    assert result.confidence == 0.5


@pytest.mark.asyncio
async def test_analyze_holdings_handles_empty_response(monkeypatch):
    monkeypatch.setattr("src.analyzer.ANTHROPIC_API_KEY", "test-key")
    analyzer = GSAnalyzer()

    class FakeResponse:
        content = []

    async def fake_create(*args, **kwargs):
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
    assert result.summary == ""
    assert isinstance(result, AnalysisResult)
