"""SQLite persistence layer."""
import hashlib
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from src.config import DATABASE_URL, PROJECT_ROOT
from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)


def db_path() -> Path:
    """Resolve the SQLite database file path from DATABASE_URL."""
    url = DATABASE_URL
    if url.startswith("sqlite:///"):
        relative = url.replace("sqlite:///", "")
        return (PROJECT_ROOT / relative).resolve()
    raise ValueError(f"Unsupported DATABASE_URL: {DATABASE_URL}")


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection with row factory."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # WAL lets readers (web server) proceed while the pipeline process writes;
    # busy_timeout waits out short lock contention instead of failing.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        yield conn
    finally:
        conn.close()


def _add_column_if_not_exists(
    conn: sqlite3.Connection, table: str, column: str, col_type: str
) -> None:
    """Safely add a column to an existing table, ignoring duplicate-column errors."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check whether a column exists in a table."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _create_index_if_columns_exist(
    conn: sqlite3.Connection, index_name: str, table: str, columns: List[str]
) -> None:
    """Create an index only if all referenced columns already exist."""
    if all(_column_exists(conn, table, col) for col in columns):
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({', '.join(columns)})"
        )


def _add_unique_index_if_not_exists(
    conn: sqlite3.Connection, index_name: str, table: str, columns: List[str]
) -> None:
    """Create a UNIQUE index only if all referenced columns exist and the index is absent."""
    if not all(_column_exists(conn, table, col) for col in columns):
        return
    existing = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
            (table,),
        )
    }
    if index_name not in existing:
        conn.execute(
            f"CREATE UNIQUE INDEX {index_name} ON {table}({', '.join(columns)})"
        )


def _migrate_signal_runs_pk(conn: sqlite3.Connection) -> None:
    """Migrate signal_runs PK from (quarter) to (quarter, job) if needed.

    SQLite cannot ALTER TABLE DROP PRIMARY KEY, so we use the standard
    4-step recipe: create new table → copy data → drop old → rename new.
    """
    if not _column_exists(conn, "signal_runs", "job"):
        return

    # Check if the old PK (quarter alone, via rowid alias) is still in effect.
    # We know migration is needed if the table has the `job` column but it
    # was added via ALTER TABLE (migration added it) rather than being in
    # the CREATE TABLE. Pragmatic check: does a UNIQUE index on (quarter, job)
    # exist? If not, the old quarter-PK is still in place.
    indexes = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='signal_runs'"
        )
    }
    if "uq_signal_runs_quarter_job" in indexes:
        return  # already migrated

    # 4-step migration
    conn.execute("""
        CREATE TABLE signal_runs_new (
            quarter TEXT NOT NULL,
            job TEXT NOT NULL DEFAULT 'reconciliation',
            source_status TEXT,
            errors TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (quarter, job)
        )
    """)
    conn.execute("""
        INSERT INTO signal_runs_new (quarter, job, source_status, errors, created_at)
        SELECT quarter, COALESCE(job, 'reconciliation'),
               source_status, errors, created_at
        FROM signal_runs
    """)
    conn.execute("DROP TABLE signal_runs")
    conn.execute("ALTER TABLE signal_runs_new RENAME TO signal_runs")
    logger.info("Migrated signal_runs PK to (quarter, job)")


def init_db() -> None:
    """Initialize the database schema."""
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS quarterly_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cik TEXT NOT NULL,
                quarter TEXT NOT NULL,
                filing_date TEXT,
                period_of_report TEXT,
                total_value REAL,
                num_holdings INTEGER,
                xml_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (cik, quarter)
            );

            CREATE TABLE IF NOT EXISTS holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL,
                cik TEXT NOT NULL,
                quarter TEXT NOT NULL,
                cusip TEXT NOT NULL,
                name_of_issuer TEXT NOT NULL,
                title_of_class TEXT,
                value REAL,
                shares INTEGER,
                investment_discretion TEXT,
                voting_authority_sole INTEGER DEFAULT 0,
                voting_authority_shared INTEGER DEFAULT 0,
                voting_authority_none INTEGER DEFAULT 0,
                FOREIGN KEY (report_id) REFERENCES quarterly_reports(id)
            );

            CREATE TABLE IF NOT EXISTS sent_notifications (
                quarter TEXT PRIMARY KEY,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS signals (
                id TEXT NOT NULL,
                quarter TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                published_at TEXT NOT NULL,
                summary TEXT,
                companies TEXT,
                strength TEXT NOT NULL,
                url TEXT,
                cross_refs TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (quarter, id)
            );

            CREATE TABLE IF NOT EXISTS signal_runs (
                quarter TEXT PRIMARY KEY,
                source_status TEXT,
                errors TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS source_state (
                source TEXT NOT NULL,
                path TEXT NOT NULL,
                watermark TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (source, path)
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS llm_models (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                auth_token TEXT NOT NULL,
                model_name TEXT NOT NULL,
                is_default INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS signal_analysis (
                signal_id TEXT PRIMARY KEY,
                analysis_text TEXT NOT NULL,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS daily_reports (
                date TEXT PRIMARY KEY,
                report_text TEXT NOT NULL,
                signal_count INTEGER DEFAULT 0,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # Migrate existing databases: add columns that may be missing.
        for table, column, col_type in (
            ("quarterly_reports", "filing_date", "TEXT"),
            ("quarterly_reports", "period_of_report", "TEXT"),
            ("quarterly_reports", "total_value", "REAL"),
            ("quarterly_reports", "num_holdings", "INTEGER"),
            ("quarterly_reports", "xml_url", "TEXT"),
            ("holdings", "voting_authority_sole", "INTEGER DEFAULT 0"),
            ("holdings", "voting_authority_shared", "INTEGER DEFAULT 0"),
            ("holdings", "voting_authority_none", "INTEGER DEFAULT 0"),
            ("signals", "signal_fingerprint", "TEXT"),
            ("signals", "relevance_score", "REAL"),
            ("signal_runs", "job", "TEXT DEFAULT 'reconciliation'"),
        ):
            _add_column_if_not_exists(conn, table, column, col_type)

        # signal_fingerprint unique constraint — skip if already present.
        _add_unique_index_if_not_exists(
            conn, "idx_signals_fingerprint", "signals", ["signal_fingerprint"]
        )

        _create_index_if_columns_exist(
            conn, "idx_signals_published_at", "signals", ["published_at"]
        )
        _create_index_if_columns_exist(
            conn, "idx_reports_cik_quarter", "quarterly_reports", ["cik", "quarter"]
        )
        _create_index_if_columns_exist(conn, "idx_holdings_report_id", "holdings", ["report_id"])
        _create_index_if_columns_exist(
            conn, "idx_holdings_cik_quarter", "holdings", ["cik", "quarter"]
        )

        # Migrate signal_runs PK from quarter to (quarter, job) if still on old schema.
        _migrate_signal_runs_pk(conn)

        conn.commit()


def save_holdings(
    cik: str,
    quarter: str,
    holdings: List[dict],
    filing_info: Optional[dict] = None,
) -> int:
    """Persist holdings for a single quarter. Returns report_id."""
    filing_info = filing_info or {}
    total_value = filing_info.get("total_value")
    if total_value is None:
        total_value = sum(h.get("value") or 0.0 for h in holdings)
    num_holdings = filing_info.get("num_holdings")
    if num_holdings is None:
        num_holdings = len(holdings)

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO quarterly_reports (
                cik, quarter, filing_date, period_of_report, total_value, num_holdings, xml_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cik, quarter) DO UPDATE SET
                filing_date=excluded.filing_date,
                period_of_report=excluded.period_of_report,
                total_value=excluded.total_value,
                num_holdings=excluded.num_holdings,
                xml_url=excluded.xml_url
            """,
            (
                cik,
                quarter,
                filing_info.get("filing_date"),
                filing_info.get("period_of_report"),
                total_value,
                num_holdings,
                filing_info.get("xml_url"),
            ),
        )
        report_id = cursor.lastrowid

        cursor = conn.execute(
            "SELECT id FROM quarterly_reports WHERE cik = ? AND quarter = ?",
            (cik, quarter),
        )
        report_id = int(cursor.fetchone()["id"])

        conn.execute(
            "DELETE FROM holdings WHERE report_id = ?",
            (report_id,),
        )

        for holding in holdings:
            conn.execute(
                """
                INSERT INTO holdings (
                    report_id, cik, quarter, cusip, name_of_issuer,
                    title_of_class, value, shares, investment_discretion,
                    voting_authority_sole, voting_authority_shared, voting_authority_none
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    cik,
                    quarter,
                    holding["cusip"],
                    holding["name_of_issuer"],
                    holding.get("title_of_class"),
                    holding.get("value"),
                    holding.get("shares"),
                    holding.get("investment_discretion"),
                    holding.get("voting_sole") or holding.get("voting_authority_sole") or 0,
                    holding.get("voting_shared") or holding.get("voting_authority_shared") or 0,
                    holding.get("voting_none") or holding.get("voting_authority_none") or 0,
                ),
            )

        conn.commit()
        return report_id


def get_holdings(cik: str, quarter: str) -> List[dict]:
    """Load holdings for a given quarter."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT
                cusip,
                name_of_issuer,
                title_of_class,
                value,
                shares,
                investment_discretion,
                voting_authority_sole,
                voting_authority_shared,
                voting_authority_none
            FROM holdings
            WHERE cik = ? AND quarter = ?
            ORDER BY id
            """,
            (cik, quarter),
        )
        return [dict(row) for row in cursor.fetchall()]


def mark_notification_sent(quarter: str) -> bool:
    """Mark a quarter as notified.

    Returns True if this call inserted the row (first time),
    False if the quarter was already present.
    """
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO sent_notifications (quarter) VALUES (?)",
                (quarter,),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def is_notification_sent(quarter: str) -> bool:
    """Return whether a notification has already been sent for this quarter."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT 1 FROM sent_notifications WHERE quarter = ?",
            (quarter,),
        )
        return cursor.fetchone() is not None


