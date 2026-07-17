"""Tests for src.storage."""
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
