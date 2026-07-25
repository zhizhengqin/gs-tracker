"""Shared LLM client configuration resolution (DB default first, env fallback)."""
from typing import Optional


def resolve_llm_config(db_model: Optional[dict]) -> dict:
    """Resolve LLM settings. db_model: row from get_default_llm_model() or None.
    Returns dict with keys api_key, auth_token, base_url, model (first three
    may be None when unset)."""
    if db_model:
        return {
            "api_key": None,
            "auth_token": db_model["auth_token"] or None,
            "base_url": db_model["base_url"] or None,
            "model": db_model["model_name"],
        }
    from src.config import (
        ANTHROPIC_API_KEY,
        ANTHROPIC_AUTH_TOKEN,
        ANTHROPIC_BASE_URL,
        GS_LLM_MODEL,
    )
    return {
        "api_key": ANTHROPIC_API_KEY or None,
        "auth_token": ANTHROPIC_AUTH_TOKEN or None,
        "base_url": ANTHROPIC_BASE_URL or None,
        "model": GS_LLM_MODEL,
    }
