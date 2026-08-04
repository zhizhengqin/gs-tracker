"""AI-based pre-ingest triage for news-type signal sources.

Batches candidate items through the configured LLM to decide keep/drop.
Any failure (no config, LLM error, unparseable output, budget exhausted)
falls back deterministically to keeping everything — callers pre-filter
gs_only sources by keywords at fetch time, so 'keep all' IS the fallback.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from src.signals.base import smart_truncate

logger = logging.getLogger(__name__)

BATCH_SIZE = 20
DEFAULT_DAILY_BUDGET = 20

CRITERIA = {
    "gs_only": (
        "保留与高盛（Goldman Sachs）相关且对理解市场有帮助的内容：高盛的观点、研报、"
        "评级、目标价、人事与业务动态，或引用高盛观点分析市场的报道。"
        "仅当高盛被一笔带过、内容主体与高盛无关时才丢弃。"
    ),
    "jpm_only": (
        "保留与摩根大通（J.P. Morgan / JPMorgan）相关且对理解市场有帮助的内容：摩根大通的观点、研报、"
        "评级、目标价、人事与业务动态，或引用摩根大通观点分析市场的报道。"
        "仅当摩根大通被一笔带过、内容主体与摩根大通无关时才丢弃。"
    ),
    "all": (
        "保留对 A 股投资者有参考价值的内容：市场趋势、宏观政策、机构观点、"
        "重大公司动态。丢弃广告、软文、推广、与财经无关的花边。拿不准的可以保留。"
    ),
}


class DailyBudget:
    """Daily LLM call counter persisted via settings; resets each UTC day."""

    def __init__(
        self,
        key_prefix: str,
        limit: int,
        get_setting: Callable[[str, str], str],
        set_setting: Callable[[str, str], None],
    ) -> None:
        self.key_prefix = key_prefix
        self.limit = limit
        self._get_setting = get_setting
        self._set_setting = set_setting

    def _key(self) -> str:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{self.key_prefix}_{day}"

    def used(self) -> int:
        try:
            return int(self._get_setting(self._key(), "0") or "0")
        except ValueError:
            return 0

    def exhausted(self) -> bool:
        return self.used() >= self.limit

    def increment(self) -> None:
        self._set_setting(self._key(), str(self.used() + 1))


@dataclass
class TriageResult:
    kept_indices: list = field(default_factory=list)
    fallback_used: bool = False
    note: str = ""


def _parse_keep(text: str, batch_len: int) -> Optional[list]:
    """Extract 1-based keep indices from model output; None if unparseable.

    The keep array is extracted directly instead of parsing the whole JSON
    object: models occasionally blow the token budget mid-"reason", leaving a
    truncated tail that is not valid JSON — the array itself is still sound.
    A truncated array (no closing "]") returns None → caller falls back.
    """
    match = re.search(r'"keep"\s*:\s*\[([^\]]*)\]', text)
    if not match:
        return None
    try:
        indices = json.loads(f"[{match.group(1)}]")
    except json.JSONDecodeError:
        return None
    if not isinstance(indices, list):
        return None
    return [i - 1 for i in indices if isinstance(i, int) and 1 <= i <= batch_len]


class AiTriage:
    """Batch LLM screening with daily call budget and deterministic fallback."""

    def __init__(
        self,
        llm_config: dict,
        get_setting: Callable[[str, str], str],
        set_setting: Callable[[str, str], None],
        daily_budget: int = DEFAULT_DAILY_BUDGET,
    ) -> None:
        self.llm_config = llm_config
        self.budget = DailyBudget(
            key_prefix="ai_triage_count",
            limit=daily_budget,
            get_setting=get_setting,
            set_setting=set_setting,
        )

    def _build_prompt(self, batch: list, source_label: str, filter_policy: str) -> str:
        criteria = CRITERIA.get(filter_policy, CRITERIA["gs_only"])
        numbered = "\n".join(
            f"{i + 1}. {it['title']} — {it['summary'][:150]}"
            for i, it in enumerate(batch)
        )
        return (
            "你是投资情报筛选助手。用户是中国 A 股个人投资者，关注高盛观点以判断市场趋势。\n\n"
            f"信息源：{source_label}\n"
            f"筛选标准：{criteria}\n\n"
            f"候选内容（编号. 标题 — 摘要）：\n{numbered}\n\n"
            '只输出 JSON，不要输出其他内容：{"keep": [要保留的编号], "reason": "不超过20字"}'
        )

    async def triage(self, items: list, source_label: str, filter_policy: str) -> TriageResult:
        if not items:
            return TriageResult(kept_indices=[])
        if not (self.llm_config.get("api_key") or self.llm_config.get("auth_token")):
            return TriageResult(
                kept_indices=list(range(len(items))),
                fallback_used=True,
                note="未配置大模型，已跳过 AI 预筛",
            )

        import anthropic

        client = anthropic.AsyncAnthropic(
            api_key=self.llm_config.get("api_key"),
            auth_token=self.llm_config.get("auth_token"),
            base_url=self.llm_config.get("base_url"),
            timeout=30.0,
        )

        kept: list = []
        fallback_note = ""
        for start in range(0, len(items), BATCH_SIZE):
            if self.budget.exhausted():
                kept.extend(range(start, len(items)))
                fallback_note = "AI 预算已用完，其余条目按基础规则保留"
                break
            batch = items[start:start + BATCH_SIZE]
            prompt = self._build_prompt(batch, source_label, filter_policy)
            try:
                resp = await client.messages.create(
                    model=self.llm_config["model"],
                    # Thinking models burn output tokens on a reasoning block
                    # before the JSON — 512 was exhausted by it, leaving "".
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )
                self.budget.increment()
            except Exception as exc:
                logger.warning("AI triage call failed: %s", exc)
                kept.extend(range(start, len(items)))
                fallback_note = "AI 预筛不可用，已用基础过滤"
                break
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            batch_keep = _parse_keep(text, len(batch))
            if batch_keep is None:
                logger.warning("AI triage returned unparseable output: %.200s", text)
                kept.extend(range(start, len(items)))
                fallback_note = "AI 返回格式异常，已用基础过滤"
                break
            kept.extend(start + i for i in batch_keep)

        return TriageResult(
            kept_indices=sorted(kept),
            fallback_used=bool(fallback_note),
            note=fallback_note,
        )


def parse_items_json(text: str, max_items: int) -> Optional[list]:
    """Extract an {"items": [...]} array from model output; None if unparseable.

    Shared by webpage/topic sources. Each item becomes {title, summary, url} —
    url is kept only when it is an http(s) link, else None.
    """
    match = re.search(r'"items"\s*:\s*(\[.*\])', text, re.S)
    if not match:
        return None
    try:
        items = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(items, list):
        return None
    result = []
    for it in items[:max_items]:
        if isinstance(it, dict) and it.get("title"):
            url = str(it.get("url") or "").strip()
            result.append({
                "title": str(it["title"]).strip()[:120],
                "summary": smart_truncate(str(it.get("summary") or "")),
                "url": url if url.startswith(("http://", "https://")) else None,
            })
    return result
