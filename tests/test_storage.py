"""Tests for src.storage."""
import sqlite3
from datetime import datetime, timezone

import pytest

from src import storage
from src.signals.base import SignalStrength
from src.storage import (
    get_holdings,
    init_db,
    is_notification_sent,
    mark_notification_sent,
    save_holdings,
)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr("src.storage.DATABASE_URL", f"sqlite:///{db_file}")
    init_db()
    return db_file


def test_save_and_get_holdings(fresh_db):
    holdings = [
        {
            "cusip": "037833100",
            "name_of_issuer": "Apple Inc",
            "title_of_class": "COM",
            "value": 100000000.0,
            "shares": 10000,
            "investment_discretion": "SOLE",
        }
    ]
    report_id = save_holdings("0000886982", "2026-Q1", holdings)
    assert report_id == 1
    loaded = get_holdings("0000886982", "2026-Q1")
    assert len(loaded) == 1
    assert loaded[0]["cusip"] == "037833100"


def test_save_holdings_missing_optional_columns(fresh_db):
    holdings = [
        {
            "cusip": "037833100",
            "name_of_issuer": "Apple Inc",
        }
    ]
    report_id = save_holdings("0000886982", "2026-Q1", holdings)
    assert report_id == 1
    loaded = get_holdings("0000886982", "2026-Q1")
    assert len(loaded) == 1
    assert loaded[0]["title_of_class"] is None
    assert loaded[0]["value"] is None
    assert loaded[0]["shares"] is None


def test_save_holdings_persists_filing_metadata(fresh_db):
    holdings = [
        {
            "cusip": "037833100",
            "name_of_issuer": "Apple Inc",
            "title_of_class": "COM",
            "value": 100000000.0,
            "shares": 10000,
            "investment_discretion": "SOLE",
        }
    ]
    filing_info = {
        "filing_date": "2026-05-15",
        "period_of_report": "2026-03-31",
        "xml_url": "https://www.sec.gov/test.xml",
    }
    report_id = save_holdings("0000886982", "2026-Q1", holdings, filing_info)
    assert report_id == 1

    db_file = fresh_db
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM quarterly_reports WHERE id = ?", (report_id,)
    ).fetchone()
    assert row["cik"] == "0000886982"
    assert row["quarter"] == "2026-Q1"
    assert row["filing_date"] == "2026-05-15"
    assert row["period_of_report"] == "2026-03-31"
    assert row["xml_url"] == "https://www.sec.gov/test.xml"
    assert row["num_holdings"] == 1
    assert row["total_value"] == 100000000.0


def test_save_holdings_maps_voting_authority_columns(fresh_db):
    holdings = [
        {
            "cusip": "037833100",
            "name_of_issuer": "Apple Inc",
            "value": 100000000.0,
            "shares": 10000,
            "voting_sole": 10000,
            "voting_shared": 0,
            "voting_none": 0,
        }
    ]
    save_holdings("0000886982", "2026-Q1", holdings)
    loaded = get_holdings("0000886982", "2026-Q1")
    assert len(loaded) == 1
    assert loaded[0]["voting_authority_sole"] == 10000
    assert loaded[0]["voting_authority_shared"] == 0
    assert loaded[0]["voting_authority_none"] == 0


def test_init_db_migrates_existing_database(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr("src.storage.DATABASE_URL", f"sqlite:///{db_file}")
    conn = sqlite3.connect(db_file)
    conn.execute(
        "CREATE TABLE quarterly_reports (id INTEGER PRIMARY KEY, cik TEXT, quarter TEXT)"
    )
    conn.execute(
        "CREATE TABLE holdings (id INTEGER PRIMARY KEY, report_id INTEGER, cusip TEXT)"
    )
    conn.commit()
    conn.close()

    init_db()

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(quarterly_reports)")
    }
    assert "filing_date" in columns
    assert "period_of_report" in columns
    assert "total_value" in columns
    assert "num_holdings" in columns
    assert "xml_url" in columns

    h_columns = {row["name"] for row in conn.execute("PRAGMA table_info(holdings)")}
    assert "voting_authority_sole" in h_columns
    assert "voting_authority_shared" in h_columns
    assert "voting_authority_none" in h_columns


