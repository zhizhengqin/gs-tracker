"""Tests for src.config."""
from src import config


def test_db_path_default():
    assert config.DATABASE_URL.endswith("gs_tracker.db")


def test_goldman_cik():
    assert config.GOLDMAN_CIK == "0000886982"


def test_public_base_url_default():
    assert config.PUBLIC_BASE_URL == ""


def test_notifier_max_attempts_default():
    assert config.NOTIFIER_MAX_ATTEMPTS == 3


def test_notifier_backoff_base_default():
    assert config.NOTIFIER_BACKOFF_BASE == 1.0
