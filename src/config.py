"""Application configuration loaded from environment variables."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/db/gs_tracker.db")
REPORT_OUTPUT_DIR = Path(os.getenv("REPORT_OUTPUT_DIR", "output/reports"))

SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "GS-Tracker contact@example.com")
GOLDMAN_CIK = "0000886982"

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")

FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")
DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SEC_API_KEY = os.getenv("SEC_API_KEY", "")
FINRA_API_KEY = os.getenv("FINRA_API_KEY", "")
CBOE_API_KEY = os.getenv("CBOE_API_KEY", "")
BLOOMBERG_API_KEY = os.getenv("BLOOMBERG_API_KEY", "")


def ensure_directories() -> None:
    """Ensure required data/output directories exist."""
    REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "data" / "db").mkdir(parents=True, exist_ok=True)
