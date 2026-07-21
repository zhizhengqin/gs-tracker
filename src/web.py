"""FastAPI web service for dashboard, report browsing and API access."""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Path as PathParam
from fastapi.responses import HTMLResponse

from src.config import PROJECT_ROOT, REPORT_OUTPUT_DIR
from src.main import run_pipeline
from src.signals.base import Signal
from src.storage import get_recent_signals, get_signal_run, get_signals, init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure the database schema exists before serving requests."""
    init_db()
    yield


app = FastAPI(title="GS-Tracker", version="0.2.0", lifespan=lifespan)

DASHBOARD_TEMPLATE = PROJECT_ROOT / "templates" / "dashboard.html"


def _list_report_files() -> List[Path]:
    """Return HTML report files sorted newest-first (quarter names sort lexically)."""
    if not REPORT_OUTPUT_DIR.exists():
        return []
    return sorted(REPORT_OUTPUT_DIR.glob("*.html"), reverse=True)


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
    """Serialize a Signal dataclass to a JSON-friendly dict.

    Naive datetimes are normalized to UTC so the wire format always
    carries an explicit offset (all production sources emit UTC).
    """
    published = signal.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return {
        "id": signal.id,
        "title": signal.title,
        "source": signal.source,
        "published_at": published.isoformat(),
        "summary": signal.summary,
        "companies": signal.companies,
        "strength": signal.strength.value,
        "url": signal.url,
        "cross_refs": signal.cross_refs,
    }


@app.get("/api/signals/{quarter}")
async def api_signals(
    quarter: str = PathParam(pattern=r"^\d{4}-Q[1-4]$"),
) -> dict:
    """Return structured signal data for a quarter."""
    run = await asyncio.to_thread(get_signal_run, quarter)
    if run is None:
        raise HTTPException(status_code=404, detail="该季度暂无信号数据")
    signals = await asyncio.to_thread(get_signals, quarter)
    return {
        "quarter": quarter,
        "signals": [_signal_to_dict(s) for s in signals],
        "source_status": run["source_status"],
        "errors": run["errors"],
    }


@app.get("/api/signals/recent")
async def api_signals_recent(days: int = 30) -> dict:
    """Return signals from the last N days, ordered by published_at descending."""
    if days < 1 or days > 365:
        raise HTTPException(status_code=422, detail="days 参数必须在 1 到 365 之间")
    signals = await asyncio.to_thread(get_recent_signals, days)
    return {
        "days": days,
        "count": len(signals),
        "signals": [_signal_to_dict(s) for s in signals],
    }


@app.get("/api/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


# ====== Manual pipeline trigger ======

_pipeline_state: Dict[str, Any] = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_error": None,
}


async def _run_pipeline_tracked() -> None:
    """Run the full pipeline, recording lifecycle state for the status endpoint."""
    _pipeline_state.update(
        running=True,
        last_error=None,
        last_started_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        await run_pipeline()
    except Exception as exc:
        logger.exception("Manual pipeline run failed")
        _pipeline_state["last_error"] = str(exc)
    finally:
        _pipeline_state.update(
            running=False,
            last_finished_at=datetime.now(timezone.utc).isoformat(),
        )


@app.post("/api/pipeline/run", status_code=202)
async def api_pipeline_run() -> dict:
    """Trigger a full pipeline run in the background (409 if already running)."""
    if _pipeline_state["running"]:
        raise HTTPException(status_code=409, detail="流水线正在运行中，请稍候")
    # Mark running synchronously so the first status poll never sees a stale idle state
    _pipeline_state.update(
        running=True,
        last_error=None,
        last_started_at=datetime.now(timezone.utc).isoformat(),
    )
    asyncio.create_task(_run_pipeline_tracked())
    return {"status": "已启动"}


@app.get("/api/pipeline/status")
async def api_pipeline_status() -> dict:
    """Return the current pipeline run state for dashboard polling."""
    return dict(_pipeline_state)
