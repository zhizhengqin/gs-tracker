"""Cross-institution AI analysis — GS vs JPM divergence read on one signal.

Behavior contract (aligned with src.signal_analysis):
- cached analysis        -> return cached, no LLM call
- signal not found       -> KeyError (web maps to 404)
- no counterpart signals -> notice text, no LLM call, nothing cached
- no LLM configured      -> CrossAnalysisError("no_llm_configured")
- LLM success            -> compliance check (violations only logged) -> cache -> return
- LLM failure            -> CrossAnalysisError, nothing cached (retryable)
"""
import asyncio
import logging
from datetime import timedelta
from typing import List, Optional

from src.llm_config import resolve_llm_config
from src.signals.base import Signal, institution_display
from src.signals.scorer import NON_INSTITUTION_IDS, SELF_COMPANY_TOKENS
from src.storage import (
    get_cross_analysis,
    get_default_llm_model,
    get_signal_by_id,
    get_signals_in_range,
    save_cross_analysis,
)

logger = logging.getLogger(__name__)

# Counterpart signals must fall within +-N Beijing days of the signal.
CROSS_WINDOW_DAYS = 7


class CrossAnalysisError(RuntimeError):
    """Raised when cross analysis cannot be generated; nothing is cached."""


def find_counterparts(signal: Signal, candidates: List[Signal]) -> List[Signal]:
    """Return candidates from *other real institutions* sharing a company.

    Aggregate ids ("all", "") cannot form a side of the comparison, and
    institution self-tokens (高盛/摩根大通...) are not third-party companies,
    so neither can create a counterpart relationship.
    """
    own_companies = {
        c.lower() for c in signal.companies if c.lower() not in SELF_COMPANY_TOKENS
    }
    if not own_companies:
        return []
    own_inst = getattr(signal, "institution_id", "gs")
    out: List[Signal] = []
    for cand in candidates:
        if cand.id == signal.id:
            continue
        cand_inst = getattr(cand, "institution_id", "gs")
        if cand_inst in NON_INSTITUTION_IDS or cand_inst == own_inst:
            continue
        cand_companies = {
            c.lower() for c in cand.companies if c.lower() not in SELF_COMPANY_TOKENS
        }
        if own_companies & cand_companies:
            out.append(cand)
    return out


def _beijing_date_str(signal: Signal) -> str:
    from datetime import timezone

    dt = signal.published_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _build_prompt(signal: Signal, counterparts: List[Signal]) -> str:
    from src.signals.news_source import clean_html_text

    own_inst = institution_display(getattr(signal, "institution_id", "gs"))
    shared = sorted({
        c for c in signal.companies if c.lower() not in SELF_COMPANY_TOKENS
    })
    companies_text = "、".join(shared[:5])

    own_text = (
        f"[{own_inst}] [{signal.source}] {clean_html_text(signal.title)}: "
        f"{clean_html_text(signal.summary)[:200]}"
    )
    other_lines = []
    other_insts = set()
    for c in counterparts[:10]:
        tag = institution_display(getattr(c, "institution_id", "gs"))
        other_insts.add(tag)
        other_lines.append(
            f"[{tag}] [{c.source}] {clean_html_text(c.title)}: "
            f"{clean_html_text(c.summary)[:200]}"
        )
    others_text = "\n".join(other_lines)
    others_list = "、".join(sorted(other_insts))

    return (
        "你是一位跨机构情报分析师。以下两家机构在近期同时覆盖了相同标的，"
        "请对比他们的观点，帮助中国 A 股投资者理解机构的共识与分歧。\n\n"
        f"共同涉及标的：{companies_text}\n\n"
        f"=== {own_inst}的情报 ===\n{own_text}\n\n"
        f"=== {others_list}的情报 ===\n{others_text}\n\n"
        "请按以下三段式输出：\n\n"
        "## 一致点\n"
        "（两家机构观点相同或方向一致的地方，1-3 句话）\n\n"
        "## 分歧点\n"
        "（观点差异、侧重不同或只有一方提及的角度；若无明显分歧请明说，1-3 句话）\n\n"
        "## 对 A 股的启示\n"
        "（共识或分歧对 A 股相关板块可能意味着什么，1-2 句话）\n\n"
        "合规要求：所有观点必须署名来源机构，禁止以本系统名义给出买卖建议，"
        "禁止使用'建议买入/卖出'等表述。全部使用中文输出，控制在 300 字以内。"
    )


async def generate_cross_analysis(signal_id: str) -> str:
    """Generate (LLM) and cache the cross-institution analysis for a signal.

    Raises KeyError when the signal does not exist, CrossAnalysisError on
    LLM/config failures — failures are never cached so retries stay possible.
    """
    cached = await asyncio.to_thread(get_cross_analysis, signal_id)
    if cached:
        return cached

    signal = await asyncio.to_thread(get_signal_by_id, signal_id)
    if signal is None:
        raise KeyError(signal_id)

    center = _beijing_date_str(signal)
    from datetime import date as _date

    y, m, d = (int(x) for x in center.split("-"))
    center_date = _date(y, m, d)
    start = (center_date - timedelta(days=CROSS_WINDOW_DAYS)).strftime("%Y-%m-%d")
    end = (center_date + timedelta(days=CROSS_WINDOW_DAYS)).strftime("%Y-%m-%d")
    candidates = await asyncio.to_thread(get_signals_in_range, start, end)
    counterparts = find_counterparts(signal, candidates)

    if not counterparts:
        return (
            f"该信号前后 {CROSS_WINDOW_DAYS} 天内暂未发现其他机构对相同标的的观点，"
            "暂时无法生成跨机构对比。当其他机构也覆盖该标的时再来试试。"
        )

    db_model = await asyncio.to_thread(get_default_llm_model)
    llm = resolve_llm_config(db_model)
    if not llm["api_key"] and not llm["auth_token"]:
        raise CrossAnalysisError("no_llm_configured")

    import anthropic
    from src.compliance import check_content

    client = anthropic.AsyncAnthropic(
        api_key=llm["api_key"],
        auth_token=llm["auth_token"],
        base_url=llm["base_url"],
        timeout=60.0,
    )
    prompt = _build_prompt(signal, counterparts)
    try:
        resp = await client.messages.create(
            model=llm["model"],
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        raise CrossAnalysisError(str(exc)) from exc

    text = ""
    for block in resp.content:
        if hasattr(block, "text"):
            text += block.text
    analysis = text.strip()
    if not analysis:
        raise CrossAnalysisError("empty_llm_response")

    passed, violations = check_content(analysis)
    if not passed:
        logger.warning("Cross analysis compliance violations: %s", violations)

    await asyncio.to_thread(save_cross_analysis, signal_id, analysis)
    return analysis
