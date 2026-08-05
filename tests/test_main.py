import json

import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.data_fetcher import SEC13FFetcher
from src.storage import default_source_entries
from src.main import main, run_pipeline, run_pipeline_stream


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
        """Patch all source classes (hermetic — no live HTTP); yields mocks."""
        mocks = {}
        fake_institutions = [
            {"id": "gs", "name": "Goldman Sachs", "display_name": "高盛",
             "cik": "0000886982", "enabled": 1},
            {"id": "jpm", "name": "JPMorgan", "display_name": "摩根大通",
             "cik": "0000019617", "enabled": 1},
        ]
        with patch("src.main.NewsSource") as mock_news, \
             patch("src.main.Sec8kSource") as mock_8k, \
             patch("src.main.ResearchViewSource") as mock_rv, \
             patch("src.main.JPMResearchSource") as mock_jpmr, \
             patch("src.main.QFIISource") as mock_qfii, \
             patch("src.main.NorthboundSource") as mock_nb, \
             patch("src.main.get_institutions", return_value=fake_institutions), \
             patch("src.main.get_sources_config",
                   return_value=default_source_entries()), \
             patch("src.main.ThirteenDGSource") as mock_dg:
            for cls in (mock_news, mock_rv, mock_dg, mock_jpmr, mock_qfii, mock_nb):
                cls.return_value.fetch_since = AsyncMock(return_value=([], None))
                cls.return_value.close = AsyncMock()
            mock_8k.return_value.fetch = AsyncMock(return_value=[])
            mock_8k.return_value.close = AsyncMock()
            # 8-K source doesn't have fetch_since — delete auto-created MagicMock attr
            del mock_8k.return_value.fetch_since
            mocks.update(news=mock_news, sec8k=mock_8k, research=mock_rv, dg=mock_dg, jpm_research=mock_jpmr)
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
        # RSS_FEEDS empty → no news/jpm_research sources (all feed-based);
        # 8-K + 13D/13G run per institution, plus research_view + A-share sources
        assert len(done_events) == 7
        assert {e["source"] for e in done_events} == {
            "8-K · 高盛", "8-K · 摩根大通",
            "13D/13G · 高盛", "13D/13G · 摩根大通",
            "research_view", "northbound", "qfii",
        }
        assert events[-1]["event"] == "complete"
        assert not any(e["event"] == "triage_note" for e in events)

    @pytest.mark.asyncio
    async def test_build_daily_sources_includes_custom(self, monkeypatch):
        """Enabled custom RSS entries become per-source NewsSource instances."""
        monkeypatch.setattr("src.main.RSS_FEEDS", [])
        config = json.dumps([
            {"name": "news", "enabled": True, "builtin": True},
            {"name": "caixin", "label": "财新网", "type": "rss",
             "url": "https://custom.test/feed", "filter_policy": "all",
             "enabled": True, "builtin": False},
        ])
        with patch("src.main.get_sources_config", return_value=json.loads(config)), \
             patch("src.main.get_institutions", return_value=[]), \
             patch("src.main.NewsSource") as MockNews, \
             patch("src.main.ThirteenDGSource"), \
             patch("src.main.Sec8kSource"), \
             patch("src.main.ResearchViewSource"):
            from src.main import _build_daily_sources

            _build_daily_sources()

        custom_call = MockNews.call_args_list[0]
        assert custom_call.kwargs["rss_urls"] == ["https://custom.test/feed"]
        assert custom_call.kwargs["source_name"] == "caixin"
        assert custom_call.kwargs["filter_policy"] == "all"

    @pytest.mark.asyncio
    async def test_build_daily_sources_skips_disabled_custom(self, monkeypatch):
        monkeypatch.setattr("src.main.RSS_FEEDS", [])
        config = json.dumps([
            {"name": "news", "enabled": True, "builtin": True},
            {"name": "caixin", "label": "财新网", "type": "rss",
             "url": "https://custom.test/feed", "enabled": False, "builtin": False},
        ])
        with patch("src.main.get_sources_config", return_value=json.loads(config)), \
             patch("src.main.get_institutions", return_value=[]), \
             patch("src.main.NewsSource"), \
             patch("src.main.ThirteenDGSource"), \
             patch("src.main.Sec8kSource"), \
             patch("src.main.ResearchViewSource"):
            from src.main import _build_daily_sources

            names = [n for n, _ in _build_daily_sources()]

        assert "caixin" not in names

    @pytest.mark.asyncio
    async def test_build_daily_sources_includes_webpage(self, monkeypatch):
        """webpage-type custom entries become WebpageSource instances."""
        monkeypatch.setattr("src.main.RSS_FEEDS", [])
        config = json.dumps([
            {"name": "news", "enabled": True, "builtin": True},
            {"name": "gs_insights", "label": "高盛观点页", "type": "webpage",
             "url": "https://example.com/insights", "instruction": "提取高盛观点",
             "filter_policy": "gs_only", "enabled": True, "builtin": False},
        ])
        with patch("src.main.get_sources_config", return_value=json.loads(config)), \
             patch("src.main.get_institutions", return_value=[]), \
             patch("src.main.WebpageSource") as MockWeb, \
             patch("src.main.NewsSource"), \
             patch("src.main.ThirteenDGSource"), \
             patch("src.main.Sec8kSource"), \
             patch("src.main.ResearchViewSource"), \
             patch("src.main.get_default_llm_model", return_value=None):
            from src.main import _build_daily_sources

            _build_daily_sources()

        web_call = MockWeb.call_args_list[0]
        assert web_call.kwargs["url"] == "https://example.com/insights"
        assert web_call.kwargs["instruction"] == "提取高盛观点"
        assert web_call.kwargs["source_name"] == "gs_insights"
        assert web_call.kwargs["filter_policy"] == "gs_only"

    @pytest.mark.asyncio
    async def test_build_daily_sources_includes_topic(self, monkeypatch):
        """topic-type custom entries become TopicSource instances (no url needed)."""
        monkeypatch.setattr("src.main.RSS_FEEDS", [])
        config = json.dumps([
            {"name": "news", "enabled": True, "builtin": True},
            {"name": "gs_china_view", "label": "高盛中国观点", "type": "topic",
             "url": "", "instruction": "高盛对中国股市的最新观点",
             "filter_policy": "gs_only", "enabled": True, "builtin": False},
        ])
        with patch("src.main.get_sources_config", return_value=json.loads(config)), \
             patch("src.main.get_institutions", return_value=[]), \
             patch("src.main.TopicSource") as MockTopic, \
             patch("src.main.NewsSource"), \
             patch("src.main.ThirteenDGSource"), \
             patch("src.main.Sec8kSource"), \
             patch("src.main.ResearchViewSource"), \
             patch("src.main.get_default_llm_model", return_value=None):
            from src.main import _build_daily_sources

            _build_daily_sources()

        topic_call = MockTopic.call_args_list[0]
        assert topic_call.kwargs["topic"] == "高盛对中国股市的最新观点"
        assert topic_call.kwargs["source_name"] == "gs_china_view"
        assert topic_call.kwargs["filter_policy"] == "gs_only"

    @pytest.mark.asyncio
    async def test_stream_emits_triage_note_from_fetch_note(self, tmp_path, monkeypatch, _mock_sources, _mock_storage):
        """A source's fetch_note surfaces as a yellow triage_note SSE event."""
        monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.main.RSS_FEEDS", [])

        class _NoteSource:
            source_name = "gs_page"
            fetch_note = ""

            async def fetch_since(self, watermark=None):
                self.fetch_note = "网页提取 AI 预算已用完，明日自动恢复"
                return [], None

            async def close(self):
                pass

        monkeypatch.setattr(
            "src.main._build_daily_sources", lambda *_a, **_k: [("gs_page", _NoteSource())]
        )

        from src.main import run_daily_intel_stream

        events = [json.loads(e) async for e in run_daily_intel_stream()]
        notes = [e for e in events if e.get("event") == "triage_note"]
        assert any(n["source"] == "gs_page" and "预算" in n["note"] for n in notes)

    @pytest.mark.asyncio
    async def test_stream_runs_triage_and_emits_note(self, tmp_path, monkeypatch, _mock_sources, _mock_storage, make_signal):
        """News items go through AiTriage; fallback emits a triage_note event."""
        from src.signals.ai_triage import TriageResult

        monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.main.RSS_FEEDS", ["https://x.test/rss"])
        sig1 = make_signal(id="n1", source="news", title="高盛研报A")
        sig2 = make_signal(id="n2", source="news", title="无关新闻B")
        _mock_sources["news"].return_value.fetch_since = AsyncMock(
            return_value=([sig1, sig2], None)
        )
        monkeypatch.setattr(
            "src.main._build_daily_sources",
            lambda *_a, **_k: [("news", _mock_sources["news"].return_value)],
        )

        with patch("src.main.AiTriage") as MockTriage, \
             patch("src.main.get_default_llm_model", return_value=None), \
             patch("src.main.get_recent_signals", return_value=[]):
            MockTriage.return_value.triage = AsyncMock(
                return_value=TriageResult(
                    kept_indices=[0], fallback_used=True, note="AI 预算已用完"
                )
            )
            from src.main import run_daily_intel_stream

            events = []
            async for ev in run_daily_intel_stream():
                events.append(json.loads(ev))

        note_events = [e for e in events if e["event"] == "triage_note"]
        assert len(note_events) == 1
        assert note_events[0]["source"] == "news"
        assert "预算" in note_events[0]["note"]
        complete = events[-1]
        assert complete["event"] == "complete"
        assert complete["new_signals"] == 1  # 仅保留 triage 选中的第 1 条

    @pytest.mark.asyncio
    async def test_build_daily_sources_respects_enabled_flags(self, monkeypatch):
        """Disabled sources in sources_config must be skipped."""
        monkeypatch.setattr("src.main.RSS_FEEDS", ["https://example.test/rss"])
        config = [
            {"name": "8-K", "enabled": False},
            {"name": "13D/13G", "enabled": True},
            {"name": "research_view", "enabled": False},
            {"name": "news", "enabled": True},
        ]
        fake_institutions = [
            {"id": "gs", "name": "Goldman Sachs", "display_name": "高盛",
             "cik": "0000886982", "enabled": 1},
            {"id": "jpm", "name": "JPMorgan", "display_name": "摩根大通",
             "cik": "0000019617", "enabled": 1},
        ]
        with patch("src.main.get_sources_config", return_value=config), \
             patch("src.main.get_institutions", return_value=fake_institutions), \
             patch("src.main.NewsSource"), \
             patch("src.main.ThirteenDGSource"), \
             patch("src.main.Sec8kSource"), \
             patch("src.main.ResearchViewSource"):
            from src.main import _build_daily_sources

            sources = _build_daily_sources()

        assert [n for n, _ in sources] == ["13D/13G · 高盛", "13D/13G · 摩根大通", "news"]

    @pytest.mark.asyncio
    async def test_build_daily_sources_sec_sources_per_institution(self, monkeypatch):
        """8-K and 13D/13G must be built once per enabled institution,
        parameterized with that institution's CIK/tag/display name."""
        monkeypatch.setattr("src.main.RSS_FEEDS", [])
        config = [
            {"name": "8-K", "enabled": True, "builtin": True},
            {"name": "13D/13G", "enabled": True, "builtin": True},
        ]
        fake_institutions = [
            {"id": "gs", "name": "Goldman Sachs", "display_name": "高盛",
             "cik": "0000886982", "enabled": 1},
            {"id": "jpm", "name": "JPMorgan", "display_name": "摩根大通",
             "cik": "0000019617", "enabled": 1},
            {"id": "ms", "name": "Morgan Stanley", "display_name": "摩根士丹利",
             "cik": "0000895421", "enabled": 0},  # disabled -> skipped
        ]
        with patch("src.main.get_sources_config", return_value=config), \
             patch("src.main.get_institutions", return_value=fake_institutions), \
             patch("src.main.Sec8kSource") as Mock8k, \
             patch("src.main.ThirteenDGSource") as MockDG:
            from src.main import _build_daily_sources

            sources = _build_daily_sources()

        names = [n for n, _ in sources]
        assert names == [
            "8-K · 高盛", "8-K · 摩根大通",
            "13D/13G · 高盛", "13D/13G · 摩根大通",
        ]
        by_inst = {c.kwargs["institution_id"]: c.kwargs for c in Mock8k.call_args_list}
        assert by_inst["jpm"]["cik"] == "0000019617"
        assert by_inst["jpm"]["company_tag"] == "JPM"
        assert by_inst["jpm"]["display_name"] == "摩根大通"
        assert by_inst["gs"]["cik"] == "0000886982"
        dg_insts = {c.kwargs["institution_id"] for c in MockDG.call_args_list}
        assert dg_insts == {"gs", "jpm"}


