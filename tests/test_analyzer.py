"""Tests for src/analyzer."""
import anthropic
import httpx
import pytest

from src.analyzer import GSAnalyzer, AnalysisResult


def _internal_server_error(message: str = "server error") -> anthropic.InternalServerError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(500, request=request)
    return anthropic.InternalServerError(message, response=response, body=None)


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


@pytest.mark.asyncio
async def test_analyze_holdings_claude_500_fallback(monkeypatch):
    monkeypatch.setattr("src.analyzer.ANTHROPIC_API_KEY", "test-key")
    analyzer = GSAnalyzer()

    async def _no_sleep(*_args, **_kwargs):
        pass

    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    async def failing_create(*args, **kwargs):
        raise _internal_server_error("server error")

    monkeypatch.setattr(analyzer.client.messages, "create", failing_create)

    import pandas as pd
    df = pd.DataFrame({
        "cusip": ["A"],
        "name_of_issuer": ["Apple"],
        "value": [1000000.0],
        "shares": [1000],
    })
    result = await analyzer.analyze_holdings(df)
    assert "AI 分析服务暂不可用" in result.summary
    assert result.sentiment == "neutral"
    assert result.confidence == 0.0
    assert result.key_tickers == ["Apple"]


@pytest.mark.asyncio
async def test_analyze_holdings_claude_retry_then_success(monkeypatch):
    monkeypatch.setattr("src.analyzer.ANTHROPIC_API_KEY", "test-key")
    analyzer = GSAnalyzer()

    async def _no_sleep(*_args, **_kwargs):
        pass

    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    valid_json = """{
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

    calls = []

    class FakeResponse:
        content = [type("Block", (), {"text": valid_json})()]

    async def flaky_create(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise _internal_server_error("boom")
        return FakeResponse()

    monkeypatch.setattr(analyzer.client.messages, "create", flaky_create)

    import pandas as pd
    df = pd.DataFrame({
        "cusip": ["A"],
        "name_of_issuer": ["Apple"],
        "value": [1000000.0],
        "shares": [1000],
    })
    result = await analyzer.analyze_holdings(df)
    assert len(calls) == 3
    assert result.summary == "总体摘要"
    assert result.sentiment == "bullish"
    assert result.confidence == 0.75


# ====== LLM provider configuration ======


class _FakeClient:
    """Capture AsyncAnthropic constructor kwargs without any network access."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_init_passes_config_base_url_and_auth_token(monkeypatch):
    """Kimi-style config (base_url + auth_token, no api_key) must reach the client."""
    monkeypatch.setattr("src.analyzer.anthropic.AsyncAnthropic", _FakeClient)
    monkeypatch.setattr("src.analyzer.ANTHROPIC_API_KEY", "")
    monkeypatch.setattr("src.analyzer.ANTHROPIC_AUTH_TOKEN", "tok-123")
    monkeypatch.setattr("src.analyzer.ANTHROPIC_BASE_URL", "https://api.kimi.com/coding")
    monkeypatch.setattr("src.analyzer.GS_LLM_MODEL", "kimi-for-coding")

    analyzer = GSAnalyzer()

    assert analyzer.client.kwargs["auth_token"] == "tok-123"
    assert analyzer.client.kwargs["base_url"] == "https://api.kimi.com/coding"
    assert analyzer.client.kwargs["api_key"] is None
    assert analyzer.model == "kimi-for-coding"


def test_init_empty_config_values_become_none(monkeypatch):
    """Empty strings must become None so the SDK's own env fallback still works."""
    monkeypatch.setattr("src.analyzer.anthropic.AsyncAnthropic", _FakeClient)
    monkeypatch.setattr("src.analyzer.ANTHROPIC_API_KEY", "")
    monkeypatch.setattr("src.analyzer.ANTHROPIC_AUTH_TOKEN", "")
    monkeypatch.setattr("src.analyzer.ANTHROPIC_BASE_URL", "")

    analyzer = GSAnalyzer()

    assert analyzer.client.kwargs["api_key"] is None
    assert analyzer.client.kwargs["auth_token"] is None
    assert analyzer.client.kwargs["base_url"] is None


def test_init_explicit_params_override_config(monkeypatch):
    monkeypatch.setattr("src.analyzer.anthropic.AsyncAnthropic", _FakeClient)
    monkeypatch.setattr("src.analyzer.ANTHROPIC_API_KEY", "cfg-key")
    monkeypatch.setattr("src.analyzer.ANTHROPIC_AUTH_TOKEN", "cfg-tok")
    monkeypatch.setattr("src.analyzer.ANTHROPIC_BASE_URL", "https://cfg.example.com")
    monkeypatch.setattr("src.analyzer.GS_LLM_MODEL", "cfg-model")

    analyzer = GSAnalyzer(
        api_key="arg-key",
        auth_token="arg-tok",
        base_url="https://arg.example.com",
        model="arg-model",
    )

    assert analyzer.client.kwargs["api_key"] == "arg-key"
    assert analyzer.client.kwargs["auth_token"] == "arg-tok"
    assert analyzer.client.kwargs["base_url"] == "https://arg.example.com"
    assert analyzer.model == "arg-model"


@pytest.mark.asyncio
async def test_analyze_holdings_non_retriable_error_returns_placeholder(monkeypatch):
    """Non-retriable API errors (e.g. unknown model on the provider) must not
    crash the pipeline; fall back to placeholder analysis without retrying."""
    monkeypatch.setattr("src.analyzer.ANTHROPIC_API_KEY", "test-key")
    analyzer = GSAnalyzer()

    calls = []

    async def bad_model_create(*args, **kwargs):
        calls.append(1)
        request = httpx.Request("POST", "https://api.kimi.com/coding/v1/messages")
        response = httpx.Response(404, request=request)
        raise anthropic.NotFoundError("model not found", response=response, body=None)

    monkeypatch.setattr(analyzer.client.messages, "create", bad_model_create)

    import pandas as pd
    df = pd.DataFrame({
        "cusip": ["A"],
        "name_of_issuer": ["Apple"],
        "value": [1000000.0],
        "shares": [1000],
    })
    result = await analyzer.analyze_holdings(df)

    assert len(calls) == 1  # no retry on non-retriable errors
    assert "AI 分析服务暂不可用" in result.summary
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_analyze_holdings_skips_thinking_blocks(monkeypatch):
    """Kimi thinking models return a ThinkingBlock before the TextBlock;
    text must be collected from blocks that actually carry text."""
    monkeypatch.setattr("src.analyzer.ANTHROPIC_API_KEY", "test-key")
    analyzer = GSAnalyzer()

    thinking_block = type("ThinkingBlock", (), {"thinking": "嗯……"})()  # no .text attr
    text_block = type("TextBlock", (), {"text": "最终分析"})()

    class FakeResponse:
        content = [thinking_block, text_block]

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
    assert result.summary == "最终分析"
    assert result.confidence == 0.5


@pytest.mark.asyncio
async def test_analyze_holdings_all_thinking_blocks_no_crash(monkeypatch):
    """If every block is a thinking block (tiny budget), degrade gracefully."""
    monkeypatch.setattr("src.analyzer.ANTHROPIC_API_KEY", "test-key")
    analyzer = GSAnalyzer()

    thinking_block = type("ThinkingBlock", (), {"thinking": "嗯……"})()

    class FakeResponse:
        content = [thinking_block]

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
    assert isinstance(result, AnalysisResult)
    assert result.summary == ""
