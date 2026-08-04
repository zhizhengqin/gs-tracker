"""Regression tests for bugs found by /qa on 2026-08-04.

Report: .gstack/qa-reports/qa-report-127-0-0-1-8770-2026-08-04.md
- ISSUE-001: per-signal analysis prefetch flooded the console with 404s;
  bulk endpoint POST /api/signals/analyses replaces N requests with 1.
"""
import pytest
from fastapi.testclient import TestClient

from src import storage
from src.auth import ensure_default_admin
from src.web import app


client = TestClient(app)
storage.init_db()
ensure_default_admin()
_login = client.post(
    "/api/auth/login", json={"username": "gsadmin", "password": "admin123"}
)
assert _login.status_code == 200, _login.text


@pytest.fixture
def analyses_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr("src.storage.DATABASE_URL", f"sqlite:///{db_file}")
    storage.init_db()
    ensure_default_admin()
    resp = client.post(
        "/api/auth/login", json={"username": "gsadmin", "password": "admin123"}
    )
    assert resp.status_code == 200, resp.text
    return db_file


def test_get_signal_analyses_roundtrip(analyses_db):
    storage.save_signal_analysis("s1", "解读一")
    storage.save_signal_analysis("s2", "解读二")
    storage.save_signal_analysis("s3", "AI 未生成有效解读")  # 失败哨兵应被排除
    out = storage.get_signal_analyses(["s1", "s2", "s3", "s4"])
    assert out == {"s1": "解读一", "s2": "解读二"}


def test_get_signal_analyses_empty_ids(analyses_db):
    assert storage.get_signal_analyses([]) == {}


def test_bulk_analyses_endpoint(analyses_db):
    storage.save_signal_analysis("s1", "缓存的解读")
    resp = client.post("/api/signals/analyses", json={"ids": ["s1", "s2"]})
    assert resp.status_code == 200
    assert resp.json()["analyses"] == {"s1": "缓存的解读"}


def test_bulk_analyses_endpoint_rejects_bad_body(analyses_db):
    resp = client.post("/api/signals/analyses", json={"ids": "not-a-list"})
    assert resp.status_code == 422
