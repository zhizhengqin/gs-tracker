"""Tests for src.config."""
from src import config


def test_db_path_default():
    assert config.DATABASE_URL.endswith("gs_tracker.db")


def test_goldman_cik():
    assert config.GOLDMAN_CIK == "0000886982"
