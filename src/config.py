"""Application configuration loaded from environment variables."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MAX_RETRIES = int(os.getenv("ANTHROPIC_MAX_RETRIES", "3"))
ANTHROPIC_BACKOFF_BASE = float(os.getenv("ANTHROPIC_BACKOFF_BASE", "1.0"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/db/gs_tracker.db")
REPORT_OUTPUT_DIR = Path(os.getenv("REPORT_OUTPUT_DIR", "output/reports"))

SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "GS-Tracker contact@example.com")
SEC_MAX_RETRIES = int(os.getenv("SEC_MAX_RETRIES", "3"))
SEC_BACKOFF_BASE = float(os.getenv("SEC_BACKOFF_BASE", "1.0"))
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
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
NOTIFIER_MAX_ATTEMPTS = int(os.getenv("NOTIFIER_MAX_ATTEMPTS", "3"))
NOTIFIER_BACKOFF_BASE = float(os.getenv("NOTIFIER_BACKOFF_BASE", "1.0"))

RSS_FEEDS_RAW = os.getenv(
    "RSS_FEEDS",
    "https://feeds.content.dowjones.io/public/rss/RSSWSJ,https://www.reuters.com/arc/outboundfeeds/v3/all/?outputType=xml",
)
RSS_FEEDS: list[str] = [u.strip() for u in RSS_FEEDS_RAW.split(",") if u.strip()]
SIGNAL_LOOKBACK_DAYS = int(os.getenv("SIGNAL_LOOKBACK_DAYS", "90"))

SEC_API_KEY = os.getenv("SEC_API_KEY", "")
FINRA_API_KEY = os.getenv("FINRA_API_KEY", "")
CBOE_API_KEY = os.getenv("CBOE_API_KEY", "")
BLOOMBERG_API_KEY = os.getenv("BLOOMBERG_API_KEY", "")


def ensure_directories() -> None:
    """Ensure required data/output directories exist."""
    REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "data" / "db").mkdir(parents=True, exist_ok=True)