@pytest.mark.asyncio
async def test_stream_schedules_daily_report(monkeypatch):
    """complete 事件前，流水线应调度当日日报生成（fire-and-forget）。"""
    import json as _json
    from datetime import datetime, timezone
    import src.main as main_mod

    calls = []

    async def _fake_ensure(date):
        calls.append(date)
        return None

    monkeypatch.setattr(main_mod, "ensure_daily_report", _fake_ensure)
    monkeypatch.setattr(main_mod, "_build_daily_sources", lambda *_a, **_k: [])
    monkeypatch.setattr(main_mod, "get_recent_signals", lambda days=30: [])
    monkeypatch.setattr(main_mod, "save_signals_incremental", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "save_signal_run", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "cleanup_expired_signals", lambda *a, **kw: None)

    events = []
    async for event_json in main_mod.run_daily_intel_stream():
        events.append(_json.loads(event_json))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert calls == [today]
    assert events[-1]["event"] == "complete"


@pytest.mark.asyncio
async def test_stream_refreshes_daily_report_when_new_signals(monkeypatch, make_signal):
    """本次抓到新信号时，流水线应强制重生成当日日报（refresh 而非 ensure）。"""
    import json as _json
    from datetime import datetime, timezone
    import src.main as main_mod

    refresh_calls, ensure_calls = [], []

    async def _fake_refresh(date):
        refresh_calls.append(date)
        return None

    async def _fake_ensure(date):
        ensure_calls.append(date)
        return None

    class _Src:
        async def fetch(self, _query):
            return [make_signal(source="8-K")]

        async def close(self):
            return None

    monkeypatch.setattr(main_mod, "refresh_daily_report", _fake_refresh)
    monkeypatch.setattr(main_mod, "ensure_daily_report", _fake_ensure)
    monkeypatch.setattr(main_mod, "_build_daily_sources", lambda *_a, **_k: [("8-K", _Src())])
    monkeypatch.setattr(main_mod, "get_recent_signals", lambda days=30: [])
    monkeypatch.setattr(main_mod, "save_signals_incremental", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "save_signal_run", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "cleanup_expired_signals", lambda *a, **kw: None)

    events = []
    async for event_json in main_mod.run_daily_intel_stream():
        events.append(_json.loads(event_json))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert refresh_calls == [today]
    assert ensure_calls == []
    assert events[-1]["event"] == "complete"
    assert events[-1]["new_signals"] == 1


