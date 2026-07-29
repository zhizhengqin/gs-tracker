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


def test_real_template_splits_sentiment_and_confidence(tmp_path):
    """The dashboard parses 情绪信号 and 置信度 from separate <p> elements;
    merging them into one paragraph breaks extraction (NaN% on the dashboard)."""
    gen = ReportGenerator()  # real project template

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
        sentiment="bullish",
        confidence=0.85,
    )
    path = gen.generate_report("2026-Q1", holdings, analysis, output_path=tmp_path / "r.html")
    html = path.read_text(encoding="utf-8")

    # Two separate paragraphs, each cleanly extractable
    assert '<span class="label">情绪信号：</span>偏多</p>' in html
    assert '<span class="label">置信度：</span>85%</p>' in html
    # The old merged format must be gone
    assert "（置信度：" not in html.split("情绪信号")[1][:200]


def test_real_template_embeds_only_top_holdings(tmp_path):
    """The static report ships just the top positions (the full list is
    served via /api/holdings) so quarter pages stay small on slow links."""
    from src.reporter import HOLDINGS_PREVIEW_LIMIT

    gen = ReportGenerator()  # real project template
    n = HOLDINGS_PREVIEW_LIMIT + 50
    holdings = pd.DataFrame(
        {
            "name_of_issuer": [f"Company {i:04d}" for i in range(n)],
            # Deliberately unsorted: largest value sits in the middle
            "value": [float((i * 7919) % n) for i in range(n)],
        }
    )
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
    path = gen.generate_report("2026-Q1", holdings, analysis, output_path=tmp_path / "r.html")
    html = path.read_text(encoding="utf-8")

    # Full count is stamped on the table for the dashboard to pick up
    assert f'data-total-holdings="{n}"' in html
    # Only the preview rows are rendered
    tbody = html.split("<tbody>")[1].split("</tbody>")[0]
    assert tbody.count("<tr>") == HOLDINGS_PREVIEW_LIMIT
    # Truncation note is shown
    assert f"共 {n} 条记录" in html
    # Rows are sorted by value desc: the largest holding comes first
    first_row = html.split("<tbody>")[1].split("<tr>")[1]
    assert f"{float(n - 1):,.0f}" in first_row
