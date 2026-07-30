"""Per-signal AI analysis — single source of truth for generation.

Shared by the web endpoint (manual "AI 解读" click) and the daily-intel
pipeline (auto-generation for HIGH-strength signals). Behavior contract:
- cached valid analysis   -> no LLM call (ensure returns None)
- cached failure sentinel -> treated as a miss, regenerated
- LLM empty completion    -> retried once, then AnalysisError (never cached)
- no LLM configured       -> AnalysisError("no_llm_configured")
- generation failures are NEVER cached, so the next attempt retries

ensure_signal_analysis() adds process-wide dedupe so the pipeline's
auto-generation and a user's manual click can never double-generate one
signal. auto_analyze_high_signals() is the pipeline entry point.
"""
import asyncio
import logging
from typing import Optional

from src.llm_config import resolve_llm_config
from src.signals.base import SignalStrength
from src.storage import (
    get_default_llm_model,
    get_signal_analysis,
    save_signal_analysis,
)

logger = logging.getLogger(__name__)

# Marker written by older versions when the LLM returned no usable text;
# such rows are treated as cache misses so they get regenerated.
ANALYSIS_FAILURE_SENTINEL = "AI 未生成有效解读"

# signal_id -> in-flight generation Task (process-wide dedupe)
_analysis_tasks: dict = {}


class AnalysisError(RuntimeError):
    """Raised when analysis generation fails; nothing is cached."""


async def generate_signal_analysis(
    signal_id: str, title: str, summary: str, source: str
) -> str:
    """Generate (LLM) and cache the AI analysis for one signal.

    Raises AnalysisError on failure — callers decide how to surface it;
    failures are deliberately not cached so retries stay possible.
    """
    from src.signals.news_source import clean_html_text

    title = clean_html_text(title)
    summary = clean_html_text(summary)

    db_model = await asyncio.to_thread(get_default_llm_model)
    llm = resolve_llm_config(db_model)
    if not llm["api_key"] and not llm["auth_token"]:
        raise AnalysisError("no_llm_configured")

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

    async def _complete() -> str:
        resp = await client.messages.create(
            model=llm["model"],
            # Headroom for gateways whose models emit a thinking block first —
            # an 800 cap was exhausted by reasoning, yielding empty text.
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if hasattr(b, "text"))

    text = await _complete()
    if not text.strip():
        # Transient empty completions happen with some gateways — retry once
        text = await _complete()
    if not text.strip():
        raise AnalysisError("empty_llm_response")

    analysis = text.strip()
    await asyncio.to_thread(save_signal_analysis, signal_id, analysis)
    return analysis


async def ensure_signal_analysis(
    signal_id: str, title: str, summary: str, source: str
) -> Optional[asyncio.Task]:
    """Idempotent generation with process-wide dedupe.

    Returns None when a valid cached analysis already exists; otherwise
    returns the in-flight (or newly created) generation Task. The Task
    resolves to the analysis text and raises on failure — callers must
    await it (or gather with return_exceptions) to retrieve exceptions.
    """
    task = _analysis_tasks.get(signal_id)
    if task is not None and not task.done():
        return task
    cached = await asyncio.to_thread(get_signal_analysis, signal_id)
    if cached and cached != ANALYSIS_FAILURE_SENTINEL:
        return None
    task = asyncio.create_task(
        generate_signal_analysis(signal_id, title, summary, source)
    )
    _analysis_tasks[signal_id] = task
    return task


async def auto_analyze_high_signals(signals: list) -> int:
    """Generate AI analysis for every HIGH-strength signal; skip the rest.

    Returns the number of signals attempted. Individual failures are logged
    and swallowed so one bad signal never blocks the pipeline (the next
    run or a manual click retries).
    """
    tasks: dict[str, asyncio.Task] = {}
    for sig in signals:
        if sig.strength != SignalStrength.HIGH:
            continue
        task = await ensure_signal_analysis(sig.id, sig.title, sig.summary, sig.source)
        if task is not None:
            tasks[sig.id] = task
    if not tasks:
        return 0
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for sig_id, result in zip(tasks, results):
        if isinstance(result, Exception):
            logger.warning("Auto analysis failed for signal %s: %s", sig_id, result)
    return len(tasks)