def compute_fingerprint(signal: Signal) -> str:
    """Compute a deduplication fingerprint for a signal.

    Fingerprint = SHA-256 of (source, title, publish_date, url).
    When url is None (e.g. macro_view), the fingerprint falls back to
    (source, title, publish_date) — same-day same-title without URL will
    collide, which is correct for sources that produce at most one signal
    per day per topic.
    """
    date_str = signal.published_at.strftime("%Y-%m-%d")
    parts = [signal.source, signal.title, date_str]
    if signal.url:
        parts.append(signal.url)
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest


_INSERT_SIGNAL_SQL = """
    INSERT INTO signals (
        id, quarter, source, title, published_at,
        summary, companies, strength, url, cross_refs,
        signal_fingerprint, relevance_score
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


_UPSERT_SIGNAL_SQL = """
    INSERT INTO signals (
        id, quarter, source, title, published_at,
        summary, companies, strength, url, cross_refs,
        signal_fingerprint, relevance_score
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(signal_fingerprint) DO UPDATE SET
        strength=excluded.strength,
        cross_refs=excluded.cross_refs,
        relevance_score=excluded.relevance_score,
        quarter=excluded.quarter
"""

_UPSERT_SIGNAL_RUN_SQL = """
    INSERT INTO signal_runs (quarter, job, source_status, errors)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(quarter, job) DO UPDATE SET
        source_status=excluded.source_status,
        errors=excluded.errors,
        created_at=CURRENT_TIMESTAMP
"""


def _signal_row(quarter: str, s: Signal, fingerprint: str = "", score: float = 0.0) -> tuple:
    """Build the SQL parameter tuple for one signal."""
    return (
        s.id,
        quarter,
        s.source,
        s.title,
        s.published_at.isoformat(),
        s.summary,
        json.dumps(s.companies, ensure_ascii=False),
        s.strength.value,
        s.url,
        json.dumps(s.cross_refs, ensure_ascii=False),
        fingerprint or compute_fingerprint(s),
        score,
    )


def _upsert_signal_run(
    conn: sqlite3.Connection,
    quarter: str,
    job: str,
    source_status: Optional[dict],
    errors: Optional[List[str]],
) -> None:
    """Upsert run metadata inside an existing transaction."""
    conn.execute(
        _UPSERT_SIGNAL_RUN_SQL,
        (
            quarter,
            job,
            json.dumps(source_status or {}, ensure_ascii=False),
            json.dumps(errors or [], ensure_ascii=False),
        ),
    )


def _insert_signals(
    conn: sqlite3.Connection, quarter: str, signals: List[Signal]
) -> None:
    """Replace a quarter's signal rows inside an existing transaction.

    This is the legacy path used by the quarterly reconciliation job —
    it deletes all signals for the quarter and inserts fresh.
    """
    conn.execute("DELETE FROM signals WHERE quarter = ?", (quarter,))
    conn.executemany(_INSERT_SIGNAL_SQL, [_signal_row(quarter, s) for s in signals])


def _upsert_signals(
    conn: sqlite3.Connection, quarter: str, signals: List[Signal]
) -> None:
    """Upsert signals by signal_fingerprint inside an existing transaction.

    New fingerprints → INSERT. Existing fingerprints → UPDATE scoring
    fields (strength, cross_refs, relevance_score) only; content fields
    (title, summary, url, companies, published_at) are preserved from
    the first insert.

    This is the path for the daily intelligence job — incremental,
    no quarter-level deletion.
    """
    conn.executemany(
        _UPSERT_SIGNAL_SQL,
        [_signal_row(quarter, s) for s in signals],
    )


def save_signals(quarter: str, signals: List[Signal]) -> None:
    """Persist signals for a quarter, replacing any previous run.

    This is the quarterly reconciliation path: DELETE + INSERT per quarter.
    For incremental daily updates, use save_signals_incremental().
    """
    with get_connection() as conn:
        _insert_signals(conn, quarter, signals)
        conn.commit()


def save_signals_incremental(quarter: str, signals: List[Signal]) -> None:
    """Persist signals via fingerprint-based upsert — no quarter-level deletion.

    Used by the daily intelligence job. New fingerprints insert new rows;
    existing fingerprints update scoring fields only.
    """
    with get_connection() as conn:
        _upsert_signals(conn, quarter, signals)
        conn.commit()


def get_signals(quarter: str) -> List[Signal]:
    """Load persisted signals for a quarter, in insertion order.

    Malformed rows (unknown strength, unparseable date/JSON) are skipped
    with a warning so one bad row cannot fail the whole quarter.
    """
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, source, title, published_at, summary,
                   companies, strength, url, cross_refs
            FROM signals
            WHERE quarter = ?
            ORDER BY rowid
            """,
            (quarter,),
        )
        signals: List[Signal] = []
        for row in cursor.fetchall():
            try:
                signals.append(
                    Signal(
                        id=row["id"],
                        source=row["source"],
                        title=row["title"],
                        published_at=datetime.fromisoformat(row["published_at"]),
                        summary=row["summary"] or "",
                        companies=json.loads(row["companies"]) if row["companies"] else [],
                        strength=SignalStrength(row["strength"]),
                        url=row["url"],
                        cross_refs=json.loads(row["cross_refs"]) if row["cross_refs"] else [],
                    )
                )
            except (ValueError, TypeError, KeyError) as exc:
                logger.warning(
                    "Skipping malformed signal row (id=%s): %s", row["id"], exc
                )
        return signals


