"""FastAPI web service for dashboard, report browsing and API access."""
import logging
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.config import PROJECT_ROOT, REPORT_OUTPUT_DIR
from src.signals.base import Signal
from src.storage import get_signal_run, get_signals

logger = logging.getLogger(__name__)

app = FastAPI(title="GS-Tracker", version="0.2.0")

DASHBOARD_TEMPLATE = PROJECT_ROOT / "templates" / "dashboard.html"


def _list_report_files() -> List[Path]:
    """Return sorted HTML report files in the output directory."""
    if not REPORT_OUTPUT_DIR.exists():
        return []
    return sorted(REPORT_OUTPUT_DIR.glob("*.html"))


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    """Serve the interactive dashboard."""
    if DASHBOARD_TEMPLATE.exists():
        return DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    # Fallback to simple listing
    files = _list_report_files()
    items = "".join(
        f'<li><a href="/reports/{f.name}">高盛动向情报板 — {f.stem}</a></li>'
        for f in files
    ) or "<li>暂无报告</li>"
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>GS-Tracker</title></head>
<body><h1>高盛动向情报系统</h1><ul>{items}</ul></body></html>"""


@app.get("/reports/{quarter}.html", response_class=HTMLResponse)
async def get_report(quarter: str) -> str:
    """Return a single quarter HTML report."""
    report_path = REPORT_OUTPUT_DIR / f"{quarter}.html"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="未找到该季度报告")
    return report_path.read_text(encoding="utf-8")


@app.get("/api/reports")
async def api_reports() -> List[dict]:
    """Return metadata for all generated reports."""
    files = _list_report_files()
    return [
        {
            "quarter": file_path.stem,
            "title": f"高盛动向情报板 — {file_path.stem}",
            "path": f"/reports/{file_path.name}",
        }
        for file_path in files
    ]


def _signal_to_dict(signal: Signal) -> dict:
    """Serialize a Signal dataclass to a JSON-friendly dict."""
    return {
        "id": signal.id,
        "title": signal.title,
        "source": signal.source,
        "published_at": signal.published_at.isoformat(),
        "summary": signal.summary,
        "companies": signal.companies,
        "strength": signal.strength.value,
        "url": signal.url,
        "cross_refs": signal.cross_refs,
    }


@app.get("/api/signals/{quarter}")
async def api_signals(quarter: str) -> dict:
    """Return structured signal data for a quarter."""
    run = get_signal_run(quarter)
    if run is None:
        raise HTTPException(status_code=404, detail="该季度暂无信号数据")
    return {
        "quarter": quarter,
        "signals": [_signal_to_dict(s) for s in get_signals(quarter)],
        "source_status": run["source_status"],
        "errors": run["errors"],
    }


@app.get("/api/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}