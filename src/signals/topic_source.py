"""Topic-type custom source: the LLM searches the web itself (gateway
web_search server tool) for a user-defined topic and organizes what it finds.

No deterministic fallback exists without the LLM, and there is no page to
hash — every run searches once. Cost control: a daily LLM-call budget
(ai_topic_count_*) plus a max_searches cap per run. Cross-day dedup relies on
recent_titles (same as webpage sources). AI failures degrade to
"no items + fetch_note" (yellow triage_note in the pipeline).
"""
import logging
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

from src.signals.ai_triage import CRITERIA, DailyBudget, parse_items_json
from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

MAX_ITEMS = 8
MAX_TOKENS = 8192  # web_search runs multiple rounds before answering
DEFAULT_DAILY_BUDGET = 10
DEFAULT_MAX_SEARCHES = 3


class TopicSource:
    """One search topic + gateway web_search → AI-organized signals."""

    def __init__(
        self,
        topic: str,
        source_name: str,
        filter_policy: str = "gs_only",
        llm_config: Optional[dict] = None,
        get_setting: Callable[[str, str], str] = lambda k, d="": d,
        set_setting: Callable[[str, str], None] = lambda k, v: None,
        daily_budget: int = DEFAULT_DAILY_BUDGET,
        recent_titles: Optional[Callable[[str], set]] = None,
        max_searches: int = DEFAULT_MAX_SEARCHES,
    ) -> None:
        self.topic = topic
        self.source_name = source_name
        self.filter_policy = filter_policy
        self.llm_config = llm_config or {}
        self.budget = DailyBudget("ai_topic_count", daily_budget, get_setting, set_setting)
        self._recent_titles = recent_titles or (lambda name: set())
        self.max_searches = max_searches
        self.fetch_note = ""  # AI degradation reason; read by the pipeline
        self._llm_client = None  # lazy anthropic.AsyncAnthropic

    async def close(self) -> None:
        """No HTTP client of our own — protocol no-op."""

    async def fetch(self, quarter: str) -> List[Signal]:
        signals, _ = await self.fetch_since(None)
        return signals

    async def fetch_since(
        self, watermark: Optional[str] = None
    ) -> Tuple[List[Signal], Optional[str]]:
        self.fetch_note = ""
        items = await self._search_items()
        if items is None:
            return [], None  # degraded (fetch_note set)
        seen = self._recent_titles(self.source_name)
        items = [it for it in items if it["title"] not in seen]
        if not items:
            return [], None

        strength = (
            SignalStrength.MEDIUM if self.filter_policy == "gs_only"
            else SignalStrength.LOW
        )
        now = datetime.now(timezone.utc)
        signals = [
            Signal(
                title=it["title"],
                source=self.source_name,
                published_at=now,
                summary=it["summary"],
                companies=[],
                strength=strength,
                url=it["url"],
            )
            for it in items
        ]
        return signals, None

    def _build_prompt(self) -> str:
        criteria = CRITERIA.get(self.filter_policy, CRITERIA["gs_only"])
        return (
            "你是投资情报搜集助手。用户是中国 A 股个人投资者，关注高盛观点以判断市场趋势。\n\n"
            f"搜索主题：{self.topic}\n"
            f"筛选标准：{criteria}\n\n"
            f"请用 web_search 搜索（最多 {self.max_searches} 次），整理出最新、最相关的条目。\n"
            '最后只输出 JSON，不要输出其他内容：{"items": [{"title": "条目标题", "summary": "150字内摘要", "url": "来源链接"}]}，'
            f"最多 {MAX_ITEMS} 条；没有符合要求的内容则输出空数组。"
        )

    def _get_llm_client(self):
        if self._llm_client is None:
            import anthropic

            self._llm_client = anthropic.AsyncAnthropic(
                api_key=self.llm_config.get("api_key"),
                auth_token=self.llm_config.get("auth_token"),
                base_url=self.llm_config.get("base_url"),
                timeout=120.0,
            )
        return self._llm_client

    async def _search_items(self) -> Optional[list]:
        """LLM web_search extraction; None means degraded (fetch_note explains)."""
        if not (self.llm_config.get("api_key") or self.llm_config.get("auth_token")):
            self.fetch_note = "未配置大模型，主题搜索源无法工作"
            return None
        if self.budget.exhausted():
            self.fetch_note = "主题搜索 AI 预算已用完，明日自动恢复"
            return None
        try:
            resp = await self._get_llm_client().messages.create(
                model=self.llm_config["model"],
                max_tokens=MAX_TOKENS,
                tools=[{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": self.max_searches,
                }],
                messages=[{"role": "user", "content": self._build_prompt()}],
            )
            self.budget.increment()
        except Exception as exc:
            logger.warning("Topic search failed for %s: %s", self.source_name, exc)
            self.fetch_note = "AI 搜索失败，本次跳过该主题"
            return None
        # Gateways interleave search-process text blocks (query logs, partial
        # fragments) with the final answer. Parse each text block separately,
        # last-to-first, and take the first one that yields valid items.
        blocks = [b.text for b in resp.content if hasattr(b, "text")]
        items = None
        for block_text in reversed(blocks):
            items = parse_items_json(block_text, MAX_ITEMS)
            if items is not None:
                break
        if items is None:
            logger.warning(
                "Topic search unparseable for %s: %.200s",
                self.source_name, blocks[-1] if blocks else "",
            )
            self.fetch_note = "AI 返回格式异常，本次跳过该主题"
        return items