def get_recent_signals(
    days: int = 30, reference_date: Optional[datetime] = None
) -> List[Signal]:
    """Load signals published within the last N days, ordered by published_at DESC."""
    ref = reference_date or datetime.now(timezone.utc)
    cutoff = ref - timedelta(days=days)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, source, title, published_at, summary,
                   companies, strength, url, cross_refs
            FROM signals
            WHERE published_at >= ?
            ORDER BY published_at DESC
            """,
            (cutoff.isoformat(),),
        )
        signals: List[Signal] = []
        for row in cursor.fetchall():
            try:
                signals.append(
                    Signal(
                        id=row["id"],
                        source=row["source"],
                        title=row["title"],
                        published_at=datetime.fromisoformat(row["published_at"]),
                        summary=row["summary"] or "",
                        companies=json.loads(row["companies"]) if row["companies"] else [],
                        strength=SignalStrength(row["strength"]),
                        url=row["url"],
                        cross_refs=json.loads(row["cross_refs"]) if row["cross_refs"] else [],
                    )
                )
            except (ValueError, TypeError, KeyError) as exc:
                logger.warning(
                    "Skipping malformed signal row (id=%s): %s", row["id"], exc
                )
        return signals


def cleanup_expired_signals(retention_days: int = 90) -> int:
    """Delete signals older than *retention_days* days. Returns deleted count."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM signals WHERE published_at < ?",
            (cutoff.isoformat(),),
        )
        conn.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.info("Cleaned up %d expired signals (older than %d days)", deleted, retention_days)
        return deleted


