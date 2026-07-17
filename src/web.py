"""FastAPI web service for report browsing and API access."""
import logging
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from src.config import REPORT_OUTPUT_DIR

logger = logging.getLogger(__name__)

app = FastAPI(title="GS-Tracker", version="0.1.0")


def _list_report_files() -> List[Path]:
    """Return sorted HTML report files in the output directory."""
    if not REPORT_OUTPUT_DIR.exists():
        return []
    return sorted(REPORT_OUTPUT_DIR.glob("*.html"))


@app.get("/", response_class=HTMLResponse)
async def list_reports() -> str:
    """Return the report listing page in Chinese."""
    files = _list_report_files()
    items = []
    for file_path in files:
        quarter = file_path.stem
        link = f"/reports/{quarter}.html"
        items.append(f'<li><a href="{link}">高盛动向情报板 — {quarter}</a></li>')

    items_html = "\n".join(items) if items else "<li>暂无报告</li>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>GS-Tracker 报告列表</title>
</head>
<body>
    <h1>高盛动向情报系统 — 报告列表</h1>
    <ul>
        {items_html}
    </ul>
</body>
</html>"""


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


@app.get("/api/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
