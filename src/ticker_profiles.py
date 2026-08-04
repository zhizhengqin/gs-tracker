"""AI-generated basic profiles for a quarter's top holdings (sector/themes/intro).

Follows the same behavior contract as src.quarter_insight:
- cache hit           -> return cached profiles, no LLM call
- no holdings         -> empty profiles + message, no LLM call, nothing cached
- no LLM configured   -> base profiles (name/value/pct only) + error, nothing cached
- LLM success         -> merged profiles -> cache -> return
- LLM failure         -> base profiles + error, nothing cached (retryable)
"""
import asyncio
import json
import logging
from typing import Optional

from src.config import GOLDMAN_CIK
from src.llm_config import resolve_llm_config
from src.storage import (
    get_default_llm_model,
    get_holdings,
    get_institution,
    get_ticker_profiles,
    save_ticker_profiles,
)

logger = logging.getLogger(__name__)

TOP_N = 10


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


def aggregate_top_holdings(holdings: list[dict], limit: int = TOP_N) -> list[dict]:
    """Aggregate raw 13F rows by issuer; return top-N with portfolio percentage."""
    import pandas as pd

    df = pd.DataFrame(holdings)
    grouped = (
        df.groupby("name_of_issuer", as_index=False)["value"].sum()
        .sort_values("value", ascending=False)
        .head(limit)
    )
    total = float(df["value"].sum()) or 1.0
    return [
        {
            "ticker": row.name_of_issuer,
            "value": float(row.value),
            "pct": round(float(row.value) / total * 100, 2),
            "cn_name": "",
            "sector": "",
            "themes": [],
            "intro": "",
        }
        for row in grouped.itertuples()
    ]


def _extract_json_array(text: str) -> Optional[list]:
    """Pull the first JSON array out of an LLM reply (tolerates code fences)."""
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, list) else None


def _merge_profiles(base: list[dict], ai_items: list) -> list[dict]:
    """Overlay AI-generated fields onto base profiles, matched by ticker name."""
    by_ticker = {
        str(item.get("ticker", "")).strip(): item
        for item in ai_items
        if isinstance(item, dict)
    }
    merged = []
    for profile in base:
        ai = by_ticker.get(profile["ticker"])
        if ai:
            themes = ai.get("themes")
            if isinstance(themes, str):
                themes = [t.strip() for t in themes.replace("，", ",").split(",") if t.strip()]
            profile = {
                **profile,
                "cn_name": str(ai.get("cn_name", "") or ""),
                "sector": str(ai.get("sector", "") or ""),
                "themes": themes if isinstance(themes, list) else [],
                "intro": str(ai.get("intro", "") or ""),
            }
        merged.append(profile)
    return merged


async def generate_ticker_profiles(
    quarter: str, force: bool = False, institution: str = "gs"
) -> dict:
    """Return (or generate) AI profiles for the quarter's top-10 holdings."""
    if not force:
        cached = await asyncio.to_thread(get_ticker_profiles, quarter, institution)
        if cached:
            return {
                "quarter": quarter,
                "profiles": json.loads(cached["profiles_json"]),
                "cached": True,
            }

    cik, label = _resolve_institution(institution)
    holdings = await asyncio.to_thread(get_holdings, cik, quarter)
    if not holdings:
        return {
            "quarter": quarter,
            "profiles": [],
            "message": "该季度暂无持仓数据，请先运行季度对账。",
            "cached": False,
        }

    base = aggregate_top_holdings(holdings)

    try:
        import anthropic

        db_model = await asyncio.to_thread(get_default_llm_model)
        llm = resolve_llm_config(db_model)
        if not llm["api_key"] and not llm["auth_token"]:
            return {
                "quarter": quarter,
                "profiles": base,
                "cached": False,
                "error": "no_llm_configured",
            }

        tickers_text = "\n".join(f"- {p['ticker']}" for p in base)
        client = anthropic.AsyncAnthropic(
            api_key=llm["api_key"],
            auth_token=llm["auth_token"],
            base_url=llm["base_url"],
            timeout=60.0,
        )
        prompt = (
            f"你是一位资深美股分析师。下面是{label} 13F 披露的前十大重仓标的"
            "（13F 原始名称，可能是公司、ETF 或指数信托）。\n\n"
            f"{tickers_text}\n\n"
            "请为每个标的生成一段最基本的中文档案，并严格按 JSON 数组输出，"
            "每个对象包含以下字段：\n"
            '- "ticker": 与输入完全一致的原始名称\n'
            '- "cn_name": 中文常用名（如 英伟达、苹果、标普500ETF）\n'
            '- "sector": 所属板块（如 半导体、消费电子、宽基指数ETF）\n'
            '- "themes": 相关题材数组（如 ["AI算力","芯片"]），1-3 个\n'
            '- "intro": 基本情况简介，1-2 句话，说明主营业务或跟踪标的\n\n'
            "要求：只输出 JSON 数组本身，不要输出任何额外文字或代码块标记；"
            "顺序与输入一致；全部使用中文。"
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

        ai_items = _extract_json_array(text)
        if ai_items is None:
            logger.warning("Ticker profiles: LLM returned unparseable JSON for %s", quarter)
            return {
                "quarter": quarter,
                "profiles": base,
                "cached": False,
                "error": "llm_parse_failed",
            }

        profiles = _merge_profiles(base, ai_items)
        await asyncio.to_thread(
            save_ticker_profiles, quarter, json.dumps(profiles, ensure_ascii=False), institution
        )
        return {"quarter": quarter, "profiles": profiles, "cached": False}
    except Exception as exc:
        logger.exception("Ticker profiles generation failed for %s", quarter)
        return {"quarter": quarter, "profiles": base, "cached": False, "error": str(exc)}
