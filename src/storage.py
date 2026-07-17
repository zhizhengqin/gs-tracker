"""SQLite persistence layer."""
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import List

from src.config import DATABASE_URL, PROJECT_ROOT

logger = logging.getLogger(__name__)


def db_path() -> Path:
    """Resolve the SQLite database file path from DATABASE_URL."""
    url = DATABASE_URL
    if url.startswith("sqlite:///"):
        relative = url.replace("sqlite:///", "")
        return (PROJECT_ROOT / relative).resolve()
    raise ValueError(f"Unsupported DATABASE_URL: {DATABASE_URL}")


@contextmanager
def get_connection():
    """Yield a SQLite connection with row factory."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Initialize the database schema."""
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS quarterly_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cik TEXT NOT NULL,
                quarter TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (cik, quarter)
            );

            CREATE INDEX IF NOT EXISTS idx_reports_cik_quarter
                ON quarterly_reports(cik, quarter);

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
                FOREIGN KEY (report_id) REFERENCES quarterly_reports(id)
            );

            CREATE INDEX IF NOT EXISTS idx_holdings_report_id
                ON holdings(report_id);
            CREATE INDEX IF NOT EXISTS idx_holdings_cik_quarter
                ON holdings(cik, quarter);
            """
        )
        conn.commit()


def save_holdings(cik: str, quarter: str, holdings: List[dict]) -> int:
    """Persist holdings for a single quarter. Returns report_id."""
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT OR REPLACE INTO quarterly_reports (cik, quarter) VALUES (?, ?)",
            (cik, quarter),
        )
        conn.commit()

        cursor = conn.execute(
            "SELECT id FROM quarterly_reports WHERE cik = ? AND quarter = ?",
            (cik, quarter),
        )
        report_id = cursor.fetchone()["id"]

        conn.execute(
            "DELETE FROM holdings WHERE report_id = ?",
            (report_id,),
        )

        for holding in holdings:
            conn.execute(
                """
                INSERT INTO holdings (
                    report_id, cik, quarter, cusip, name_of_issuer,
                    title_of_class, value, shares, investment_discretion
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                investment_discretion
            FROM holdings
            WHERE cik = ? AND quarter = ?
            ORDER BY id
            """,
            (cik, quarter),
        )
        return [dict(row) for row in cursor.fetchall()]
