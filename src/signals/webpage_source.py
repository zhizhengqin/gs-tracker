"""Webpage-type custom source: fetch a page, extract its text, and let the
LLM pull out intelligence items guided by the user's instruction.

There is NO deterministic fallback without the LLM (the items originate from
the extraction itself), so AI failures degrade to "no items + fetch_note" —
the pipeline surfaces fetch_note as a yellow triage_note SSE event. HTTP
fetch errors raise, so the pipeline marks the source red (fault isolation
keeps other sources running).

Watermark = SHA1 of the extracted page text: an unchanged page short-circuits
before any LLM call. A changed page with no matching items still advances the
watermark (nothing to retry). AI degradation does NOT advance it.
"""
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

import httpx

from src.signals.ai_triage import CRITERIA, DailyBudget, parse_items_json
from src.signals.base import Signal, SignalStrength
from src.signals.news_source import clean_html_text

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 6000
MAX_ITEMS = 10
DEFAULT_DAILY_BUDGET = 10

_UA = {"User-Agent": "GS-Tracker/1.0 (market research; contact: admin@gs-tracker.local)"}
_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)


def extract_text(html: str) -> str:
    """Strip script/style/noscript blocks, then tags; cap the length."""
    no_scripts = _SCRIPT_RE.sub(" ", html)
    return clean_html_text(no_scripts)[:MAX_TEXT_CHARS]


class WebpageSource:
    """One webpage + one user instruction → AI-extracted signals."""

    def __init__(
        self,
        url: str,
        instruction: str,
        source_name: str,
        filter_policy: str = "gs_only",
        llm_config: Optional[dict] = None,
        get_setting: Callable[[str, str], str] = lambda k, d="": d,
        set_setting: Callable[[str, str], None] = lambda k, v: None,
        daily_budget: int = DEFAULT_DAILY_BUDGET,
        recent_titles: Optional[Callable[[str], set]] = None,
    ) -> None:
        self.url = url
        self.instruction = instruction
        self.source_name = source_name
        self.filter_policy = filter_policy
        self.llm_config = llm_config or {}
        self.budget = DailyBudget("ai_webpage_count", daily_budget, get_setting, set_setting)
        self._recent_titles = recent_titles or (lambda name: set())
        self.fetch_note = ""  # AI degradation reason; read by the pipeline
        self._client = httpx.AsyncClient(timeout=30.0, headers=_UA, follow_redirects=True)
        self._llm_client = None  # lazy anthropic.AsyncAnthropic

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch(self, quarter: str) -> List[Signal]:
        signals, _ = await self.fetch_since(None)
        return signals

    async def fetch_since(
        self, watermark: Optional[str] = None
    ) -> Tuple[List[Signal], Optional[str]]:
        self.fetch_note = ""
        resp = await self._client.get(self.url)
        resp.raise_for_status()
        text = extract_text(resp.text)
        if not text:
            return [], None
        page_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()
        if page_hash == watermark:
            return [], None  # page unchanged since last run

        items = await self._extract_items(text)
        if items is None:
            return [], None  # AI degraded (fetch_note set); retry next run
        seen = self._recent_titles(self.source_name)
        items = [it for it in items if it["title"] not in seen]
        if not items:
            return [], page_hash  # changed, but nothing (new) to keep

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
                url=self.url,
            )
            for it in items
        ]
        return signals, page_hash

    def _build_prompt(self, text: str) -> str:
        criteria = CRITERIA.get(self.filter_policy, CRITERIA["gs_only"])
        return (
            "你是投资情报提取助手。用户是中国 A 股个人投资者，关注高盛观点以判断市场趋势。\n\n"
            f"网页地址：{self.url}\n"
            f"用户提取要求：{self.instruction}\n"
            f"筛选标准：{criteria}\n\n"
            f"网页正文（已截断）：\n{text}\n\n"
            '只输出 JSON，不要输出其他内容：{"items": [{"title": "要点标题", "summary": "150字内摘要"}]}，'
            f"最多 {MAX_ITEMS} 条；没有符合要求的内容则输出空数组。"
        )

    def _get_llm_client(self):
        if self._llm_client is None:
            import anthropic

            self._llm_client = anthropic.AsyncAnthropic(
                api_key=self.llm_config.get("api_key"),
                auth_token=self.llm_config.get("auth_token"),
                base_url=self.llm_config.get("base_url"),
                timeout=60.0,
            )
        return self._llm_client

    async def _extract_items(self, text: str) -> Optional[list]:
        """LLM extraction; None means degraded (fetch_note explains)."""
        if not (self.llm_config.get("api_key") or self.llm_config.get("auth_token")):
            self.fetch_note = "未配置大模型，网页型源无法提取内容"
            return None
        if self.budget.exhausted():
            self.fetch_note = "网页提取 AI 预算已用完，明日自动恢复"
            return None
        try:
            resp = await self._get_llm_client().messages.create(
                model=self.llm_config["model"],
                max_tokens=2048,  # thinking-block models burn budget on reasoning first
                messages=[{"role": "user", "content": self._build_prompt(text)}],
            )
            self.budget.increment()
        except Exception as exc:
            logger.warning("Webpage extraction failed for %s: %s", self.source_name, exc)
            self.fetch_note = "AI 提取失败，本次跳过该网页"
            return None
        out = "".join(b.text for b in resp.content if hasattr(b, "text"))
        items = parse_items_json(out, MAX_ITEMS)
        if items is None:
            logger.warning("Webpage extraction unparseable for %s: %.200s", self.source_name, out)
            self.fetch_note = "AI 返回格式异常，本次跳过该网页"
        return items
