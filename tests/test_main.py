import json

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

    @pytest.fixture(autouse=True)
    def _default_settings(self):
        """Keep sources_config reads hermetic: default = all sources enabled."""
        with patch("src.main.get_setting", return_value=""):
            yield

    @pytest.fixture
    def _mock_sources(self):
        """Patch all four source classes; yields the mock classes dict."""
        mocks = {}
        with patch("src.main.NewsSource") as mock_news, \
             patch("src.main.Sec8kSource") as mock_8k, \
             patch("src.main.ResearchViewSource") as mock_rv, \
             patch("src.main.ThirteenDGSource") as mock_dg:
            for cls in (mock_news, mock_rv, mock_dg):
                cls.return_value.fetch_since = AsyncMock(return_value=([], None))
                cls.return_value.close = AsyncMock()
            mock_8k.return_value.fetch = AsyncMock(return_value=[])
            mock_8k.return_value.close = AsyncMock()
            # 8-K source doesn't have fetch_since — delete auto-created MagicMock attr
            del mock_8k.return_value.fetch_since
            mocks.update(news=mock_news, sec8k=mock_8k, research=mock_rv, dg=mock_dg)
            yield mocks

    @pytest.fixture
    def _mock_storage(self):
        with patch("src.main.get_source_state", return_value=None), \
             patch("src.main.save_source_state"), \
             patch("src.main.save_signals_incremental"), \
             patch("src.main.save_signal_run"), \
             patch("src.main.cleanup_expired_signals"):
            yield

    @pytest.mark.asyncio
    async def test_run_daily_intel_returns_status_dict(self, tmp_path, monkeypatch, _mock_sources, _mock_storage):
        """Daily intel should complete without LLM calls and return structured status."""
        monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.main.RSS_FEEDS", [])

        from src.main import run_daily_intel

        result = await run_daily_intel()

        assert "new_signals" in result
        assert "total_scored" in result
        assert "source_status" in result
        assert "errors" in result
        assert isinstance(result["source_status"], dict)
        assert isinstance(result["errors"], list)

    @pytest.mark.asyncio
    async def test_run_daily_intel_handles_source_failure(self, tmp_path, monkeypatch, _mock_sources, _mock_storage):
        """One source failing should not crash the job — partial result returned."""
        monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.main.RSS_FEEDS", [])
        _mock_sources["sec8k"].return_value.fetch = AsyncMock(side_effect=RuntimeError("SEC down"))

        from src.main import run_daily_intel

        result = await run_daily_intel()

        assert result["new_signals"] == 0
        assert len(result["errors"]) >= 1
        assert "SEC down" in str(result["errors"])

    @pytest.mark.asyncio
    async def test_stream_emits_start_source_done_complete(self, tmp_path, monkeypatch, _mock_sources, _mock_storage):
        """Regression: stream must yield start → source_done per source → complete.

        (A task->name dict lookup around as_completed used to crash the stream
        right after the start event — the production '等待中 forever' bug.)
        """
        monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.main.RSS_FEEDS", [])

        from src.main import run_daily_intel_stream

        events = []
        async for ev in run_daily_intel_stream():
            events.append(json.loads(ev))

        assert events[0]["event"] == "start"
        done_events = [e for e in events if e["event"] == "source_done"]
        # RSS_FEEDS empty → no news source; 8-K + 13D/13G + research_view remain
        assert len(done_events) == 3
        assert {e["source"] for e in done_events} == {"8-K", "13D/13G", "research_view"}
        assert events[-1]["event"] == "complete"

    @pytest.mark.asyncio
    async def test_build_daily_sources_respects_enabled_flags(self, monkeypatch):
        """Disabled sources in sources_config must be skipped."""
        monkeypatch.setattr("src.main.RSS_FEEDS", ["https://example.test/rss"])
        config = json.dumps([
            {"name": "8-K", "enabled": False},
            {"name": "13D/13G", "enabled": True},
            {"name": "research_view", "enabled": False},
            {"name": "news", "enabled": True},
        ])
        with patch("src.main.get_setting", return_value=config), \
             patch("src.main.NewsSource"), \
             patch("src.main.ThirteenDGSource"), \
             patch("src.main.Sec8kSource"), \
             patch("src.main.ResearchViewSource"):
            from src.main import _build_daily_sources

            sources = _build_daily_sources()

        assert [n for n, _ in sources] == ["13D/13G", "news"]

    @pytest.mark.asyncio
    async def test_all_rss_feeds_merges_custom_sources(self, monkeypatch):
        """Custom RSS entries from settings merge with env feeds (dupes excluded)."""
        monkeypatch.setattr("src.main.RSS_FEEDS", ["https://base.test/rss"])
        config = json.dumps([
            {"name": "custom1", "type": "rss", "url": "https://custom.test/feed", "enabled": True},
            {"name": "custom2", "type": "rss", "url": "https://off.test/feed", "enabled": False},
            {"name": "dup", "type": "rss", "url": "https://base.test/rss", "enabled": True},
        ])
        with patch("src.main.get_setting", return_value=config):
            from src.main import _all_rss_feeds

            feeds = _all_rss_feeds()

        assert feeds == ["https://base.test/rss", "https://custom.test/feed"]