@pytest.mark.asyncio
async def test_stream_auto_analyzes_new_signals_before_complete(monkeypatch, make_signal):
    """complete 事件发出前，流水线应先完成新信号的自动 AI 解读。"""
    import json as _json
    import src.main as main_mod

    auto_calls = []
    sig = make_signal(source="8-K")

    async def _fake_auto(signals):
        auto_calls.append([s.id for s in signals])

    class _Src:
        async def fetch(self, _query):
            return [sig]

        async def close(self):
            return None

    async def _noop(date):
        return None

    monkeypatch.setattr(main_mod, "auto_analyze_high_signals", _fake_auto)
    monkeypatch.setattr(main_mod, "refresh_daily_report", _noop)
    monkeypatch.setattr(main_mod, "ensure_daily_report", _noop)
    monkeypatch.setattr(main_mod, "_build_daily_sources", lambda *_a, **_k: [("8-K", _Src())])
    monkeypatch.setattr(main_mod, "get_recent_signals", lambda days=30: [])
    monkeypatch.setattr(main_mod, "save_signals_incremental", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "save_signal_run", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "cleanup_expired_signals", lambda *a, **kw: None)

    events = []
    async for event_json in main_mod.run_daily_intel_stream():
        events.append(_json.loads(event_json))

    assert auto_calls == [[sig.id]]
    assert events[-1]["event"] == "complete"