def save_signal_run(
    quarter: str,
    job: str = "daily",
    source_status: Optional[dict] = None,
    errors: Optional[List[str]] = None,
) -> None:
    """Persist metadata about a signal aggregation run for a (quarter, job) pair."""
    with get_connection() as conn:
        _upsert_signal_run(conn, quarter, job, source_status, errors)
        conn.commit()


def save_signal_payload(
    quarter: str,
    signals: List[Signal],
    job: str = "daily",
    source_status: Optional[dict] = None,
    errors: Optional[List[str]] = None,
) -> None:
    """Persist signals (fingerprint-based upsert) and run metadata in a single transaction."""
    with get_connection() as conn:
        _upsert_signals(conn, quarter, signals)
        _upsert_signal_run(conn, quarter, job, source_status, errors)
        conn.commit()


def get_signal_run(
    quarter: str, job: Optional[str] = None
) -> Optional[dict]:
    """Load signal aggregation run metadata, or None if it never ran.

    When *job* is None, returns the daily row if available, falling back
    to reconciliation. This preserves backward compatibility with the
    single-job API.
    """
    with get_connection() as conn:
        if job is not None:
            cursor = conn.execute(
                "SELECT quarter, job, source_status, errors FROM signal_runs "
                "WHERE quarter = ? AND job = ?",
                (quarter, job),
            )
        else:
            cursor = conn.execute(
                "SELECT quarter, job, source_status, errors FROM signal_runs "
                "WHERE quarter = ? ORDER BY job = 'daily' DESC LIMIT 1",
                (quarter,),
            )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "quarter": row["quarter"],
            "job": row["job"],
            "source_status": json.loads(row["source_status"]) if row["source_status"] else {},
            "errors": json.loads(row["errors"]) if row["errors"] else [],
        }


