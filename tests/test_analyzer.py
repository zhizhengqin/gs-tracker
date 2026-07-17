"""Tests for src.analyzer."""
import pytest

from src.analyzer import GSAnalyzer


@pytest.mark.asyncio
async def test_analyzer_initializes_without_key(monkeypatch):
    monkeypatch.setattr("src.analyzer.ANTHROPIC_API_KEY", "")
    analyzer = GSAnalyzer()
    assert analyzer.client.api_key == ""


def test_analysis_result_dataclass():
    from src.analyzer import AnalysisResult

    result = AnalysisResult(
        summary="Test",
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
