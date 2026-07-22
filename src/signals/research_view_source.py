"""Goldman Sachs Insights research view signal source.

Discovers new GS Insights articles via the sitemap, then extracts
title/date/summary from each article's static HTML (schema.org JSON-LD +
meta tags). No JavaScript rendering required — pure httpx + regex.

Categories covered (filtered from sitemap):
- /insights/articles/      — general research articles
- /insights/the-markets/   — market analysis
- /insights/top-of-mind/   — flagship research series
- /insights/outlooks/      — macro outlooks

Watermark is an ISO date string (YYYY-MM-DD) — the most recent <lastmod>
seen. Next run only fetches articles with lastmod > watermark.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import httpx

from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

SITEMAP_URL = "https://www.goldmansachs.com/sitemap-1.xml"

# Categories to track.
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
# Sitemap block parsing: each <url> block contains <loc> and <lastmod>.
_RE_URL_BLOCK = re.compile(r"<url>(.*?)</url>", re.DOTALL)
_RE_LOC = re.compile(r"<loc>([^<]+)</loc>")
_RE_LASTMOD = re.compile(r"<lastmod>([^<]+)</lastmod>")


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
        """Fetch new GS Insights articles since *watermark* (ISO date).

        Watermark is an ISO date string (YYYY-MM-DD) — the most recent
        <lastmod> date seen. Articles with lastmod > watermark are new.

        Never raises — returns empty on failure.
        """
        try:
            response = await self.client.get(SITEMAP_URL)
            response.raise_for_status()
            sitemap_text = response.text
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("Failed to fetch GS sitemap: %s", exc)
            return [], watermark

        # Parse sitemap: extract (url, lastmod_date) for every insight article.
        candidates: list[tuple[str, str]] = []  # (url, lastmod_date_str)
        for block_match in _RE_URL_BLOCK.finditer(sitemap_text):
            block = block_match.group(1)
            loc_match = _RE_LOC.search(block)
            if not loc_match:
                continue
            url = loc_match.group(1)
            if not any(prefix in url for prefix in TRACKED_PREFIXES):
                continue
            # Skip PDF transcripts — we only parse HTML articles.
            if "/pdfs/" in url or url.endswith(".pdf"):
                continue
            lastmod_match = _RE_LASTMOD.search(block)
            lastmod = lastmod_match.group(1)[:10] if lastmod_match else ""
            candidates.append((url, lastmod))

        # Determine the cutoff date for filtering.
        # Watermark is an ISO date (YYYY-MM-DD). If the stored watermark
        # is a URL (old format), ignore it and use the 90-day default.
        _RE_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        if watermark and _RE_ISO_DATE.match(watermark):
            cutoff = watermark
        else:
            if watermark:
                logger.info("research_view: ignoring old URL-format watermark, using 90-day window")
            cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

        # Filter: lastmod > cutoff, sort by lastmod descending (newest first).
        recent = [
            (url, lm) for url, lm in candidates
            if lm and lm > cutoff
        ]
        recent.sort(key=lambda x: x[1], reverse=True)

        if not recent:
            return [], watermark

        # Fetch and parse articles, up to max_items.
        new_watermark = watermark
        signals: list[Signal] = []
        fetched = 0

        for url, lastmod in recent:
            if fetched >= self.max_items:
                break
            fetched += 1

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

            signals.append(
                Signal(
                    title=f"高盛研究: {headline}",
                    source="research_view",
                    published_at=published_at,
                    summary=description[:200] if description else headline,
                    companies=[],
                    strength=SignalStrength.HIGH,
                    url=url,
                )
            )

            # Advance watermark to the most recent lastmod we've processed.
            if lastmod and (not new_watermark or lastmod > new_watermark):
                new_watermark = lastmod

        logger.info(
            "research_view: %d new articles (watermark %s → %s, %d candidates)",
            len(signals), watermark, new_watermark, len(recent),
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
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").title()
