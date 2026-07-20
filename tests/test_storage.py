"""Tests for src.storage."""
import sqlite3
from datetime import datetime, timezone

import pytest

from src import storage
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
        for published in (
            datetime(2026, 3, 31, 12, 0, 0),
            datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc),
        ):
            storage.save_signals("2026-Q1", [make_signal(published_at=published)])
            loaded = storage.get_signals("2026-Q1")[0]
            assert loaded.published_at == published
            assert loaded.published_at.tzinfo == published.tzinfo

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