@pytest.mark.asyncio
async def test_stream_auto_analyze_failure_does_not_break_pipeline(monkeypatch, make_signal):
    """自动解读失败不阻塞流水线，complete 事件照常发出。"""
    import json as _json
    import src.main as main_mod

    async def _boom(signals):
        raise RuntimeError("LLM down")

    class _Src:
        async def fetch(self, _query):
            return [make_signal(source="8-K")]

        async def close(self):
            return None

    async def _noop(date):
        return None

    monkeypatch.setattr(main_mod, "auto_analyze_high_signals", _boom)
    monkeypatch.setattr(main_mod, "refresh_daily_report", _noop)
    monkeypatch.setattr(main_mod, "ensure_daily_report", _noop)
    monkeypatch.setattr(main_mod, "_build_daily_sources", lambda *_a, **_k: [("8-K", _Src())])
    monkeypatch.setattr(main_mod, "get_recent_signals", lambda days=30: [])
    monkeypatch.setattr(main_mod, "save_signals_incremental", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "save_signal_run", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "cleanup_expired_signals", lambda *a, **kw: None)

    events = []
    async for event_json in main_mod.run_daily_intel_stream():
        events.append(_json.loads(event_json))

    assert events[-1]["event"] == "complete"
    assert events[-1]["new_signals"] == 1


