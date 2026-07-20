"""SQLite persistence layer."""
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional

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
        ):
            _add_column_if_not_exists(conn, table, column, col_type)

        _create_index_if_columns_exist(
            conn, "idx_reports_cik_quarter", "quarterly_reports", ["cik", "quarter"]
        )
        _create_index_if_columns_exist(conn, "idx_holdings_report_id", "holdings", ["report_id"])
        _create_index_if_columns_exist(
            conn, "idx_holdings_cik_quarter", "holdings", ["cik", "quarter"]
        )

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


_INSERT_SIGNAL_SQL = """
    INSERT OR REPLACE INTO signals (
        id, quarter, source, title, published_at,
        summary, companies, strength, url, cross_refs
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_UPSERT_SIGNAL_RUN_SQL = """
    INSERT INTO signal_runs (quarter, source_status, errors)
    VALUES (?, ?, ?)
    ON CONFLICT(quarter) DO UPDATE SET
        source_status=excluded.source_status,
        errors=excluded.errors,
        created_at=CURRENT_TIMESTAMP
"""


def _signal_row(quarter: str, s: Signal) -> tuple:
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
    )


def _insert_signals(
    conn: sqlite3.Connection, quarter: str, signals: List[Signal]
) -> None:
    """Replace a quarter's signal rows inside an existing transaction."""
    conn.execute("DELETE FROM signals WHERE quarter = ?", (quarter,))
    conn.executemany(_INSERT_SIGNAL_SQL, [_signal_row(quarter, s) for s in signals])


def _upsert_signal_run(
    conn: sqlite3.Connection,
    quarter: str,
    source_status: Optional[dict],
    errors: Optional[List[str]],
) -> None:
    """Upsert run metadata inside an existing transaction."""
    conn.execute(
        _UPSERT_SIGNAL_RUN_SQL,
        (
            quarter,
            json.dumps(source_status or {}, ensure_ascii=False),
            json.dumps(errors or [], ensure_ascii=False),
        ),
    )


def save_signals(quarter: str, signals: List[Signal]) -> None:
    """Persist aggregated signals for a quarter, replacing any previous run."""
    with get_connection() as conn:
        _insert_signals(conn, quarter, signals)
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


def save_signal_run(
    quarter: str,
    source_status: Optional[dict] = None,
    errors: Optional[List[str]] = None,
) -> None:
    """Persist metadata about a signal aggregation run for a quarter."""
    with get_connection() as conn:
        _upsert_signal_run(conn, quarter, source_status, errors)
        conn.commit()


def save_signal_payload(
    quarter: str,
    signals: List[Signal],
    source_status: Optional[dict] = None,
    errors: Optional[List[str]] = None,
) -> None:
    """Persist signals and run metadata for a quarter in a single transaction."""
    with get_connection() as conn:
        _insert_signals(conn, quarter, signals)
        _upsert_signal_run(conn, quarter, source_status, errors)
        conn.commit()


def get_signal_run(quarter: str) -> Optional[dict]:
    """Load signal aggregation run metadata, or None if the quarter never ran."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT quarter, source_status, errors FROM signal_runs WHERE quarter = ?",
            (quarter,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "quarter": row["quarter"],
            "source_status": json.loads(row["source_status"]) if row["source_status"] else {},
            "errors": json.loads(row["errors"]) if row["errors"] else [],
        }
