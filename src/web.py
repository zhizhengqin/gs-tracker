"""FastAPI web service for report browsing and API access."""
import logging
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from src.config import REPORT_OUTPUT_DIR

logger = logging.getLogger(__name__)

app = FastAPI(title="GS-Tracker", version="0.1.0")


@app.get("/", response_class=HTMLResponse)
async def list_reports() -> str:
    """Return the report listing page."""
    raise NotImplementedError("TODO: implement report list page")


@app.get("/reports/{quarter}.html", response_class=HTMLResponse)
async def get_report(quarter: str) -> str:
    """Return a single quarter HTML report."""
    report_path = REPORT_OUTPUT_DIR / f"{quarter}.html"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return report_path.read_text(encoding="utf-8")


@app.get("/api/reports")
async def api_reports() -> List[dict]:
    """Return metadata for all generated reports."""
    raise NotImplementedError("TODO: implement reports API")


@app.get("/api/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
