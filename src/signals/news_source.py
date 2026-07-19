"""RSS news signal source."""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import feedparser
import httpx

from src.config import SIGNAL_LOOKBACK_DAYS, SEC_USER_AGENT
from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

GS_KEYWORDS = [
    "goldman sachs", "goldman", "高盛",
]
HOLDING_KEYWORDS = [
    "apple", "aapl", "microsoft", "msft", "nvidia", "nvda",
    "amazon", "amzn", "meta", "googl", "google", "tesla", "tsla",
    "berkshire", "brk", "jpmorgan", "jpm", "visa", "v",
    "unitedhealth", "unh", "mastercard", "ma",
]


QUARTER_START_MONTHS = {"Q1": 1, "Q2": 4, "Q3": 7, "Q4": 10}


def _quarter_start(quarter: str) -> datetime:
    """Return the first day of the quarter as a UTC datetime."""
    year_str, q = quarter.split("-")
    year = int(year_str)
    month = QUARTER_START_MONTHS.get(q, 1)
    return datetime(year, month, 1, tzinfo=timezone.utc)


class NewsSource:
    """Fetch news signals from RSS feeds."""

    source_name = "news"

    def __init__(self, rss_urls: Optional[List[str]] = None) -> None:
        self.rss_urls = rss_urls or []
        self.client = httpx.AsyncClient(
            timeout=20.0,
            headers={"User-Agent": SEC_USER_AGENT},
        )

    async def fetch(self, quarter: str) -> List[Signal]:
        """Fetch RSS items and convert to Signals. Never raises — returns empty list on failure."""
        lookback_cutoff = datetime.now(timezone.utc) - timedelta(days=SIGNAL_LOOKBACK_DAYS)
        quarter_cutoff = _quarter_start(quarter)
        # Use the later of the two cutoffs to avoid pulling data before the quarter
        cutoff = max(lookback_cutoff, quarter_cutoff)
        all_items: list = []

        for url in self.rss_urls:
            try:
                response = await self.client.get(url)
                response.raise_for_status()
                feed = feedparser.parse(response.text)
                for entry in feed.entries:
                    all_items.append({
                        "title": getattr(entry, "title", ""),
                        "link": getattr(entry, "link", ""),
                        "summary": getattr(entry, "summary", getattr(entry, "description", "")),
                        "published_parsed": getattr(entry, "published_parsed", None),
                    })
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.warning("Failed to fetch RSS feed %s: %s", url, exc)
                continue
            except Exception as exc:
                logger.warning("Failed to parse RSS feed %s: %s", url, exc)
                continue

        signals: List[Signal] = []
        for item in all_items:
            title = item["title"]
            summary_text = item.get("summary", "")
            text_lower = (title + " " + summary_text).lower()

            has_gs = any(kw in text_lower for kw in GS_KEYWORDS)
            has_holding = any(kw in text_lower for kw in HOLDING_KEYWORDS)
            if not (has_gs or has_holding):
                continue

            published_at = datetime.now(timezone.utc)
            if item.get("published_parsed"):
                try:
                    tp = item["published_parsed"]
                    published_at = datetime(*tp[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    pass

            if published_at < cutoff:
                continue

            companies: List[str] = []
            for kw in HOLDING_KEYWORDS:
                if kw in text_lower:
                    companies.append(kw.upper())

            strength = SignalStrength.HIGH if has_gs else SignalStrength.MEDIUM

            signals.append(Signal(
                title=title,
                source="news",
                published_at=published_at,
                summary=summary_text[:200] if summary_text else title,
                companies=companies if companies else ["GS"],
                strength=strength,
                url=item.get("link") or None,
            ))

        return signals

    async def close(self) -> None:
        await self.client.aclose()
