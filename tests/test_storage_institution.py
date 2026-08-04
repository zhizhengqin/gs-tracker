"""Test storage layer institution_id support."""
from datetime import datetime, timezone

import pytest
from src.signals.base import Signal, SignalStrength
from src.storage import init_db, save_signals_incremental, get_recent_signals, get_signals_by_date, get_institutions


class TestStorageInstitution:
    @pytest.fixture(autouse=True)
    def fresh_db(self, tmp_path, monkeypatch):
        # Redirect storage to a throwaway DB so test rows never land in
        # the production database.
        db_file = tmp_path / "test.db"
        monkeypatch.setattr("src.storage.DATABASE_URL", f"sqlite:///{db_file}")
        init_db()

    def test_institutions_table_created(self):
        insts = get_institutions()
        ids = {i["id"] for i in insts}
        assert "gs" in ids
        assert "jpm" in ids

    def test_signal_saved_with_institution_id(self):
        now = datetime.now(timezone.utc)
        unique_title = f"JPM-INST-TEST-{now.timestamp()}"
        s = Signal(title=unique_title, source="news", published_at=now,
                   summary="", companies=[], strength=SignalStrength.MEDIUM,
                   institution_id="jpm")
        save_signals_incremental("2026-Q3", [s])
        recent = get_recent_signals(days=7, institution_id="jpm")
        titles = {x.title for x in recent}
        assert unique_title in titles

    def test_get_recent_signals_filter_by_institution(self):
        now = datetime.now(timezone.utc)
        ts = now.timestamp()
        save_signals_incremental("2026-Q3", [
            Signal(title=f"GS-FILTER-{ts}", source="news", published_at=now,
                   summary="", companies=[], strength=SignalStrength.MEDIUM, institution_id="gs"),
            Signal(title=f"JPM-FILTER-{ts}", source="news", published_at=now,
                   summary="", companies=[], strength=SignalStrength.MEDIUM, institution_id="jpm"),
        ])
        gs = get_recent_signals(days=7, institution_id="gs")
        jpm = get_recent_signals(days=7, institution_id="jpm")
        gs_titles = {x.title for x in gs}
        jpm_titles = {x.title for x in jpm}
        assert f"GS-FILTER-{ts}" in gs_titles
        assert f"JPM-FILTER-{ts}" in jpm_titles

    def test_get_signals_by_date_filter_by_institution(self):
        from datetime import timedelta
        beijing = timezone(timedelta(hours=8))
        today = datetime.now(beijing)
        today_str = today.strftime("%Y-%m-%d")
        ts = today.timestamp()
        save_signals_incremental("2026-Q3", [
            Signal(title=f"GS-DATE-{ts}", source="news", published_at=today,
                   summary="", companies=[], strength=SignalStrength.MEDIUM, institution_id="gs"),
            Signal(title=f"JPM-DATE-{ts}", source="news", published_at=today,
                   summary="", companies=[], strength=SignalStrength.MEDIUM, institution_id="jpm"),
        ])
        gs = get_signals_by_date(today_str, institution_id="gs")
        jpm = get_signals_by_date(today_str, institution_id="jpm")
        gs_titles = {x.title for x in gs}
        jpm_titles = {x.title for x in jpm}
        assert f"GS-DATE-{ts}" in gs_titles
        assert f"JPM-DATE-{ts}" in jpm_titles
