"""Tests for src.llm_config."""
from src.llm_config import resolve_llm_config


def test_db_model_wins(monkeypatch):
    db_model = {"auth_token": "db-token", "base_url": "https://db.test", "model_name": "db-model"}
    cfg = resolve_llm_config(db_model)
    assert cfg == {
        "api_key": None,
        "auth_token": "db-token",
        "base_url": "https://db.test",
        "model": "db-model",
    }


def test_env_fallback_includes_api_key(monkeypatch):
    monkeypatch.setattr("src.config.ANTHROPIC_API_KEY", "ak-123")
    monkeypatch.setattr("src.config.ANTHROPIC_AUTH_TOKEN", "")
    monkeypatch.setattr("src.config.ANTHROPIC_BASE_URL", "")
    monkeypatch.setattr("src.config.GS_LLM_MODEL", "env-model")
    cfg = resolve_llm_config(None)
    assert cfg["api_key"] == "ak-123"
    assert cfg["auth_token"] is None
    assert cfg["base_url"] is None
    assert cfg["model"] == "env-model"
