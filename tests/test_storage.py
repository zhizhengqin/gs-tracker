"""Tests for src.storage."""
import sqlite3

import pytest

from src.storage import init_db, save_holdings, get_holdings


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
