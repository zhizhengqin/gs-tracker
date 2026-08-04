"""Quarterly AI insight report — A-share mapping, macro view, holdings changes.

Follows the same behavior contract as src.daily_report:
- cache hit           -> return cached row, no LLM call
- no holdings         -> notice text, no LLM call, nothing cached
- no LLM configured   -> notice + error="no_llm_configured", nothing cached
- LLM success         -> compliance check (violations only logged) -> cache -> return
- LLM failure         -> fallback text + error, nothing cached (retryable)

ensure_quarter_insight() adds process-wide dedupe so concurrent requests can
never double-generate one quarter.
"""
import asyncio
import logging
from typing import Optional

from src.config import GOLDMAN_CIK
from src.llm_config import resolve_llm_config
from src.storage import (
    get_default_llm_model,
    get_holdings,
    get_institution,
    get_quarter_insight,
    save_quarter_insight,
)

logger = logging.getLogger(__name__)

# (institution, quarter) -> in-flight generation Task (process-wide dedupe)
_insight_tasks: dict = {}


def _resolve_institution(institution: str) -> tuple[str, str]:
    # Resolve an institution id to (cik, Chinese display label); GS fallback.
    if institution == "gs":
        return GOLDMAN_CIK, "高盛"
    try:
        row = get_institution(institution)
    except Exception:
        row = None
    if row:
        return row["cik"] or GOLDMAN_CIK, row["display_name"]
    return GOLDMAN_CIK, institution


def _fmt_yi(value: float) -> str:
    """Format a dollar value in 100M-USD units for prompt readability."""
    return f"{value / 1e8:.1f}"


def _top_holdings_text(holdings: list[dict], limit: int = 15) -> str:
    """Aggregate raw 13F rows by issuer and return top-N lines for the prompt."""
    import pandas as pd

    df = pd.DataFrame(holdings)
    grouped = (
        df.groupby("name_of_issuer", as_index=False)["value"].sum()
        .sort_values("value", ascending=False)
        .head(limit)
    )
    return "\n".join(
        f"- {row.name_of_issuer}: {_fmt_yi(row.value)} 亿美元"
        for row in grouped.itertuples()
    )


def _comparison_text(current: list[dict], previous: list[dict]) -> str:
    """Summarize quarter-over-quarter changes for the prompt."""
    import pandas as pd

    from src.quarter_compare import QuarterComparator

    comparator = QuarterComparator()
    result = comparator.compare(
        pd.DataFrame(current), pd.DataFrame(previous), "", ""
    )

    def top_names(df, n: int = 5) -> str:
        if df.empty:
            return "无"
        top = df.sort_values("value", ascending=False).head(n)
        return "、".join(top["name_of_issuer"].tolist())

    direction = "上升（持仓更集中）" if result.concentration_change > 0 else "下降（持仓更分散）"
    return (
        f"新建仓 {len(result.new_positions)} 只（市值靠前：{top_names(result.new_positions)}）\n"
        f"清仓 {len(result.sold_positions)} 只（市值靠前：{top_names(result.sold_positions)}）\n"
        f"增持超20% {len(result.increased_positions)} 只（市值靠前：{top_names(result.increased_positions)}）\n"
        f"减持超20% {len(result.decreased_positions)} 只（市值靠前：{top_names(result.decreased_positions)}）\n"
        f"集中度变化：{result.concentration_change:+.4f}（{direction}）"
    )


