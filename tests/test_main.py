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
                            with patch(
                                "src.main.is_notification_sent", return_value=False
                            ):
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
                            with patch(
                                "src.main.is_notification_sent", return_value=False
                            ):
                                with patch("src.main.FEISHU_WEBHOOK", "https://fake.webhook"):
                                    with patch("src.main.PUBLIC_BASE_URL", "https://example.com"):
                                        with patch("src.main.get_holdings", return_value=[]):
                                            await run_pipeline()
                                            notifier.send.assert_awaited_once()
                                            mock_mark.assert_not_called()


@pytest.mark.asyncio
async def test_run_pipeline_skips_notification_when_already_sent(tmp_path, monkeypatch):
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
                        with patch("src.main.mark_notification_sent") as mock_mark:
                            with patch(
                                "src.main.is_notification_sent", return_value=True
                            ) as mock_is_sent:
                                with patch("src.main.FEISHU_WEBHOOK", "https://fake.webhook"):
                                    with patch("src.main.PUBLIC_BASE_URL", "https://example.com"):
                                        with patch("src.main.get_holdings", return_value=[]):
                                            await run_pipeline()
                                            mock_is_sent.assert_called_once_with("2026-Q2")
                                            MockNotifier.assert_not_called()
                                            notifier.send.assert_not_awaited()
                                            mock_mark.assert_not_called()


class TestPreviousQuarter:
    def test_q2_returns_q1(self):
        from src.main import _previous_quarter
        assert _previous_quarter("2026-Q2") == "2026-Q1"

    def test_q1_returns_previous_year_q4(self):
        from src.main import _previous_quarter
        assert _previous_quarter("2026-Q1") == "2025-Q4"

    def test_q4_returns_q3(self):
        from src.main import _previous_quarter
        assert _previous_quarter("2026-Q4") == "2026-Q3"

    def test_q3_returns_q2(self):
        from src.main import _previous_quarter
        assert _previous_quarter("2026-Q3") == "2026-Q2"


class TestDailyIntel:
    """Smoke tests for the daily intelligence job — no LLM, no 13F."""

    @pytest.mark.asyncio
    async def test_run_daily_intel_returns_status_dict(self, tmp_path, monkeypatch):
        """Daily intel should complete without LLM calls and return structured status."""
        monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.main.RSS_FEEDS", [])

        with patch("src.main.NewsSource") as MockNews:
            MockNews.return_value.fetch_since = AsyncMock(return_value=([], None))
            MockNews.return_value.close = AsyncMock()
            with patch("src.main.Sec8kSource") as Mock8k:
                Mock8k.return_value.fetch = AsyncMock(return_value=[])
                Mock8k.return_value.close = AsyncMock()
                # 8-K source doesn't have fetch_since — delete auto-created MagicMock attr
                del Mock8k.return_value.fetch_since
                with patch("src.main.ThirteenDGSource") as Mock13dg:
                    Mock13dg.return_value.fetch_since = AsyncMock(return_value=([], None))
                    Mock13dg.return_value.close = AsyncMock()
                    with patch("src.main.get_source_state", return_value=None):
                        with patch("src.main.save_source_state"):
                            with patch("src.main.save_signals_incremental"):
                                with patch("src.main.save_signal_run"):
                                    with patch("src.main.cleanup_expired_signals"):
                                        from src.main import run_daily_intel

                                        result = await run_daily_intel()

        assert "new_signals" in result
        assert "total_scored" in result
        assert "source_status" in result
        assert "errors" in result
        assert isinstance(result["source_status"], dict)
        assert isinstance(result["errors"], list)

    @pytest.mark.asyncio
    async def test_run_daily_intel_handles_source_failure(self, tmp_path, monkeypatch):
        """One source failing should not crash the job — partial result returned."""
        monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.main.RSS_FEEDS", [])

        with patch("src.main.NewsSource") as MockNews2:
            MockNews2.return_value.fetch_since = AsyncMock(return_value=([], None))
            MockNews2.return_value.close = AsyncMock()
            with patch("src.main.ThirteenDGSource") as Mock13dg:
                Mock13dg.return_value.fetch_since = AsyncMock(return_value=([], None))
                Mock13dg.return_value.close = AsyncMock()
                with patch("src.main.Sec8kSource") as Mock8k:
                    Mock8k.return_value.fetch = AsyncMock(side_effect=RuntimeError("SEC down"))
                    Mock8k.return_value.close = AsyncMock()
                    del Mock8k.return_value.fetch_since
                    with patch("src.main.get_source_state", return_value=None):
                        with patch("src.main.save_source_state"):
                            with patch("src.main.save_signals_incremental"):
                                with patch("src.main.save_signal_run"):
                                    with patch("src.main.cleanup_expired_signals"):
                                        from src.main import run_daily_intel

                                        result = await run_daily_intel()

        assert result["new_signals"] == 0
        assert len(result["errors"]) >= 1
        assert "SEC down" in str(result["errors"])
