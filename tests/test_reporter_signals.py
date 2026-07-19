"""Tests for signal panel rendering in HTML reports."""
from datetime import datetime, timezone

from src.reporter import ReportGenerator
from src.signals.base import Signal, SignalStrength


class FakeAnalysis:
    summary = "test summary"
    concentration_analysis = "test"
    top_holdings_analysis = "test"
    sector_preference = "test"
    trading_signals = "test"
    risk_warnings = "test"
    retail_insights = "test"
    key_tickers = ["AAPL"]
    sentiment = "neutral"
    confidence = 0.8


def test_generate_report_renders_signal_panel(sample_holdings_df, tmp_path, monkeypatch):
    monkeypatch.setattr("src.reporter.REPORT_OUTPUT_DIR", tmp_path)

    test_signals = [
        Signal(
            title="高盛增持 Apple",
            source="13F",
            published_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
            summary="高盛增持 Apple 5%，持仓市值 $10B",
            companies=["Apple"],
            strength=SignalStrength.HIGH,
        ),
    ]

    reporter = ReportGenerator()
    path = reporter.generate_report(
        quarter="2026-Q2",
        holdings_df=sample_holdings_df,
        analysis=FakeAnalysis(),
        signals=test_signals,
        signal_errors=[],
        source_status={"13F": "ok", "news": "error", "8-K": "ok"},
    )
    content = path.read_text(encoding="utf-8")
    assert "多源信号" in content
    assert "高盛增持 Apple" in content


def test_generate_report_without_signals(sample_holdings_df, tmp_path, monkeypatch):
    """Report should render without signal panel when no signals provided."""
    monkeypatch.setattr("src.reporter.REPORT_OUTPUT_DIR", tmp_path)

    reporter = ReportGenerator()
    path = reporter.generate_report(
        quarter="2026-Q2",
        holdings_df=sample_holdings_df,
        analysis=FakeAnalysis(),
    )
    content = path.read_text(encoding="utf-8")
    assert "2026-Q2" in content
    # No signal-specific content when no signals provided
    assert "高优先级信号" not in content


def test_generate_report_renders_degraded_source_status(sample_holdings_df, tmp_path, monkeypatch):
    """When a source is in error, the panel should show degraded status."""
    monkeypatch.setattr("src.reporter.REPORT_OUTPUT_DIR", tmp_path)

    reporter = ReportGenerator()
    path = reporter.generate_report(
        quarter="2026-Q2",
        holdings_df=sample_holdings_df,
        analysis=FakeAnalysis(),
        signals=[],
        signal_errors=["news 信号获取失败: timeout"],
        source_status={"13F": "ok", "news": "error"},
    )
    content = path.read_text(encoding="utf-8")
    assert "多源信号" in content
    assert "error" in content or "暂不可用" in content
