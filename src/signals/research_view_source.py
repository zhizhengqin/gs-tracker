"""Goldman Sachs Insights research view signal source.

Discovers new GS Insights articles via the sitemap, then extracts
title/date/summary from each article's static HTML (schema.org JSON-LD +
meta tags). No JavaScript rendering required — pure httpx + regex.

Categories covered (filtered from sitemap):
- /insights/articles/      — general research articles
- /insights/the-markets/   — market analysis
- /insights/top-of-mind/   — flagship research series
- /insights/outlooks/      — macro outlooks
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import httpx

from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

SITEMAP_URL = "https://www.goldmansachs.com/sitemap-1.xml"

# Categories to track. Each gets its own watermark path.
TRACKED_PREFIXES = [
    "/insights/articles/",
    "/insights/the-markets/",
    "/insights/top-of-mind/",
    "/insights/outlooks/",
]

# Regex to extract schema.org JSON-LD fields from article HTML.
_RE_HEADLINE = re.compile(r'"headline"\s*:\s*"([^"]+)"')
_RE_DATE_PUBLISHED = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
_RE_META_DESC = re.compile(
    r'<meta\s+name="description"\s+content="([^"]+)"', re.IGNORECASE
)
# Sitemap URL extraction
_RE_SITEMAP_LOC = re.compile(r"<loc>([^<]+)</loc>")


class ResearchViewSource:
    """Discover and extract GS Insights articles from the public website."""

    source_name = "research_view"

    def __init__(self, max_items: int = 10) -> None:
        self.max_items = max_items
        self.client = httpx.AsyncClient(
            timeout=20.0,
            headers={"User-Agent": "GS-Tracker/1.0 (research bot; contact@example.com)"},
        )

    async def fetch(self, quarter: str = "") -> List[Signal]:
        """Backward compat: fetch returns list."""
        signals, _ = await self.fetch_since()
        return signals

    async def fetch_since(
        self, watermark: Optional[str] = None
    ) -> Tuple[List[Signal], Optional[str]]:
        """Fetch new GS Insights articles since *watermark* (last-seen URL).

        Returns (signals, new_watermark). Watermark is the last-processed
        article URL — articles are processed in sitemap order.

        Never raises — returns empty on failure.
        """
        try:
            response = await self.client.get(SITEMAP_URL)
            response.raise_for_status()
            sitemap_text = response.text
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("Failed to fetch GS sitemap: %s", exc)
            return [], watermark

        # Extract all insight URLs from the sitemap, filtered by category.
        # Sitemap URLs are absolute (https://...), TRACKED_PREFIXES are paths.
        all_urls: list[str] = []
        for match in _RE_SITEMAP_LOC.finditer(sitemap_text):
            url = match.group(1)
            if any(prefix in url for prefix in TRACKED_PREFIXES):
                all_urls.append(url)

        # Filter: skip URLs before or at the watermark
        if watermark:
            try:
                wm_idx = all_urls.index(watermark)
                new_urls = all_urls[:wm_idx]  # URLs before watermark = newer
            except ValueError:
                new_urls = all_urls[: self.max_items]  # watermark not found → start fresh
        else:
            new_urls = all_urls[: self.max_items]

        if not new_urls:
            return [], watermark

        # Fetch and parse each article page
        signals: list[Signal] = []
        new_watermark = watermark
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)

        for url in new_urls[: self.max_items]:
            try:
                article_response = await self.client.get(url)
                article_response.raise_for_status()
                html = article_response.text
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.warning("Failed to fetch article %s: %s", url, exc)
                continue

            headline = _extract_first(_RE_HEADLINE, html) or _title_from_url(url)
            date_str = _extract_first(_RE_DATE_PUBLISHED, html)
            description = _extract_first(_RE_META_DESC, html) or ""

            published_at = datetime.now(timezone.utc)
            if date_str:
                try:
                    published_at = datetime.strptime(
                        date_str[:10], "%Y-%m-%d"
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

            # Skip articles older than 90 days — but watermark still advances
            # past them so the next run doesn't re-fetch the same stale batch.
            if published_at < cutoff:
                continue

            signals.append(
                Signal(
                    title=f"高盛研究: {headline}",
                    source="research_view",
                    published_at=published_at,
                    summary=description[:200] if description else headline,
                    companies=[],  # filled by keyword matching if needed
                    strength=SignalStrength.HIGH,
                    url=url,
                )
            )

        # Update watermark to the newest URL processed
        if new_urls:
            new_watermark = new_urls[0]  # sitemap is newest-first

        logger.info(
            "research_view: %d new articles (watermark %s → %s)",
            len(signals), watermark, new_watermark,
        )
        return signals, new_watermark

    async def close(self) -> None:
        await self.client.aclose()


def _extract_first(pattern: re.Pattern, text: str) -> Optional[str]:
    """Return the first capture group match, or None."""
    m = pattern.search(text)
    return m.group(1) if m else None


def _title_from_url(url: str) -> str:
    """Derive a readable title from an article URL slug."""
    # e.g. /insights/articles/the-fed-is-forecast-to-cut-rates → The Fed Is Forecast To Cut Rates
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").title()