async def generate_quarter_insight(
    quarter: str,
    previous: Optional[str] = None,
    force: bool = False,
    institution: str = "gs",
) -> dict:
    """Return (or generate) the AI insight report for `quarter` (YYYY-QN)."""
    if not force:
        cached = await asyncio.to_thread(get_quarter_insight, quarter, institution)
        if cached:
            return {"quarter": quarter, "report": cached["report_text"], "cached": True}

    cik, label = _resolve_institution(institution)
    holdings = await asyncio.to_thread(get_holdings, cik, quarter)
    if not holdings:
        return {"quarter": quarter, "report": "该季度暂无持仓数据，请先运行季度对账。", "cached": False}

    top_text = _top_holdings_text(holdings)

    comparison_text = "暂无上一季度数据，无法对比。"
    if previous:
        previous_holdings = await asyncio.to_thread(get_holdings, cik, previous)
        if previous_holdings:
            comparison_text = _comparison_text(holdings, previous_holdings)

    try:
        import anthropic
        from src.compliance import check_content

        db_model = await asyncio.to_thread(get_default_llm_model)
        llm = resolve_llm_config(db_model)
        if not llm["api_key"] and not llm["auth_token"]:
            return {
                "quarter": quarter,
                "report": "尚未配置大模型，请先在「设置」页添加大模型（如 DeepSeek/Kimi）后再生成季度洞察。",
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
            f"你是一位资深的机构情报分析师。请基于以下{label} 13F 持仓数据，"
            "生成一份面向中国普通投资者的季度洞察报告。\n\n"
            f"当前季度：{quarter}\n"
            f"对比季度：{previous or '无'}\n\n"
            "=== 当季前十五大重仓（按市值合计，单位：亿美元） ===\n"
            f"{top_text}\n\n"
            "=== 环比持仓变化 ===\n"
            f"{comparison_text}\n\n"
            "请按以下四段式输出：\n\n"
            "## 持仓变化解读\n"
            f"（本季{label}的调仓方向和可能动机，2-4 句话）\n\n"
            "## A股题材映射\n"
            "（这些美股持仓和调仓动向可能映射到 A 股的哪些题材板块，"
            "如 AI 算力、半导体、新能源车、消费电子等，说明映射逻辑，3-5 句话）\n\n"
            "## 宏观看点\n"
            f"（从持仓变化看{label}对宏观环境的判断，2-3 句话）\n\n"
            "## 风险提示\n"
            "（13F 数据滞后 45 天、仅披露多头等局限性，1-2 句话）\n\n"
            "合规要求：不得给出具体买卖建议，禁止使用'建议买入/卖出'等表述。"
            "全部使用中文输出，控制在 600 字以内。"
        )
        resp = await client.messages.create(
            model=llm["model"],
            max_tokens=4096,  # leave room for thinking-block models
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        for block in resp.content:
            if hasattr(block, "text"):
                text += block.text

        report = text.strip() or "AI 未生成有效季度洞察"
        passed, violations = check_content(report)
        if not passed:
            logger.warning("Quarter insight compliance violations: %s", violations)

        await asyncio.to_thread(save_quarter_insight, quarter, report, institution)
        return {"quarter": quarter, "report": report, "cached": False}
    except Exception as exc:
        logger.exception("Quarter insight generation failed for %s", quarter)
        fallback = (
            f"## 持仓概览\n\n{quarter} 季度持仓数据已就绪，但 AI 季度洞察生成失败。\n\n"
            f"错误信息：{exc}"
        )
        return {"quarter": quarter, "report": fallback, "cached": False, "error": str(exc)}


async def _generate_safe(
    quarter: str, previous: Optional[str], institution: str = "gs"
) -> None:
    """Task wrapper: generation failures must never crash callers."""
    try:
        await generate_quarter_insight(quarter, previous, institution=institution)
    except Exception:
        logger.exception("Quarter insight generation task failed for %s", quarter)


async def ensure_quarter_insight(
    quarter: str, previous: Optional[str] = None, institution: str = "gs"
) -> Optional[asyncio.Task]:
    """Idempotent generation with process-wide dedupe.

    Returns None when a cached insight already exists; otherwise returns the
    in-flight (or newly created) generation Task.
    """
    if await asyncio.to_thread(get_quarter_insight, quarter, institution):
        return None
    key = f"{institution}:{quarter}"
    task = _insight_tasks.get(key)
    if task is None or task.done():
        task = asyncio.create_task(_generate_safe(quarter, previous, institution))
        _insight_tasks[key] = task
    return task
