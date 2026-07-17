import pytest
from unittest.mock import AsyncMock, patch

from src.main import main, run_pipeline


def test_main_without_args_prints_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "usage" in captured.out


@pytest.mark.asyncio
async def test_run_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)

    import pandas as pd

    mock_df = pd.DataFrame(
        {
            "cusip": ["A"],
            "name_of_issuer": ["Apple"],
            "title_of_class": ["COM"],
            "value": [1000000.0],
            "shares": [1000],
            "investment_discretion": ["SOLE"],
        }
    )

    with patch("src.main.SEC13FFetcher") as MockFetcher:
        instance = MockFetcher.return_value.__aenter__.return_value
        instance.fetch_latest_holdings = AsyncMock(return_value=mock_df)
        with patch("src.main.GSAnalyzer") as MockAnalyzer:
            analyzer = MockAnalyzer.return_value
            analyzer.analyze_holdings = AsyncMock(return_value=AsyncMock())
            with patch("src.main.ReportGenerator") as MockReporter:
                reporter = MockReporter.return_value
                reporter.generate_report = lambda *args, **kwargs: tmp_path / "2026-Q1.html"
                await run_pipeline()
                assert instance.fetch_latest_holdings.called