def save_source_state(source: str, path: str, watermark: str) -> None:
    """Persist the latest watermark for one (source, path) pair."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO source_state (source, path, watermark, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source, path) DO UPDATE SET
                watermark=excluded.watermark,
                updated_at=CURRENT_TIMESTAMP
            """,
            (source, path, watermark),
        )
        conn.commit()


def get_source_state(source: str, path: str) -> Optional[str]:
    """Load the latest watermark for a (source, path) pair, or None."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT watermark FROM source_state WHERE source = ? AND path = ?",
            (source, path),
        )
        row = cursor.fetchone()
        return row["watermark"] if row else None


# ====== App settings (key-value) ======

def get_setting(key: str, default: str = "") -> str:
    """Read a single setting value, or *default* if not found."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    """Persist a key-value setting."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()


def get_all_settings() -> dict:
    """Return all settings as a dict."""
    with get_connection() as conn:
        rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


# ====== LLM model management ======

def get_llm_models() -> List[dict]:
    """Return all configured LLM models, default first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, base_url, auth_token, model_name, is_default, created_at "
            "FROM llm_models ORDER BY is_default DESC, created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_default_llm_model() -> Optional[dict]:
    """Return the default LLM model config, or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, base_url, auth_token, model_name "
            "FROM llm_models WHERE is_default = 1 LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def add_llm_model(
    model_id: str, name: str, base_url: str, auth_token: str, model_name: str
) -> None:
    """Insert a new LLM model. If no default exists, make it the default."""
    with get_connection() as conn:
        has_default = conn.execute(
            "SELECT 1 FROM llm_models WHERE is_default = 1 LIMIT 1"
        ).fetchone()
        conn.execute(
            "INSERT INTO llm_models (id, name, base_url, auth_token, model_name, is_default) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (model_id, name, base_url, auth_token, model_name, 0 if has_default else 1),
        )
        conn.commit()


