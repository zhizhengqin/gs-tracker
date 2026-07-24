"""RSS news signal source."""
import html as _html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import feedparser
import httpx

from src.config import SIGNAL_LOOKBACK_DAYS, SEC_USER_AGENT
from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_html_text(raw: str) -> str:
    """Strip HTML tags/entities and collapse whitespace.

    RSS summaries (e.g. wallstreetcn) embed full HTML markup; storing it raw
    produced the '乱码' (garbled tag soup) seen in the dashboard.
    """
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    text = _html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


GS_KEYWORDS = [
    "goldman sachs", "goldman", "高盛",
]

# Viewpoint/analysis keywords — GS-authored or GS-attributed content.
# Matching these indicates a signal where GS is the *source* of analysis,
# not just mentioned in passing.
GS_VIEWPOINT_KEYWORDS = [
    "hatzius",           # Jan Hatzius — GS chief economist
    "kostin",            # David Kostin — GS chief US equity strategist
    "goldman sachs says",
    "goldman sachs expects",
    "goldman sachs upgrades",
    "goldman sachs downgrades",
    "goldman sachs forecast",
    "goldman sachs predicts",
    "goldman sachs warns",
    "goldman sachs sees",
    "goldman strategists",
    "goldman analysts",
    "goldman economists",
    "高盛 研报",
    "高盛 观点",
    "高盛 预计",
    "高盛 预测",
    "高盛 上调",
    "高盛 下调",
    "高盛 维持",
    "高盛 警告",
]

HOLDING_KEYWORDS = [
    "apple", "aapl", "microsoft", "msft", "nvidia", "nvda",
    "amazon", "amzn", "meta", "googl", "google", "tesla", "tsla",
    "berkshire", "jpmorgan", "jpm", "visa",
    "unitedhealth", "unh", "mastercard",
]


def _kw_regex(kw: str) -> "re.Pattern":
    """ASCII keywords match on word boundaries (so 'visa' hits Visa but 'v'
    can't hit every 'vs'); CJK keywords match as plain substrings with
    optional whitespace between characters (高盛研报 ≈ 高盛 研报)."""
    if kw.isascii():
        return re.compile(r"\b" + re.escape(kw) + r"\b")
    chars = [re.escape(c) for c in kw.replace(" ", "")]
    return re.compile(r"\s*".join(chars))


_GS_RE = [_kw_regex(k) for k in GS_KEYWORDS]
_VIEWPOINT_RE = [_kw_regex(k) for k in GS_VIEWPOINT_KEYWORDS]
_HOLDING_RE = [(k, _kw_regex(k)) for k in HOLDING_KEYWORDS]


QUARTER_START_MONTHS = {"Q1": 1, "Q2": 4, "Q3": 7, "Q4": 10}


def _quarter_start(quarter: str) -> datetime:
    """Return the first day of the quarter as a UTC datetime.

    When *quarter* is empty (called from fetch_since / daily intel path),
    default to a 90-day lookback.
    """
    if not quarter:
        return datetime.now(timezone.utc) - timedelta(days=90)
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
            title = clean_html_text(item["title"])
            summary_text = clean_html_text(item.get("summary", ""))
            text_lower = (title + " " + summary_text).lower()

            has_gs = any(rx.search(text_lower) for rx in _GS_RE)
            has_viewpoint = any(rx.search(text_lower) for rx in _VIEWPOINT_RE)
            # GS-focused tracker (user feedback 2026-07): drop general market
            # news that only mentions a holding company without any GS angle.
            if not (has_gs or has_viewpoint):
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
            for kw, rx in _HOLDING_RE:
                if rx.search(text_lower):
                    companies.append(kw.upper())

            # Viewpoint keywords → HIGH (GS-authored analysis, the core value)
            # Basic GS mention → MEDIUM (news about GS)
            strength = SignalStrength.HIGH if has_viewpoint else SignalStrength.MEDIUM

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

    async def fetch_since(
        self, watermark: Optional[str] = None
    ) -> Tuple[List[Signal], Optional[str]]:
        """Fetch RSS items newer than *watermark* (ISO date string YYYY-MM-DD).

        Returns (signals, new_watermark). When watermark is None, uses the
        standard SIGNAL_LOOKBACK_DAYS cutoff.
        """
        all_signals = await self.fetch("")  # empty quarter → lookback-based cutoff

        if not all_signals:
            return [], watermark

        # Filter by watermark: keep signals published strictly after the watermark
        if watermark:
            try:
                wm_date = datetime.strptime(watermark, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                all_signals = [s for s in all_signals if s.published_at > wm_date]
            except ValueError:
                logger.warning("Invalid watermark format: %s, ignoring filter", watermark)

        # Compute new watermark = latest published_at among results
        new_watermark = watermark
        if all_signals:
            latest = max(s.published_at for s in all_signals)
            new_watermark = latest.strftime("%Y-%m-%d")

        return all_signals, new_watermark

    async def close(self) -> None:
        await self.client.aclose()