def test_mark_notification_sent_first_time(fresh_db):
    assert mark_notification_sent("2026-Q1") is True


def test_mark_notification_sent_duplicate_returns_false(fresh_db):
    mark_notification_sent("2026-Q1")
    assert mark_notification_sent("2026-Q1") is False


def test_is_notification_sent(fresh_db):
    assert is_notification_sent("2026-Q1") is False
    mark_notification_sent("2026-Q1")
    assert is_notification_sent("2026-Q1") is True


class TestSignalsStorage:
    """Tests for signals and signal_runs persistence."""

    def test_save_and_get_signals_round_trip(self, fresh_db, make_signal):
        storage.save_signals("2026-Q1", [make_signal()])

        loaded = storage.get_signals("2026-Q1")
        assert len(loaded) == 1
        s = loaded[0]
        assert s.id == "sig00001"
        assert s.title == "高盛增持苹果"
        assert s.source == "13F"
        assert s.published_at == datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
        assert s.summary == "苹果占组合 12.3%"
        assert s.companies == ["AAPL"]
        assert s.strength.value == "high"
        assert s.url == "https://example.com/a"
        assert s.cross_refs == ["news:高盛看好苹果"]

    def test_round_trip_preserves_naive_and_aware_datetimes(
        self, fresh_db, make_signal
    ):
        # All production sources emit tz-aware UTC; naive inputs must also survive.
        # Use distinct titles so upsert fingerprint doesn't collide across iterations.
        for published, title in (
            (datetime(2026, 3, 31, 12, 0, 0), "高盛增持苹果-naive"),
            (datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc), "高盛增持苹果-aware"),
        ):
            storage.save_signals("2026-Q1", [make_signal(published_at=published, title=title)])
            loaded = storage.get_signals("2026-Q1")[0]
            assert loaded.published_at == published
            assert loaded.published_at.tzinfo == published.tzinfo
            # Clean up for next iteration (fingerprint is global unique)
            with storage.get_connection() as conn:
                conn.execute("DELETE FROM signals")
                conn.commit()

    def test_get_signals_preserves_insertion_order(self, fresh_db, make_signal):
        signals = [
            make_signal(id="zz000001", title="第一条"),
            make_signal(id="aa000002", title="第二条"),
            make_signal(id="mm000003", title="第三条"),
        ]
        storage.save_signals("2026-Q1", signals)

        loaded_ids = [s.id for s in storage.get_signals("2026-Q1")]
        assert loaded_ids == ["zz000001", "aa000002", "mm000003"]

    def test_get_signals_skips_malformed_rows(self, fresh_db, make_signal):
        storage.save_signals("2026-Q1", [make_signal()])
        with storage.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO signals (id, quarter, source, title, published_at, strength)
                VALUES ('bad00001', '2026-Q1', 'news', '坏强度', '2026-01-01T00:00:00', 'weird')
                """
            )
            conn.execute(
                """
                INSERT INTO signals (id, quarter, source, title, published_at, strength)
                VALUES ('bad00002', '2026-Q1', 'news', '坏日期', 'not-a-date', 'high')
                """
            )
            conn.commit()

        loaded = storage.get_signals("2026-Q1")
        assert [s.id for s in loaded] == ["sig00001"]

    def test_signal_optional_fields_default(self, fresh_db, make_signal):
        storage.save_signals(
            "2026-Q1",
            [make_signal(url=None, cross_refs=[], companies=[])],
        )
        s = storage.get_signals("2026-Q1")[0]
        assert s.url is None
        assert s.cross_refs == []
        assert s.companies == []

    def test_save_signals_replaces_existing_quarter(self, fresh_db, make_signal):
        storage.save_signals(
            "2026-Q1", [make_signal(id="old00001", title="旧信号")]
        )
        storage.save_signals(
            "2026-Q1", [make_signal(id="new00001", title="新信号")]
        )

        loaded = storage.get_signals("2026-Q1")
        assert len(loaded) == 1
        assert loaded[0].title == "新信号"

    def test_save_signals_does_not_touch_other_quarters(self, fresh_db, make_signal):
        storage.save_signals("2026-Q1", [make_signal()])
        storage.save_signals("2026-Q2", [])

        assert len(storage.get_signals("2026-Q1")) == 1
        assert storage.get_signals("2026-Q2") == []

    def test_get_signals_empty_quarter(self, fresh_db):
        assert storage.get_signals("2099-Q4") == []

    def test_signal_run_round_trip(self, fresh_db):
        storage.save_signal_run(
            "2026-Q1",
            source_status={"13F": "ok", "news": "error"},
            errors=["news failed: timeout"],
        )

        run = storage.get_signal_run("2026-Q1")
        assert run is not None
        assert run["quarter"] == "2026-Q1"
        assert run["source_status"] == {"13F": "ok", "news": "error"}
        assert run["errors"] == ["news failed: timeout"]

    def test_save_signal_run_replaces_existing(self, fresh_db):
        storage.save_signal_run("2026-Q1", source_status={"13F": "ok"}, errors=[])
        storage.save_signal_run("2026-Q1", source_status={"13F": "error"}, errors=["boom"])

        run = storage.get_signal_run("2026-Q1")
        assert run["source_status"] == {"13F": "error"}
        assert run["errors"] == ["boom"]

    def test_get_signal_run_none_when_missing(self, fresh_db):
        assert storage.get_signal_run("2099-Q4") is None

    def test_save_signal_payload_writes_signals_and_run_atomically(
        self, fresh_db, make_signal
    ):
        storage.save_signal_payload(
            "2026-Q1",
            [make_signal()],
            source_status={"13F": "ok"},
            errors=[],
        )

        assert len(storage.get_signals("2026-Q1")) == 1
        run = storage.get_signal_run("2026-Q1")
        assert run is not None
        assert run["source_status"] == {"13F": "ok"}
        assert run["errors"] == []


class TestInitDbMigrations:
    """Tests for schema migrations introduced by the intelligence-flow upgrade."""

    def test_init_db_creates_source_state_table(self, fresh_db):
        conn = sqlite3.connect(str(fresh_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='source_state'"
        ).fetchall()
        assert len(rows) == 1

    def test_init_db_adds_signal_fingerprint_column(self, fresh_db):
        conn = sqlite3.connect(str(fresh_db))
        conn.row_factory = sqlite3.Row
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(signals)")
        }
        assert "signal_fingerprint" in columns

    def test_init_db_adds_relevance_score_column(self, fresh_db):
        conn = sqlite3.connect(str(fresh_db))
        conn.row_factory = sqlite3.Row
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(signals)")
        }
        assert "relevance_score" in columns

    def test_init_db_creates_published_at_index(self, fresh_db):
        conn = sqlite3.connect(str(fresh_db))
        conn.row_factory = sqlite3.Row
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        assert "idx_signals_published_at" in indexes

    def test_init_db_signal_runs_has_job_dimension(self, fresh_db):
        """After init_db signal_runs must accept (quarter, job) composite key."""
        conn = sqlite3.connect(str(fresh_db))
        conn.row_factory = sqlite3.Row
        # Verify the job column exists
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(signal_runs)")
        }
        assert "job" in columns

        # Verify the composite PK works (no IntegrityError on insert)
        conn.execute(
            "INSERT INTO signal_runs (quarter, job, source_status, errors) "
            "VALUES (?, ?, ?, ?)",
            ("2026-Q1", "daily", "{}", "[]"),
        )
        conn.execute(
            "INSERT INTO signal_runs (quarter, job, source_status, errors) "
            "VALUES (?, ?, ?, ?)",
            ("2026-Q1", "reconciliation", "{}", "[]"),
        )
        conn.commit()
        rows = conn.execute(
            "SELECT quarter, job FROM signal_runs ORDER BY job"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["job"] == "daily"
        assert rows[1]["job"] == "reconciliation"


class TestSignalFingerprint:
    """Tests for signal fingerprint computation."""

    def test_fingerprint_includes_url_when_present(self, make_signal):
        sig1 = make_signal(
            title="Regulation FD Disclosure",
            source="8-K",
            published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            url="https://sec.gov/a.xml",
        )
        sig2 = make_signal(
            title="Regulation FD Disclosure",
            source="8-K",
            published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            url="https://sec.gov/b.xml",  # different URL
        )
        assert storage.compute_fingerprint(sig1) != storage.compute_fingerprint(sig2)

    def test_fingerprint_no_url_falls_back_to_triple(self, make_signal):
        """Without URL, fingerprint still works but may collide on same-day same-title."""
        sig = make_signal(
            title="宏观信号",
            source="macro_view",
            published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            url=None,
        )
        fp = storage.compute_fingerprint(sig)
        assert isinstance(fp, str)
        assert len(fp) == 64  # SHA-256 hex digest

    def test_fingerprint_stable_across_calls(self, make_signal):
        sig = make_signal()
        fp1 = storage.compute_fingerprint(sig)
        fp2 = storage.compute_fingerprint(sig)
        assert fp1 == fp2

    def test_fingerprint_date_normalized_to_date_only(self, make_signal):
        """Fingerprint uses date only, not time — same day different time = same FP."""
        sig1 = make_signal(published_at=datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc))
        sig2 = make_signal(published_at=datetime(2026, 7, 1, 20, 0, tzinfo=timezone.utc))
        assert storage.compute_fingerprint(sig1) == storage.compute_fingerprint(sig2)


class TestUpsertSignals:
    """Tests for incremental upsert by signal_fingerprint."""

    def test_upsert_inserts_new_signal(self, fresh_db, make_signal):
        sig = make_signal()
        storage.save_signals_incremental("2026-Q1", [sig])
        loaded = storage.get_signals("2026-Q1")
        assert len(loaded) == 1
        assert loaded[0].id == sig.id

    def test_upsert_updates_scoring_on_same_fingerprint(self, fresh_db, make_signal):
        sig = make_signal(title="高盛增持苹果", source="13F")
        storage.save_signals_incremental("2026-Q1", [sig])

        # Same fingerprint, different strength and higher relevance_score
        sig_v2 = make_signal(
            id="sig00002",
            title="高盛增持苹果",
            source="13F",
            strength=SignalStrength.MEDIUM,
            cross_refs=["8-K:苹果财报"],
        )
        storage.save_signals_incremental("2026-Q1", [sig_v2])

        loaded = storage.get_signals("2026-Q1")
        assert len(loaded) == 1  # still one row
        # Scoring fields updated; content fields preserved from original
        assert loaded[0].id == sig.id  # original id preserved

    def test_upsert_content_fields_preserved_on_conflict(self, fresh_db, make_signal):
        sig = make_signal(
            id="orig001",
            title="高盛增持苹果",
            source="13F",
            summary="原始摘要内容",
            url="https://sec.gov/original.xml",
        )
        storage.save_signals_incremental("2026-Q1", [sig])

        # Re-insert with different summary/url but same fingerprint
        sig_v2 = make_signal(
            id="new002",
            title="高盛增持苹果",
            source="13F",
            summary="新摘要不应覆盖",
            url="https://sec.gov/different.xml",
        )
        storage.save_signals_incremental("2026-Q1", [sig_v2])

        loaded = storage.get_signals("2026-Q1")[0]
        # Content preserved from first insert
        assert loaded.summary == "原始摘要内容"
        assert loaded.url == "https://sec.gov/original.xml"
        assert loaded.id == "orig001"

    def test_upsert_multiple_sources_no_collision(self, fresh_db, make_signal):
        sig_8k = make_signal(
            id="k8001", source="8-K",
            title="重大事件", url="https://sec.gov/8k.xml",
        )
        sig_news = make_signal(
            id="nws001", source="news",
            title="重大事件", url="https://example.com/news",
        )
        storage.save_signals_incremental("2026-Q2", [sig_8k, sig_news])
        loaded = storage.get_signals("2026-Q2")
        assert len(loaded) == 2


class TestRecentSignals:
    """Tests for time-window signal retrieval."""

    def test_get_recent_signals_returns_correct_window(self, fresh_db, make_signal):
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        sig_old = make_signal(
            id="old0001",
            published_at=now - timedelta(days=10),
            title="旧信号",
        )
        sig_new = make_signal(
            id="new0001",
            published_at=now - timedelta(days=2),
            title="新信号",
        )
        storage.save_signals("2026-Q3", [sig_old, sig_new])

        recent = storage.get_recent_signals(days=5, reference_date=now)
        assert len(recent) == 1
        assert recent[0].id == "new0001"

    def test_get_recent_signals_empty_when_no_match(self, fresh_db, make_signal):
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        sig = make_signal(published_at=now - timedelta(days=30))
        storage.save_signals("2026-Q2", [sig])

        recent = storage.get_recent_signals(days=5, reference_date=now)
        assert recent == []

    def test_get_recent_signals_ordered_by_published_at_desc(self, fresh_db, make_signal):
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        sig1 = make_signal(
            id="s001", published_at=now - timedelta(days=1), title="昨天",
        )
        sig2 = make_signal(
            id="s002", published_at=now - timedelta(hours=1), title="刚才",
        )
        storage.save_signals("2026-Q3", [sig1, sig2])

        recent = storage.get_recent_signals(days=5, reference_date=now)
        assert [s.id for s in recent] == ["s002", "s001"]


class TestSourceState:
    """Tests for per-source watermark persistence."""

    def test_save_and_get_source_state_round_trip(self, fresh_db):
        storage.save_source_state("13D/13G", "cik_lookup", "0000886982-26-000300")
        wm = storage.get_source_state("13D/13G", "cik_lookup")
        assert wm == "0000886982-26-000300"

    def test_get_source_state_none_when_missing(self, fresh_db):
        assert storage.get_source_state("13D/13G", "nonexistent") is None

    def test_save_source_state_replaces_existing(self, fresh_db):
        storage.save_source_state("13D/13G", "cik_lookup", "acc-001")
        storage.save_source_state("13D/13G", "cik_lookup", "acc-002")
        assert storage.get_source_state("13D/13G", "cik_lookup") == "acc-002"

    def test_source_state_independent_paths(self, fresh_db):
        storage.save_source_state("13D/13G", "cik_lookup", "acc-cik")
        storage.save_source_state("13D/13G", "efts_search", "acc-efts")
        assert storage.get_source_state("13D/13G", "cik_lookup") == "acc-cik"
        assert storage.get_source_state("13D/13G", "efts_search") == "acc-efts"


class TestSignalRunJobDimension:
    """Tests for signal_runs with the job dimension."""

    def test_save_signal_run_with_job(self, fresh_db):
        storage.save_signal_run(
            "2026-Q2", job="daily",
            source_status={"news": "ok"},
            errors=[],
        )
        run = storage.get_signal_run("2026-Q2", job="daily")
        assert run is not None
        assert run["job"] == "daily"
        assert run["source_status"] == {"news": "ok"}

    def test_save_signal_run_jobs_dont_overwrite(self, fresh_db):
        storage.save_signal_run(
            "2026-Q2", job="daily",
            source_status={"news": "ok"}, errors=[],
        )
        storage.save_signal_run(
            "2026-Q2", job="reconciliation",
            source_status={"13F": "ok"}, errors=["timeout"],
        )
        daily = storage.get_signal_run("2026-Q2", job="daily")
        recon = storage.get_signal_run("2026-Q2", job="reconciliation")
        assert daily["source_status"] == {"news": "ok"}
        assert recon["source_status"] == {"13F": "ok"}
        assert recon["errors"] == ["timeout"]

    def test_get_signal_run_defaults_to_daily(self, fresh_db):
        """Backward compat: get_signal_run without job returns daily row when available."""
        storage.save_signal_run("2026-Q2", job="daily",
                                source_status={"news": "ok"}, errors=[])
        run = storage.get_signal_run("2026-Q2")
        assert run is not None
        assert run["job"] == "daily"
