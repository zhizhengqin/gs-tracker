"""Daily intelligence summary report — single source of truth for generation.

Extracted from the /api/daily-report/{date} endpoint so the web layer and the
daily-intel pipeline share one implementation. Behavior contract (unchanged
from the legacy endpoint):
- cache hit           -> return cached row, no LLM call
- no signals that day -> notice text, no LLM call, nothing cached
- no LLM configured   -> notice + error="no_llm_configured", nothing cached
- LLM success         -> compliance check (violations only logged) -> cache -> return
- LLM failure         -> fallback text + error, nothing cached (retryable)

ensure_daily_report() adds process-wide dedupe so the pipeline tail, the
endpoint fallback, and the scheduler can never double-generate one date.
"""
import asyncio
import logging
from typing import Optional

from src.llm_config import resolve_llm_config
from src.storage import (
    get_daily_report,
    get_default_llm_model,
    get_signals_by_date,
    save_daily_report,
)

logger = logging.getLogger(__name__)

# date -> in-flight generation Task (process-wide dedupe)
_report_tasks: dict = {}


async def generate_daily_report(date: str) -> dict:
    """Return (or generate) the daily summary report for `date` (YYYY-MM-DD)."""
    cached = await asyncio.to_thread(get_daily_report, date)
    if cached:
        return {"date": date, "report": cached["report_text"], "signal_count": cached["signal_count"], "cached": True}

    signals = await asyncio.to_thread(get_signals_by_date, date)
    if not signals:
        return {"date": date, "report": "该日期暂无情报数据。", "signal_count": 0, "cached": False}

    # Build LLM prompt from signals (HTML-stripped — legacy rows may carry tags)
    from src.signals.news_source import clean_html_text

    signal_texts = []
    for s in signals[:20]:
        signal_texts.append(f"- [{s.source}] {clean_html_text(s.title)}: {clean_html_text(s.summary)[:150]}")
    combined = "\n".join(signal_texts)

    try:
        import anthropic
        from src.compliance import check_content

        db_model = await asyncio.to_thread(get_default_llm_model)
        llm = resolve_llm_config(db_model)
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
            max_tokens=2048,  # leave room for thinking-block models
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


async def _generate_safe(date: str) -> None:
    """Task wrapper: generation failures must never crash callers."""
    try:
        await generate_daily_report(date)
    except Exception:
        logger.exception("Daily report generation task failed for %s", date)


async def ensure_daily_report(date: str) -> Optional[asyncio.Task]:
    """Idempotent fire-and-forget generation.

    Returns None when a cached report already exists; otherwise returns the
    in-flight (or newly created) generation Task. Callers that only want
    fire-and-forget ignore the return; callers that must wait (scheduler/CLI)
    await it.
    """
    if await asyncio.to_thread(get_daily_report, date):
        return None
    task = _report_tasks.get(date)
    if task is None or task.done():
        task = asyncio.create_task(_generate_safe(date))
        _report_tasks[date] = task
    return task
