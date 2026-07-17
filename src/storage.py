"""SQLite persistence layer."""
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional

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
    raise NotImplementedError("TODO: implement schema initialization")


def save_holdings(cik: str, quarter: str, holdings: List[dict]) -> int:
    """Persist holdings for a single quarter. Returns report_id."""
    raise NotImplementedError("TODO: implement save_holdings")


def get_holdings(cik: str, quarter: str) -> List[dict]:
    """Load holdings for a given quarter."""
    raise NotImplementedError("TODO: implement get_holdings")
