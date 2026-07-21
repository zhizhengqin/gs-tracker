"""Tests for src.config."""
import importlib

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


def test_rss_feeds_default():
    assert isinstance(config.RSS_FEEDS, list)


def test_signal_lookback_days_default():
    assert config.SIGNAL_LOOKBACK_DAYS == 90


def test_gs_llm_model_explicit_env_wins(monkeypatch):
    """GS_LLM_MODEL takes precedence over Claude Code's ANTHROPIC_MODEL."""
    monkeypatch.setenv("GS_LLM_MODEL", "explicit-model")
    monkeypatch.setenv("ANTHROPIC_MODEL", "cc-model")
    try:
        importlib.reload(config)
        assert config.GS_LLM_MODEL == "explicit-model"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_gs_llm_model_fallback_chain(monkeypatch):
    """Fall back to ANTHROPIC_MODEL, then to the Kimi default."""
    monkeypatch.delenv("GS_LLM_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_MODEL", "cc-model")
    try:
        importlib.reload(config)
        assert config.GS_LLM_MODEL == "cc-model"
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        importlib.reload(config)
        assert config.GS_LLM_MODEL == "kimi-for-coding"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
