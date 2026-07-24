"""FastAPI web service for dashboard, report browsing and API access."""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException, Path as PathParam
from fastapi.responses import HTMLResponse, StreamingResponse

from src.config import PROJECT_ROOT, REPORT_OUTPUT_DIR
from src.main import run_pipeline
from src.signals.base import Signal
from src.storage import (
    add_llm_model,
    delete_llm_model,
    get_all_settings,
    get_daily_report,
    get_default_llm_model,
    get_llm_models,
    get_recent_signals,
    get_setting,
    get_signal_analysis,
    get_signal_run,
    get_signals,
    get_signals_by_date,
    init_db,
    save_daily_report,
    save_signal_analysis,
    set_default_llm_model,
    set_setting,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure the database schema exists before serving requests."""
    init_db()
    _seed_default_llm_from_env()
    yield


def _seed_default_llm_from_env() -> None:
    """If no LLM model is configured yet but env vars carry credentials,
    insert them as the default model so AI features work out of the box
    and the settings page shows the active configuration."""
    from src.config import (
        ANTHROPIC_API_KEY,
        ANTHROPIC_AUTH_TOKEN,
        ANTHROPIC_BASE_URL,
        GS_LLM_MODEL,
    )

    try:
        if get_llm_models():
            return
        token = ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY
        if not token:
            return
        base_url = ANTHROPIC_BASE_URL or "https://api.anthropic.com"
        add_llm_model("env-default", "环境变量默认模型", base_url, token, GS_LLM_MODEL)
        logger.info("Seeded default LLM model from environment variables")
    except Exception:
        logger.exception("Failed to seed default LLM model from env")


def _llm_client_kwargs(db_model: Optional[dict]) -> dict:
    """Resolve LLM client settings: DB default model first, env vars as fallback."""
    from src.config import (
        ANTHROPIC_API_KEY,
        ANTHROPIC_AUTH_TOKEN,
        ANTHROPIC_BASE_URL,
        GS_LLM_MODEL,
    )

    if db_model:
        return {
            "api_key": None,
            "auth_token": db_model["auth_token"] or None,
            "base_url": db_model["base_url"] or None,
            "model": db_model["model_name"],
        }
    return {
        "api_key": ANTHROPIC_API_KEY or None,
        "auth_token": ANTHROPIC_AUTH_TOKEN or None,
        "base_url": ANTHROPIC_BASE_URL or None,
        "model": GS_LLM_MODEL,
    }


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


# ====== Manual daily intel trigger ======

_daily_intel_state: Dict[str, Any] = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_error": None,
}


async def _run_daily_intel_tracked() -> None:
    from src.main import run_daily_intel

    _daily_intel_state.update(
        running=True,
        last_error=None,
        last_started_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        result = await run_daily_intel()
        logger.info(
            "Manual daily intel: %d new signals, status=%s",
            result["new_signals"], result["source_status"],
        )
    except Exception as exc:
        logger.exception("Manual daily intel failed")
        _daily_intel_state["last_error"] = str(exc)
    finally:
        _daily_intel_state.update(
            running=False,
            last_finished_at=datetime.now(timezone.utc).isoformat(),
        )


@app.post("/api/pipeline/run-daily", status_code=202)
async def api_daily_intel_run() -> dict:
    """Trigger a daily intelligence job in the background (409 if already running)."""
    if _daily_intel_state["running"]:
        raise HTTPException(status_code=409, detail="每日情报正在运行中，请稍候")
    _daily_intel_state.update(
        running=True,
        last_error=None,
        last_started_at=datetime.now(timezone.utc).isoformat(),
    )
    asyncio.create_task(_run_daily_intel_tracked())
    return {"status": "已启动"}


# ====== Shared daily intel job (SSE attach-or-start) ======

_DAILY_JOB_GRACE_SECONDS = 120  # finished job stays replayable this long


class _DailyJob:
    """A single daily intel run with an event log subscribers can replay."""

    def __init__(self) -> None:
        self.events: List[str] = []
        self.done = False
        self.finished_at: Optional[datetime] = None
        self.cond = asyncio.Condition()


_daily_job: Optional[_DailyJob] = None


async def _daily_job_runner(job: _DailyJob) -> None:
    """Run the daily intel stream once, appending events to the shared log."""
    import json as _json

    from src.main import run_daily_intel_stream

    _daily_intel_state.update(
        running=True,
        last_error=None,
        last_started_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        async for event_json in run_daily_intel_stream():
            async with job.cond:
                job.events.append(event_json)
                job.cond.notify_all()
    except Exception as exc:
        logger.exception("Daily intel stream job failed")
        _daily_intel_state["last_error"] = str(exc)
        error_event = _json.dumps({"event": "job_error", "error": str(exc)})
        async with job.cond:
            job.events.append(error_event)
            job.cond.notify_all()
    finally:
        _daily_intel_state.update(
            running=False,
            last_finished_at=datetime.now(timezone.utc).isoformat(),
        )
        async with job.cond:
            job.done = True
            job.finished_at = datetime.now(timezone.utc)
            job.cond.notify_all()


def _get_or_start_daily_job() -> _DailyJob:
    """Return the active (or recently finished) job, starting a new one if needed."""
    global _daily_job
    now = datetime.now(timezone.utc)
    job = _daily_job
    if job is not None:
        if not job.done:
            return job  # still running — attach
        assert job.finished_at is not None
        age = (now - job.finished_at).total_seconds()
        if age < _DAILY_JOB_GRACE_SECONDS:
            return job  # recently finished — let reconnects replay the summary
    job = _DailyJob()
    _daily_job = job
    asyncio.create_task(_daily_job_runner(job))
    return job


@app.get("/api/pipeline/run-daily/stream")
async def api_daily_intel_stream():
    """Stream daily intel progress over SSE.

    The job itself is shared process-wide: the first connection starts it,
    later connections (including EventSource auto-reconnects after a proxy
    timeout) attach to the SAME job and replay its event log, instead of
    spawning duplicate runs. A finished job stays attachable for a grace
    period so a late reconnect still sees the final summary.
    """
    job = _get_or_start_daily_job()

    async def event_stream():
        cursor = 0
        while True:
            async with job.cond:
                # Deliver any new events, else wait for more / completion
                while cursor >= len(job.events) and not job.done:
                    await job.cond.wait()
                pending = job.events[cursor:]
                cursor = len(job.events)
                done = job.done
            for event_json in pending:
                yield f"data: {event_json}\n\n"
            if done and cursor >= len(job.events):
                return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/pipeline/run-daily/status")
async def api_daily_intel_status() -> dict:
    """Return the current daily intel job state for dashboard polling."""
    return dict(_daily_intel_state)


@app.get("/api/pipeline/status")
async def api_pipeline_status() -> dict:
    """Return the current pipeline run state for dashboard polling."""
    return dict(_pipeline_state)


# ====== Settings API ======

@app.get("/api/settings")
async def api_get_settings() -> dict:
    """Return all application settings."""
    return get_all_settings()


@app.put("/api/settings")
async def api_update_settings(settings: dict = Body(...)) -> dict:
    """Bulk-update application settings."""
    for key, value in settings.items():
        if isinstance(value, str):
            set_setting(key, value)
    return {"status": "ok"}


@app.get("/api/settings/sources")
async def api_get_sources() -> list:
    """Return the configured signal source list (enabled/disabled state)."""
    import json
    raw = get_setting("sources_config", "")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    # Default: all 6 built-in sources enabled
    defaults = [
        {"name": "13F", "label": "13F 持仓", "description": "高盛季度 13F 持仓报告", "enabled": True, "builtin": True},
        {"name": "8-K", "label": "SEC 8-K", "description": "高盛重大事件即时披露", "enabled": True, "builtin": True},
        {"name": "13D/13G", "label": "13D/13G", "description": "大股东权益变动披露", "enabled": True, "builtin": True},
        {"name": "research_view", "label": "高盛研究", "description": "官方 Insights 研究文章", "enabled": True, "builtin": True},
        {"name": "news", "label": "新闻", "description": "RSS 新闻关键词匹配", "enabled": True, "builtin": True},
        {"name": "macro_view", "label": "宏观指标", "description": "FRED 宏观数据（利率/VIX/美元）", "enabled": True, "builtin": True},
    ]
    return defaults


@app.put("/api/settings/sources")
async def api_update_sources(sources: List[dict] = Body(...)) -> dict:
    """Save signal source configuration."""
    import json
    set_setting("sources_config", json.dumps(sources, ensure_ascii=False))
    return {"status": "ok"}


# ====== LLM model management ======

import uuid as _uuid

@app.get("/api/settings/llm-models")
async def api_get_llm_models() -> list:
    """Return all configured LLM models (auth_token masked)."""
    models = get_llm_models()
    for m in models:
        token = m.get("auth_token", "")
        if token:
            m["auth_token_masked"] = token[:4] + "****" + token[-4:] if len(token) > 8 else "****"
    return models


@app.post("/api/settings/llm-models/test")
async def api_test_llm_model(config: dict = Body(...)) -> dict:
    """Test connectivity for a candidate LLM model config."""
    base_url = (config.get("base_url") or "").strip()
    auth_token = (config.get("auth_token") or "").strip()
    model_name = (config.get("model_name") or "").strip()
    if not base_url or not auth_token or not model_name:
        raise HTTPException(status_code=422, detail="base_url, auth_token, model_name 均为必填")

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(
            base_url=base_url,
            auth_token=auth_token,
            timeout=15.0,
        )
        resp = await client.messages.create(
            model=model_name,
            max_tokens=16,
            messages=[{"role": "user", "content": "ping"}],
        )
        text = ""
        for block in resp.content:
            if hasattr(block, "text"):
                text += block.text
        return {"status": "ok", "response": text[:100]}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:500]}


@app.post("/api/settings/llm-models")
async def api_add_llm_model(config: dict = Body(...)) -> dict:
    """Add a new LLM model configuration."""
    name = (config.get("name") or "").strip()
    base_url = (config.get("base_url") or "").strip()
    auth_token = (config.get("auth_token") or "").strip()
    model_name = (config.get("model_name") or "").strip()
    if not all([name, base_url, auth_token, model_name]):
        raise HTTPException(status_code=422, detail="name, base_url, auth_token, model_name 均为必填")

    model_id = str(_uuid.uuid4())[:8]
    add_llm_model(model_id, name, base_url, auth_token, model_name)
    return {"status": "ok", "id": model_id}


@app.put("/api/settings/llm-models/{model_id}/default")
async def api_set_default_llm(model_id: str) -> dict:
    """Set a specific LLM model as the default."""
    set_default_llm_model(model_id)
    return {"status": "ok"}


@app.delete("/api/settings/llm-models/{model_id}")
async def api_delete_llm_model(model_id: str) -> dict:
    """Delete a non-default LLM model."""
    if not delete_llm_model(model_id):
        raise HTTPException(status_code=400, detail="无法删除默认模型或模型不存在")
    return {"status": "ok"}


# ====== Signals by date ======

@app.get("/api/signals/date/{date}")
async def api_signals_by_date(date: str) -> dict:
    """Return signals published on a specific date (YYYY-MM-DD)."""
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(status_code=422, detail="日期格式必须为 YYYY-MM-DD")
    signals = await asyncio.to_thread(get_signals_by_date, date)
    return {
        "date": date,
        "count": len(signals),
        "signals": [_signal_to_dict(s) for s in signals],
    }


# ====== Signal AI analysis ======

@app.get("/api/signals/{signal_id}/analysis")
async def api_get_signal_analysis(signal_id: str) -> dict:
    """Return cached AI analysis for a signal."""
    text = await asyncio.to_thread(get_signal_analysis, signal_id)
    if text is None:
        raise HTTPException(status_code=404, detail="该信号暂无 AI 解读")
    return {"signal_id": signal_id, "analysis": text}


@app.post("/api/signals/{signal_id}/analyze")
async def api_analyze_signal(signal_id: str, body: dict = Body(default={})) -> dict:
    """Generate AI analysis for a signal and cache it.

    Accepts optional signal metadata in the request body so the LLM
    has context even if the signal is not in the DB.
    """
    # Check cache first
    cached = await asyncio.to_thread(get_signal_analysis, signal_id)
    if cached:
        return {"signal_id": signal_id, "analysis": cached, "cached": True}

    title = (body.get("title") or "").strip()
    summary = (body.get("summary") or "").strip()
    source = (body.get("source") or "").strip()

    if not title:
        raise HTTPException(status_code=422, detail="请提供信号标题(title)")

    db_model = await asyncio.to_thread(get_default_llm_model)
    llm = _llm_client_kwargs(db_model)
    if not llm["api_key"] and not llm["auth_token"]:
        raise HTTPException(
            status_code=400,
            detail="尚未配置大模型，请先在「设置」页添加大模型（如 DeepSeek/Kimi）",
        )

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(
            api_key=llm["api_key"],
            auth_token=llm["auth_token"],
            base_url=llm["base_url"],
            timeout=30.0,
        )
        prompt = (
            "你是一位高盛情报分析助手。请用中文简要分析以下情报信号，"
            "帮助中国投资者理解其含义。\n\n"
            f"信号来源：{source}\n"
            f"标题：{title}\n"
            f"摘要：{summary}\n\n"
            "要求：\n"
            "1. 用中文翻译并概括信号核心内容（2-3句）\n"
            "2. 如有涉及评级/目标价，必须署名来源（如'高盛'），禁止以本系统名义给出买卖建议\n"
            "3. 用通俗语言解释对普通投资者可能意味着什么（1-2句）\n"
            "4. 总字数控制在200字以内"
        )
        resp = await client.messages.create(
            model=llm["model"],
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        for block in resp.content:
            if hasattr(block, "text"):
                text += block.text

        analysis = text.strip() or "AI 未生成有效解读"
        await asyncio.to_thread(save_signal_analysis, signal_id, analysis)
        return {"signal_id": signal_id, "analysis": analysis, "cached": False}
    except Exception as exc:
        logger.exception("AI analysis failed for signal %s", signal_id)
        raise HTTPException(status_code=500, detail=f"AI 分析失败：{exc}")


# ====== Daily report ======

@app.get("/api/daily-report/{date}")
async def api_get_daily_report(date: str) -> dict:
    """Return (or generate) a daily summary report for the given date."""
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(status_code=422, detail="日期格式必须为 YYYY-MM-DD")

    # Check cache
    cached = await asyncio.to_thread(get_daily_report, date)
    if cached:
        return {"date": date, "report": cached["report_text"], "signal_count": cached["signal_count"], "cached": True}

    signals = await asyncio.to_thread(get_signals_by_date, date)
    if not signals:
        return {"date": date, "report": "该日期暂无情报数据。", "signal_count": 0, "cached": False}

    # Build LLM prompt from signals
    signal_texts = []
    for s in signals[:20]:
        signal_texts.append(f"- [{s.source}] {s.title}: {s.summary[:150]}")
    combined = "\n".join(signal_texts)

    try:
        import anthropic
        from src.compliance import check_content

        db_model = await asyncio.to_thread(get_default_llm_model)
        llm = _llm_client_kwargs(db_model)
        if not llm["api_key"] and not llm["auth_token"]:
            return {
                "date": date,
                "report": "尚未配置大模型，请先在「设置」页添加大模型（如 DeepSeek/Kimi）后再生成日报。",
                "signal_count": len(signals),
                "cached": False,
                "error": "no_llm_configured",
            }

        client = anthropic.AsyncAnthropic(
            api_key=llm["api_key"],
            auth_token=llm["auth_token"],
            base_url=llm["base_url"],
            timeout=60.0,
        )
        prompt = (
            "你是一位资深的高盛情报分析师。请基于以下今日高盛相关情报信号，"
            "生成一份面向中国普通投资者的每日情报摘要。\n\n"
            f"今日日期：{date}\n"
            f"信号总数：{len(signals)}\n\n"
            "=== 今日情报信号 ===\n"
            f"{combined}\n\n"
            "请按以下三段式输出：\n\n"
            "## 今日高盛观点\n"
            "（概括高盛研究/分析师当日主要观点，2-4句话）\n\n"
            "## 今日披露变动\n"
            "（概括当日 SEC 文件/持仓变动等重要披露，2-3句话）\n\n"
            "## 一句话投资启示\n"
            "（用通俗语言写一句话，帮助普通投资者理解今日信息的意义）\n\n"
            "合规要求：所有评级/目标价必须署名来源（如'高盛'），禁止以本系统名义给出买卖建议。全部使用中文输出，控制在500字以内。"
        )
        resp = await client.messages.create(
            model=llm["model"],
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        for block in resp.content:
            if hasattr(block, "text"):
                text += block.text

        report = text.strip() or "AI 未生成有效日报"
        passed, violations = check_content(report)
        if not passed:
            logger.warning("Daily report compliance violations: %s", violations)

        await asyncio.to_thread(save_daily_report, date, report, len(signals))
        return {"date": date, "report": report, "signal_count": len(signals), "cached": False}
    except Exception as exc:
        logger.exception("Daily report generation failed for %s", date)
        fallback = f"## 今日情报概览\n\n今日共收录 {len(signals)} 条高盛相关情报信号。\n\nAI 日报生成失败：{exc}"
        return {"date": date, "report": fallback, "signal_count": len(signals), "cached": False, "error": str(exc)}


# ====== Quarter comparison ======

@app.get("/api/quarters/comparison")
async def api_quarters_comparison(current: str = "", previous: str = "") -> dict:
    """Return quarter-over-quarter comparison data."""
    from src.storage import get_holdings
    from src.config import GOLDMAN_CIK
    from src.quarter_compare import QuarterComparator

    if not current:
        raise HTTPException(status_code=422, detail="请提供 current 季度参数")

    current_holdings = await asyncio.to_thread(get_holdings, GOLDMAN_CIK, current)
    previous_holdings = await asyncio.to_thread(get_holdings, GOLDMAN_CIK, previous) if previous else []

    if previous_holdings:
        import pandas as pd
        cur_df = pd.DataFrame(current_holdings)
        prev_df = pd.DataFrame(previous_holdings)
        comparator = QuarterComparator()
        comparison = comparator.compare(cur_df, prev_df)
        return {
            "current": current,
            "previous": previous,
            "new_positions": comparison.new_positions.to_dict(orient="records") if not comparison.new_positions.empty else [],
            "sold_positions": comparison.sold_positions.to_dict(orient="records") if not comparison.sold_positions.empty else [],
            "increased_positions": comparison.increased_positions.to_dict(orient="records") if not comparison.increased_positions.empty else [],
            "decreased_positions": comparison.decreased_positions.to_dict(orient="records") if not comparison.decreased_positions.empty else [],
            "concentration_change": comparison.concentration_change,
        }
    return {
        "current": current,
        "previous": previous,
        "holdings_count": len(current_holdings),
        "message": "上一季度无持仓数据，无法对比",
    }