def set_default_llm_model(model_id: str) -> None:
    """Set one LLM model as the default, clearing the previous default."""
    with get_connection() as conn:
        conn.execute("UPDATE llm_models SET is_default = 0")
        conn.execute("UPDATE llm_models SET is_default = 1 WHERE id = ?", (model_id,))
        conn.commit()


def delete_llm_model(model_id: str) -> bool:
    """Delete an LLM model. Refuses to delete the default model. Returns True if deleted."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_default FROM llm_models WHERE id = ?", (model_id,)
        ).fetchone()
        if row is None:
            return False
        if row["is_default"]:
            return False  # refuse to delete the active default
        conn.execute("DELETE FROM llm_models WHERE id = ?", (model_id,))
        conn.commit()
        return True


# ====== Signal AI analysis cache ======

def get_signal_analysis(signal_id: str) -> Optional[str]:
    """Return cached AI analysis for a signal, or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT analysis_text FROM signal_analysis WHERE signal_id = ?",
            (signal_id,),
        ).fetchone()
        return row["analysis_text"] if row else None


def save_signal_analysis(signal_id: str, analysis_text: str) -> None:
    """Cache AI analysis for a signal (idempotent upsert)."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO signal_analysis (signal_id, analysis_text, generated_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(signal_id) DO UPDATE SET "
            "analysis_text=excluded.analysis_text, generated_at=CURRENT_TIMESTAMP",
            (signal_id, analysis_text),
        )
        conn.commit()


# ====== Daily report cache ======

def get_daily_report(date_str: str) -> Optional[dict]:
    """Return cached daily report for a date, or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT date, report_text, signal_count, generated_at "
            "FROM daily_reports WHERE date = ?",
            (date_str,),
        ).fetchone()
        return dict(row) if row else None


def save_daily_report(date_str: str, report_text: str, signal_count: int = 0) -> None:
    """Cache a daily summary report (idempotent upsert)."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO daily_reports (date, report_text, signal_count, generated_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(date) DO UPDATE SET "
            "report_text=excluded.report_text, signal_count=excluded.signal_count, "
            "generated_at=CURRENT_TIMESTAMP",
            (date_str, report_text, signal_count),
        )
        conn.commit()


# ====== Signals by date ======

def get_signals_by_date(date_str: str) -> List[Signal]:
    """Return all signals published on a specific date (YYYY-MM-DD)."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, source, title, published_at, summary,
                   companies, strength, url, cross_refs
            FROM signals
            WHERE DATE(published_at) = ?
            ORDER BY published_at DESC
            """,
            (date_str,),
        )
        signals: List[Signal] = []
        for row in cursor.fetchall():
            try:
                signals.append(
                    Signal(
                        id=row["id"],
                        source=row["source"],
                        title=row["title"],
                        published_at=datetime.fromisoformat(row["published_at"]),
                        summary=row["summary"] or "",
                        companies=json.loads(row["companies"]) if row["companies"] else [],
                        strength=SignalStrength(row["strength"]),
                        url=row["url"],
                        cross_refs=json.loads(row["cross_refs"]) if row["cross_refs"] else [],
                    )
                )
            except (ValueError, TypeError, KeyError) as exc:
                logger.warning(
                    "Skipping malformed signal row (id=%s): %s", row["id"], exc
                )
        return signals
