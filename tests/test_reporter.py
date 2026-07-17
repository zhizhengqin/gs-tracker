"""Tests for src.reporter."""

import pandas as pd
from src.reporter import ReportGenerator
from src.analyzer import AnalysisResult


def test_generate_report_creates_file(tmp_path):
    gen = ReportGenerator(template_dir=tmp_path / "templates")
    # Create a minimal template
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "report.html").write_text("<html>{{ quarter }}</html>")

    holdings = pd.DataFrame(
        {
            "name_of_issuer": ["Apple"],
            "value": [1000000.0],
        }
    )
    analysis = AnalysisResult(
        summary="摘要",
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
    path = gen.generate_report("2026-Q1", holdings, analysis, output_path=tmp_path / "report.html")
    assert path.exists()
    assert "2026-Q1" in path.read_text()


def test_generate_report_uses_quarter_filename(tmp_path, monkeypatch):
    monkeypatch.setattr("src.reporter.REPORT_OUTPUT_DIR", tmp_path)

    gen = ReportGenerator(template_dir=tmp_path / "templates")
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "report.html").write_text("<html>{{ quarter }}</html>")

    holdings = pd.DataFrame({"name_of_issuer": ["Apple"], "value": [1000000.0]})
    analysis = AnalysisResult(
        summary="",
        concentration_analysis="",
        top_holdings_analysis="",
        sector_preference="",
        trading_signals="",
        risk_warnings="",
        retail_insights="",
        key_tickers=[],
        sentiment="neutral",
        confidence=0.5,
    )
    path = gen.generate_report("2026-Q1", holdings, analysis)
    assert path == tmp_path / "2026-Q1.html"
    assert path.exists()
