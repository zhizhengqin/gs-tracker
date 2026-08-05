"""Tests for sources_config merge logic in src.storage.

Regression: installs that saved sources_config before new built-in sources
existed (news_jpm, jpm_research, qfii, northbound) never saw them — the
stored list was returned verbatim, so the new sources stayed invisible and
disabled forever.
"""
import json

import pytest

from src.storage import (
    BUILTIN_SOURCE_NAMES,
    default_source_entries,
    get_sources_config,
    init_db,
    set_setting,
)


class TestSourcesConfigMerge:
    @pytest.fixture(autouse=True)
    def fresh_db(self, tmp_path, monkeypatch):
        db_file = tmp_path / "test.db"
        monkeypatch.setattr("src.storage.DATABASE_URL", f"sqlite:///{db_file}")
        init_db()

    def test_defaults_when_nothing_stored(self):
        cfg = get_sources_config()
        names = {c["name"] for c in cfg}
        assert names >= set(BUILTIN_SOURCE_NAMES)
        assert all(c.get("enabled", True) for c in cfg)

    def test_stale_config_gains_new_builtins_enabled(self):
        stale = [
            {"name": "13F", "label": "13F 持仓", "description": "高盛季度 13F 持仓报告",
             "enabled": True, "builtin": True},
            {"name": "news", "label": "新闻", "description": "RSS 新闻关键词匹配",
             "enabled": True, "builtin": True},
        ]
        set_setting("sources_config", json.dumps(stale, ensure_ascii=False))
        cfg = get_sources_config()
        names = {c["name"] for c in cfg}
        for n in ("qfii", "northbound", "news_jpm", "jpm_research",
                  "8-K", "13D/13G", "research_view", "macro_view"):
            assert n in names, f"{n} missing after merge"
            entry = next(c for c in cfg if c["name"] == n)
            assert entry["enabled"] is True

    def test_user_disabled_choice_preserved(self):
        stale = [{"name": "13F", "enabled": False, "builtin": True}]
        set_setting("sources_config", json.dumps(stale))
        cfg = get_sources_config()
        assert next(c for c in cfg if c["name"] == "13F")["enabled"] is False

    def test_builtin_labels_and_descriptions_synced(self):
        """Builtin label/description follow the code defaults (only enabled is user-owned)."""
        stale = [{"name": "13F", "label": "13F 持仓", "description": "高盛季度 13F 持仓报告",
                  "enabled": True, "builtin": True}]
        set_setting("sources_config", json.dumps(stale, ensure_ascii=False))
        cfg = get_sources_config()
        entry = next(c for c in cfg if c["name"] == "13F")
        default = next(d for d in default_source_entries() if d["name"] == "13F")
        assert entry["description"] == default["description"]
        assert entry["label"] == default["label"]

    def test_custom_entries_preserved_verbatim(self):
        stale = [
            {"name": "13F", "enabled": True, "builtin": True},
            {"name": "caixin", "label": "财新网", "type": "rss",
             "url": "https://custom.test/feed", "enabled": True, "builtin": False},
        ]
        set_setting("sources_config", json.dumps(stale, ensure_ascii=False))
        cfg = get_sources_config()
        caixin = next(c for c in cfg if c["name"] == "caixin")
        assert caixin["url"] == "https://custom.test/feed"
        assert caixin["builtin"] is False

    def test_invalid_json_falls_back_to_defaults(self):
        set_setting("sources_config", "{not valid json")
        cfg = get_sources_config()
        assert {c["name"] for c in cfg} >= set(BUILTIN_SOURCE_NAMES)