@pytest.mark.asyncio
async def test_run_daily_intel_awaits_report_task(monkeypatch):
    """调度器/CLI 路径必须等日报生成完（一次性进程退出前落地）。"""
    import asyncio
    from datetime import datetime, timezone
    import src.main as main_mod

    generated = []
    _task = None

    async def _gen():
        await asyncio.sleep(0)
        generated.append("done")

    async def _fake_ensure(date):
        nonlocal _task
        if _task is None:
            _task = asyncio.create_task(_gen())
        return _task

    monkeypatch.setattr(main_mod, "ensure_daily_report", _fake_ensure)
    monkeypatch.setattr(main_mod, "_build_daily_sources", lambda *_a, **_k: [])
    monkeypatch.setattr(main_mod, "get_recent_signals", lambda days=30: [])
    monkeypatch.setattr(main_mod, "save_signals_incremental", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "save_signal_run", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "cleanup_expired_signals", lambda *a, **kw: None)

    summary = await main_mod.run_daily_intel()
    assert generated == ["done"]
    assert summary["new_signals"] == 0


@pytest.mark.asyncio
async def test_run_pipeline_stream_emits_progress_events(tmp_path, monkeypatch):
    """The streaming pipeline yields start/step/complete events so the
    dashboard can render live per-step progress (13F-only, no signal sources)."""
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
                analyzer.analyze_holdings = AsyncMock(return_value=AsyncMock())
                with patch("src.main.ReportGenerator") as MockReporter:
                    reporter = MockReporter.return_value
                    reporter.generate_report = lambda *args, **kwargs: tmp_path / "2026-Q2.html"
                    events = [
                        json.loads(e)
                        async for e in run_pipeline_stream()
                    ]

    kinds = [e["event"] for e in events]
    assert kinds[0] == "start"
    assert kinds[-1] == "complete"
    assert events[-1]["quarter"] == "2026-Q2"

    steps = {(e["step"], e["status"]) for e in events if e["event"] == "step"}
    assert ("holdings", "running") in steps
    assert ("holdings", "done") in steps
    assert ("analysis", "done") in steps
    assert ("report", "done") in steps


@pytest.mark.asyncio
async def test_quarterly_pipeline_skips_signal_aggregation(tmp_path, monkeypatch):
    """Quarterly reconciliation is 13F-only: no signal sources, no signal panel."""
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

    events = []
    with patch("src.main.SEC13FFetcher") as MockFetcher:
        MockFetcher.report_date_to_quarter = SEC13FFetcher.report_date_to_quarter
        instance = MockFetcher.return_value.__aenter__.return_value
        instance.fetch_latest_holdings = fake_fetch
        with patch("src.main.save_holdings"):
            with patch("src.main.get_holdings", return_value=[]):
                with patch("src.main.GSAnalyzer") as MockAnalyzer:
                    analyzer = MockAnalyzer.return_value
                    analyzer.analyze_holdings = AsyncMock(return_value=MagicMock())
                    with patch("src.main.ReportGenerator") as MockReporter:
                        reporter = MockReporter.return_value
                        reporter.generate_report = MagicMock(
                            return_value=tmp_path / "2026-Q2.html"
                        )
                        async for event_json in run_pipeline_stream("gs"):
                            events.append(json.loads(event_json))
                        _, kwargs = reporter.generate_report.call_args
                        assert "signals" not in kwargs
                        assert "signal_errors" not in kwargs
                        assert "source_status" not in kwargs

    event_names = [e["event"] for e in events]
    assert "source_done" not in event_names
    start = events[0]
    assert start["event"] == "start"
    assert start["sources"] == []
    complete = events[-1]
    assert complete["event"] == "complete"
    assert "signal_count" not in complete
