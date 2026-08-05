"""Regression tests for the fingerprint-drift upsert failure.

The daily job re-saves DB-loaded signals after re-scoring. Rows stored with
legacy (date-based) fingerprints recompute to URL-based fingerprints, so
ON CONFLICT(signal_fingerprint) never fired and the INSERT violated
UNIQUE(quarter, id) — the whole daily batch was lost.
"""
import hashlib
from datetime import datetime, timezone

import pytest

from src.signals.base import Signal, SignalStrength
from src.storage import (
    compute_fingerprint,
    get_connection,
    init_db,
    save_signals_incremental,
)


def _sig(title="测试信号", url="https://example.com/a", day="2026-07-27"):
    return Signal(
        title=title,
        source="news",
        published_at=datetime.fromisoformat(day + "T08:00:00+08:00"),
        summary="",
        companies=[],
        strength=SignalStrength.MEDIUM,
        url=url,
    )


def _legacy_fp(sig: Signal) -> str:
    """Old scheme: date is always part of the fingerprint, even with a URL."""
    raw = "|".join([sig.source, sig.title, sig.url or "", sig.published_at.strftime("%Y-%m-%d")])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _stored_fp(signal_id: str) -> str:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT signal_fingerprint FROM signals WHERE id=?", (signal_id,)
        ).fetchone()
        return row[0]


def _count_rows(signal_id: str) -> int:
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM signals WHERE id=?", (signal_id,)
        ).fetchone()[0]


class TestFingerprintRepair:
    @pytest.fixture(autouse=True)
    def fresh_db(self, tmp_path, monkeypatch):
        db_file = tmp_path / "test.db"
        monkeypatch.setattr("src.storage.DATABASE_URL", f"sqlite:///{db_file}")
        init_db()

    def _corrupt_fp_to_legacy(self, sig: Signal):
        with get_connection() as conn:
            conn.execute(
                "UPDATE signals SET signal_fingerprint=? WHERE id=?",
                (_legacy_fp(sig), sig.id),
            )
            conn.commit()

    def test_init_db_repairs_legacy_fingerprints(self):
        sig = _sig()
        save_signals_incremental("2026-Q3", [sig])
        self._corrupt_fp_to_legacy(sig)
        assert _stored_fp(sig.id) != compute_fingerprint(sig)

        init_db()  # migrations re-run, including the repair pass

        assert _stored_fp(sig.id) == compute_fingerprint(sig)

    def test_upsert_with_drifted_fingerprint_does_not_raise(self):
        """Same id, drifted stored fingerprint -> update, never IntegrityError."""
        sig = _sig()
        save_signals_incremental("2026-Q3", [sig])
        self._corrupt_fp_to_legacy(sig)

        sig.strength = SignalStrength.HIGH  # re-scored, as the daily job does
        save_signals_incremental("2026-Q3", [sig])  # must not raise

        assert _count_rows(sig.id) == 1
        assert _stored_fp(sig.id) == compute_fingerprint(sig)

    def test_upsert_same_fingerprint_new_id_still_dedupes(self):
        """Re-fetched same article (fresh uuid) updates the existing row."""
        first = _sig()
        save_signals_incremental("2026-Q3", [first])
        second = _sig()  # same article, different uuid
        assert second.id != first.id

        save_signals_incremental("2026-Q3", [second])

        with get_connection() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM signals WHERE signal_fingerprint=?",
                (compute_fingerprint(first),),
            ).fetchone()[0]
        assert n == 1

    def test_init_db_removes_same_day_url_duplicates(self):
        """Same (source,title,url) twice on the same day -> keep exactly one.

        The legacy dedupe only removed later-DATE duplicates; same-day twins
        survived, blocked fingerprint repair, and rendered as double cards.
        """
        first = _sig()
        second = _sig()  # identical content, different uuid
        assert second.id != first.id
        save_signals_incremental("2026-Q3", [first])
        # force-insert the twin with a legacy fp so it bypasses fp conflict
        import json as _json
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO signals (id, quarter, institution_id, source, title,
                       published_at, summary, companies, strength, url, cross_refs,
                       signal_fingerprint, relevance_score, cross_institutional)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (second.id, "2026-Q3", "gs", second.source, second.title,
                 second.published_at.isoformat(), "", "[]", "medium", second.url,
                 "[]", _legacy_fp(second), 0.0, 0),
            )
            conn.commit()

        init_db()  # dedupe + repair

        with get_connection() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM signals WHERE source=? AND title=? AND url=?",
                (first.source, first.title, first.url),
            ).fetchone()[0]
        assert n == 1
