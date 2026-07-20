"""Integration tests for signal aggregation in the pipeline."""
import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.data_fetcher import SEC13FFetcher
from src.main import run_pipeline


def _mock_df() -> pd.DataFrame:
    """Return the standard one-row holdings DataFrame used by pipeline tests."""
    return pd.DataFrame(
        {
            "cusip": ["A"],
            "name_of_issuer": ["Apple"],
            "title_of_class": ["COM"],
            "value": [1000000.0],
            "shares": [1000],
            "investment_discretion": ["SOLE"],
        }
    )


@pytest.mark.asyncio
async def test_run_pipeline_aggregates_signals(tmp_path, monkeypatch):
    """Pipeline should aggregate signals from all sources."""
    monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)

    mock_df = _mock_df()

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
                    with patch("src.main.SignalAggregator") as MockAgg:
                        mock_agg = MockAgg.return_value
                        mock_result = MagicMock()
                        mock_result.signals = []
                        mock_result.errors = []
                        mock_result.source_status = {"13F": "ok"}
                        mock_agg.aggregate = AsyncMock(return_value=mock_result)
                        mock_agg.close = AsyncMock()

                        with patch("src.main.FEISHU_WEBHOOK", ""):
                            with patch("src.main.get_holdings", return_value=[]):
                                with patch("src.main.save_signal_payload"):
                                    await run_pipeline()
                                    mock_agg.aggregate.assert_awaited_once()
                                    mock_agg.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_pipeline_signal_aggregation_failure_does_not_block_report(
    tmp_path, monkeypatch
):
    """Report should still generate even when signal aggregation fails."""
    monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)

    mock_df = _mock_df()

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
                    with patch("src.main.SignalAggregator") as MockAgg:
                        mock_agg = MockAgg.return_value
                        mock_agg.aggregate = AsyncMock(side_effect=RuntimeError("boom"))
                        mock_agg.close = AsyncMock()

                        with patch("src.main.FEISHU_WEBHOOK", ""):
                            with patch("src.main.get_holdings", return_value=[]):
                                with patch("src.main.save_signal_payload") as mock_save_payload:
                                    with patch("src.main.save_signal_run") as mock_save_run:
                                        # Should not raise
                                        await run_pipeline()
                                        mock_save_payload.assert_not_called()
                                        # Failure is recorded so the dashboard
                                        # stops showing stale "ok" badges
                                        mock_save_run.assert_called_once()
                                        _, kwargs = mock_save_run.call_args
                                        assert kwargs["source_status"] == {}
                                        assert kwargs["errors"]


@pytest.mark.asyncio
async def test_run_pipeline_persists_signals(tmp_path, monkeypatch):
    """Pipeline should persist aggregated signals and run metadata."""
    monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)

    mock_df = _mock_df()

    async def fake_fetch(filing_info):
        filing_info["report_date"] = "2026-06-30"
        return mock_df

    fake_signals = [MagicMock(), MagicMock()]

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
                    with patch("src.main.SignalAggregator") as MockAgg:
                        mock_agg = MockAgg.return_value
                        mock_result = MagicMock()
                        mock_result.signals = fake_signals
                        mock_result.errors = ["news failed"]
                        mock_result.source_status = {"13F": "ok", "news": "error"}
                        mock_agg.aggregate = AsyncMock(return_value=mock_result)
                        mock_agg.close = AsyncMock()

                        with patch("src.main.FEISHU_WEBHOOK", ""):
                            with patch("src.main.get_holdings", return_value=[]):
                                with patch("src.main.save_signal_payload") as mock_save_payload:
                                    await run_pipeline()

                                    mock_save_payload.assert_called_once_with(
                                        "2026-Q2",
                                        fake_signals,
                                        source_status={"13F": "ok", "news": "error"},
                                        errors=["news failed"],
                                    )


@pytest.mark.asyncio
async def test_run_pipeline_signal_save_failure_does_not_block_report(
    tmp_path, monkeypatch
):
    """Report should still generate even when persisting signals fails."""
    monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)

    mock_df = _mock_df()

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
                    reporter.generate_report = MagicMock(
                        return_value=tmp_path / "2026-Q2.html"
                    )
                    with patch("src.main.SignalAggregator") as MockAgg:
                        mock_agg = MockAgg.return_value
                        mock_result = MagicMock()
                        mock_result.signals = []
                        mock_result.errors = []
                        mock_result.source_status = {"13F": "ok"}
                        mock_agg.aggregate = AsyncMock(return_value=mock_result)
                        mock_agg.close = AsyncMock()

                        with patch("src.main.FEISHU_WEBHOOK", ""):
                            with patch("src.main.get_holdings", return_value=[]):
                                with patch(
                                    "src.main.save_signal_payload",
                                    side_effect=RuntimeError("db locked"),
                                ):
                                    # Should not raise, and the report must still be generated
                                    await run_pipeline()
                                    reporter.generate_report.assert_called_once()
