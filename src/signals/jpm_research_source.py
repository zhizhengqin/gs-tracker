"""J.P. Morgan research-viewpoint signal source.

JPM's own sites (jpmorgan.com, am.jpmorgan.com) and Google News are
unreachable from CN networks, and eastmoney's research-report centre does
not redistribute JPM research. The realistic public channel for "摩根大通
观点" is Chinese financial media coverage — the same RSS feeds the news
sources poll.

So this source scans the configured RSS feeds and keeps ONLY
viewpoint-type JPM articles (上调/下调/预测/研报/评级...), i.e. JPM as the
*author* of analysis. Plain JPM mentions stay in the ``news_jpm`` source
(which skips viewpoint items), so the two never duplicate an article.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import feedparser
import httpx

from src.config import SIGNAL_LOOKBACK_DAYS, SEC_USER_AGENT
from src.signals.base import Signal, SignalStrength, smart_truncate
from src.signals.news_source import _JPM_RE, _JPM_VIEWPOINT_RE, clean_html_text

logger = logging.getLogger(__name__)


class JPMResearchSource:
    """Extract JPM-attributed viewpoint articles from configured RSS feeds."""

    source_name = "jpm_research"

    def __init__(self, rss_urls: Optional[List[str]] = None, max_items: int = 10) -> None:
        self.rss_urls = rss_urls or []
        self.max_items = max_items
        self.client = httpx.AsyncClient(
            timeout=20.0,
            headers={"User-Agent": SEC_USER_AGENT},
        )

    async def fetch(self, quarter: str = "") -> List[Signal]:
        signals, _ = await self.fetch_since()
        return signals

    async def fetch_since(
        self, watermark: Optional[str] = None
    ) -> Tuple[List[Signal], Optional[str]]:
        """Fetch recent JPM viewpoint articles. Never raises."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=SIGNAL_LOOKBACK_DAYS)
        signals: List[Signal] = []
        now = datetime.now(timezone.utc)
        new_watermark = now.strftime("%Y-%m-%d")

        for feed_url in self.rss_urls:
            try:
                resp = await self.client.get(feed_url)
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)
            except Exception as exc:
                logger.debug("JPM research: feed %s unavailable: %s", feed_url, exc)
                continue

            for entry in feed.entries[: self.max_items]:
                title = clean_html_text(getattr(entry, "title", ""))
                summary = clean_html_text(
                    getattr(entry, "summary", getattr(entry, "description", ""))
                )
                text_lower = (title + " " + summary).lower()

                is_jpm = any(rx.search(text_lower) for rx in _JPM_RE)
                is_viewpoint = any(rx.search(text_lower) for rx in _JPM_VIEWPOINT_RE)
                if not (is_jpm and is_viewpoint):
                    continue

                published_at = now
                tp = getattr(entry, "published_parsed", None)
                if tp:
                    try:
                        published_at = datetime(*tp[:6], tzinfo=timezone.utc)
                    except (TypeError, ValueError):
                        pass
                if published_at < cutoff:
                    continue

                signals.append(
                    Signal(
                        title=f"摩根大通研究: {title}",
                        source="jpm_research",
                        published_at=published_at,
                        summary=smart_truncate(summary) if summary else title,
                        companies=["JPM"],
                        strength=SignalStrength.HIGH,
                        url=getattr(entry, "link", "") or None,
                        institution_id="jpm",
                    )
                )

        signals.sort(key=lambda s: s.published_at, reverse=True)
        signals = signals[: self.max_items]
        logger.info("jpm_research: %d viewpoint articles", len(signals))
        return signals, new_watermark

    async def close(self) -> None:
        await self.client.aclose()
