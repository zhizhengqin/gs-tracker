"""J.P. Morgan research signal source.

Pulls JPM research articles from publicly available pages via RSS/feed.
For Phase 2 MVP, uses JPM's public insights RSS feed when available,
falling back to a simple page scraper.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import feedparser
import httpx

from src.signals.base import Signal, SignalStrength, smart_truncate

logger = logging.getLogger(__name__)

# JPM public feeds - these are known public RSS/Atom endpoints
JPM_FEEDS = [
    "https://www.jpmorgan.com/insights/rss",
    "https://privatebank.jpmorgan.com/insights/rss",
]

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_html(raw: str) -> str:
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    return _WS_RE.sub(" ", text).strip()


JPM_KEYWORDS = [
    "j.p. morgan", "jpmorgan", "jpm", "摩根大通", "摩根",
    "jamie dimon", "dimon",
]

JPM_VIEWPOINT_KEYWORDS = [
    "jpmorgan says", "jpmorgan expects", "jpmorgan upgrades",
    "jpmorgan downgrades", "jpmorgan forecast", "jpmorgan predicts",
    "jpmorgan warns", "jpmorgan sees", "jpmorgan strategists",
    "jpmorgan analysts", "jpmorgan economists",
    "摩根大通 研报", "摩根大通 观点", "摩根大通 预计",
    "摩根大通 预测", "摩根大通 上调", "摩根大通 下调",
    "摩根大通 维持", "摩根大通 警告",
]


class JPMResearchSource:
    """Fetch J.P. Morgan research articles from public feeds."""

    source_name = "jpm_research"

    def __init__(self, max_items: int = 10) -> None:
        self.max_items = max_items
        self.client = httpx.AsyncClient(
            timeout=20.0,
            headers={"User-Agent": "BridgeIQ/1.0 (research bot; contact@example.com)"},
        )

    async def fetch(self, quarter: str = "") -> List[Signal]:
        """Backward compat."""
        signals, _ = await self.fetch_since()
        return signals

    async def fetch_since(
        self, watermark: Optional[str] = None
    ) -> Tuple[List[Signal], Optional[str]]:
        """Fetch recent JPM research articles since *watermark*.

        Watermark is an ISO date string (YYYY-MM-DD).

        Never raises — returns empty list on failure.
        """
        if watermark is None:
            watermark = (
                datetime.now(timezone.utc) - timedelta(days=90)
            ).strftime("%Y-%m-%d")

        all_entries: list[tuple[str, str, str, str]] = []  # (title, date, summary, url)

        for feed_url in JPM_FEEDS:
            try:
                resp = await self.client.get(feed_url)
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.debug("JPM feed %s unavailable: %s", feed_url, exc)
                continue

            for entry in feed.entries[:self.max_items]:
                title = entry.get("title", "")
                published = entry.get("published", "") or entry.get("updated", "")
                summary = _clean_html(entry.get("summary", "") or entry.get("description", ""))
                link = entry.get("link", "")

                # Extract date
                date_str = ""
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(published)
                    date_str = dt.strftime("%Y-%m-%d")
                except Exception:
                    date_str = published[:10] if len(published) >= 10 else ""

                if title and date_str:
                    all_entries.append((title, date_str, summary, link))

        # Filter by watermark
        recent = [(t, d, s, u) for t, d, s, u in all_entries if d > watermark]
        recent.sort(key=lambda x: x[1], reverse=True)

        signals: list[Signal] = []
        new_watermark = watermark

        for title, date_str, summary, url in recent[:self.max_items]:
            try:
                published_at = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                published_at = datetime.now(timezone.utc)

            signals.append(
                Signal(
                    title=f"摩根大通研究: {title}",
                    source="jpm_research",
                    published_at=published_at,
                    summary=smart_truncate(summary) if summary else title,
                    companies=[],
                    strength=SignalStrength.HIGH,
                    url=url,
                    institution_id="jpm",
                )
            )

            if date_str > new_watermark:
                new_watermark = date_str

        logger.info("jpm_research: %d new articles", len(signals))
        return signals, new_watermark

    async def close(self) -> None:
        await self.client.aclose()
