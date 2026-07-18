import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.data_fetcher import SEC13FFetcher
from src.main import main, run_pipeline


def test_main_without_args_prints_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "usage" in captured.out


@pytest.mark.asyncio
async def test_run_pipeline_derives_quarter_from_report_date(tmp_path, monkeypatch):
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

    async def fake_fetch(filing_info):
        filing_info["report_date"] = "2026-06-30"
        return mock_df

    with patch("src.main.SEC13FFetcher") as MockFetcher:
        MockFetcher.report_date_to_quarter = SEC13FFetcher.report_date_to_quarter
        instance = MockFetcher.return_value.__aenter__.return_value
        instance.fetch_latest_holdings = fake_fetch
        with patch("src.main.save_holdings") as mock_save:
            with patch("src.main.GSAnalyzer") as MockAnalyzer:
                analyzer = MockAnalyzer.return_value
                analyzer.analyze_holdings = AsyncMock(return_value=AsyncMock())
                with patch("src.main.ReportGenerator") as MockReporter:
                    reporter = MockReporter.return_value
                    reporter.generate_report = lambda *args, **kwargs: tmp_path / "2026-Q2.html"
                    await run_pipeline()
                    mock_save.assert_called_once()
                    assert mock_save.call_args.args[1] == "2026-Q2"


@pytest.mark.asyncio
async def test_run_pipeline_sends_notification_after_report(tmp_path, monkeypatch):
    monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)

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

    async def fake_fetch(filing_info):
        filing_info["report_date"] = "2026-06-30"
        return mock_df

    with patch("src.main.SEC13FFetcher") as MockFetcher:
        MockFetcher.report_date_to_quarter = SEC13FFetcher.report_date_to_quarter
        instance = MockFetcher.return_value.__aenter__.return_value
        instance.fetch_latest_holdings = fake_fetch
        with patch("src.main.save_holdings"):
            with patch("src.main.GSAnalyzer") as MockAnalyzer:
                analyzer = MockAnalyzer.return_value
                analyzer.analyze_holdings = AsyncMock(return_value=MagicMock())
                with patch("src.main.ReportGenerator") as MockReporter:
                    reporter = MockReporter.return_value
                    reporter.generate_report = lambda *args, **kwargs: tmp_path / "2026-Q2.html"
                    with patch("src.main.Notifier") as MockNotifier:
                        notifier = MockNotifier.return_value
                        notifier.send = AsyncMock()
                        notifier.close = AsyncMock()
                        with patch(
                            "src.main.mark_notification_sent", return_value=True
                        ) as mock_mark:
                            with patch("src.main.FEISHU_WEBHOOK", "https://fake.webhook"):
                                with patch("src.main.PUBLIC_BASE_URL", "https://example.com"):
                                    with patch("src.main.get_holdings", return_value=[]):
                                        await run_pipeline()
                                        notifier.send.assert_awaited_once()
                                        mock_mark.assert_called_once_with("2026-Q2")


@pytest.mark.asyncio
async def test_run_pipeline_marks_notification_after_success(tmp_path, monkeypatch):
    monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)

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

    async def fake_fetch(filing_info):
        filing_info["report_date"] = "2026-06-30"
        return mock_df

    with patch("src.main.SEC13FFetcher") as MockFetcher:
        MockFetcher.report_date_to_quarter = SEC13FFetcher.report_date_to_quarter
        instance = MockFetcher.return_value.__aenter__.return_value
        instance.fetch_latest_holdings = fake_fetch
        with patch("src.main.save_holdings"):
            with patch("src.main.GSAnalyzer") as MockAnalyzer:
                analyzer = MockAnalyzer.return_value
                analyzer.analyze_holdings = AsyncMock(return_value=MagicMock())
                with patch("src.main.ReportGenerator") as MockReporter:
                    reporter = MockReporter.return_value
                    reporter.generate_report = lambda *args, **kwargs: tmp_path / "2026-Q2.html"
                    with patch("src.main.Notifier") as MockNotifier:
                        notifier = MockNotifier.return_value
                        notifier.send = AsyncMock(side_effect=RuntimeError("boom"))
                        notifier.close = AsyncMock()
                        with patch("src.main.mark_notification_sent") as mock_mark:
                            with patch("src.main.FEISHU_WEBHOOK", "https://fake.webhook"):
                                with patch("src.main.PUBLIC_BASE_URL", "https://example.com"):
                                    with patch("src.main.get_holdings", return_value=[]):
                                        await run_pipeline()
                                        notifier.send.assert_awaited_once()
                                        mock_mark.assert_not_called()
