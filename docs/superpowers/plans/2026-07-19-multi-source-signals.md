# Phase 2 多源信号聚合引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-source signal aggregation engine that merges 13F holdings, RSS news, and SEC 8-K filings into a unified signal panel embedded in the existing HTML report.

**Architecture:** Three new signal sources (13F Adapter wrapping existing SEC13FFetcher output, RSS NewsSource, SEC 8-K Sec8kSource) produce `Signal` dataclass instances. `SignalAggregator` merges, deduplicates, and orchestrates per-source Claude summarization + cross-validation. `SignalScorer` applies a rule-based scoring engine (time proximity × entity overlap × source credibility) to rank signals high/medium/low. All integrated into `run_pipeline()` and rendered via Jinja2 template.

**Tech Stack:** Python 3.11+, httpx (async HTTP), feedparser (RSS), anthropic (Claude API), jinja2 (HTML templates), pytest + pytest-asyncio + pytest-httpx

## Global Constraints

- Python 3.11+ with type annotations, PEP 8
- 代码内部英文，用户可见中文
- TDD: RED (fail) → GREEN (pass) → REFACTOR → commit
- YAGNI: concrete implementations first, Protocol as documentation annotation only
- SEC EDGAR requests must carry User-Agent header (from config.SEC_USER_AGENT)
- API keys only from environment variables, never hard-coded
- Partial fault tolerance: single source failure → degraded mode (标注降级), never blocks report
- Claude stepwise: per-source parallel summarization → scorer → top-N cross-validation
- All 63 existing tests must continue passing

---

### Task 1: Signal Dataclass + Base Types

**Files:**
- Create: `src/signals/__init__.py`
- Create: `src/signals/base.py`
- Create: `tests/signals/__init__.py`
- Create: `tests/signals/test_base.py`

**Interfaces:**
- Produces: `Signal` dataclass, `SignalSource` Protocol, `SignalStrength` enum

- [ ] **Step 1: Write the failing test**

```python
"""Tests for src.signals.base."""
from datetime import datetime, timezone

import pytest

from src.signals.base import Signal, SignalStrength


class TestSignal:
    def test_signal_creation_with_required_fields(self):
        s = Signal(
            title="高盛增持 Apple 5%",
            source="13F",
            published_at=datetime(2026, 3, 31, tzinfo=timezone.utc),
            summary="高盛在 2026-Q1 增持 Apple 5%，持仓市值达到 $10B",
            companies=["AAPL"],
            strength=SignalStrength.HIGH,
        )
        assert s.title == "高盛增持 Apple 5%"
        assert s.source == "13F"
        assert s.companies == ["AAPL"]
        assert s.strength == SignalStrength.HIGH
        assert s.url is None
        assert s.cross_refs == []

    def test_signal_creation_with_all_fields(self):
        s = Signal(
            title="NVDA Q2 Earnings Beat",
            source="news",
            published_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
            summary="NVIDIA Q2 财报超预期，营收同比增长 120%",
            companies=["NVDA"],
            strength=SignalStrength.HIGH,
            url="https://example.com/nvda-q2",
            cross_refs=["sig-001"],
        )
        assert s.url == "https://example.com/nvda-q2"
        assert s.cross_refs == ["sig-001"]

    def test_signal_equality_by_id(self):
        s1 = Signal(
            title="Same Title",
            source="news",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            summary="Summary",
            companies=["AAPL"],
            strength=SignalStrength.LOW,
        )
        s2 = Signal(
            title="Same Title",
            source="news",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            summary="Summary",
            companies=["AAPL"],
            strength=SignalStrength.LOW,
        )
        # Different auto-generated IDs
        assert s1.id != s2.id

    def test_signal_strength_enum_values(self):
        assert SignalStrength.HIGH.value == "high"
        assert SignalStrength.MEDIUM.value == "medium"
        assert SignalStrength.LOW.value == "low"

    def test_signal_dedupe_key(self):
        s = Signal(
            title="Test",
            source="news",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            summary="Summary",
            companies=["TEST"],
            strength=SignalStrength.LOW,
        )
        # dedupe_key is (source, title) for identifying duplicate signals
        assert s.dedupe_key == ("news", "Test")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.signals.base'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/signals/__init__.py
"""Multi-source signal aggregation package."""

# src/signals/base.py
"""Base types for the signal aggregation system."""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Protocol, Tuple


class SignalStrength(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Signal:
    """Unified signal format across all data sources."""

    title: str
    source: str
    published_at: datetime
    summary: str
    companies: List[str]
    strength: SignalStrength
    url: Optional[str] = None
    cross_refs: List[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    @property
    def dedupe_key(self) -> Tuple[str, str]:
        """Key for identifying duplicate signals across sources."""
        return (self.source, self.title)


class SignalSource(Protocol):
    """Protocol documenting expected signal source interface.

    This is a documentation annotation, not enforced at runtime.
    Concrete implementations return List[Signal] from fetch().
    """

    source_name: str

    async def fetch(self, quarter: str) -> List[Signal]: ...

    async def close(self) -> None: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/signals/test_base.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/signals/__init__.py src/signals/base.py tests/signals/__init__.py tests/signals/test_base.py
git commit -m "feat(signals): add Signal dataclass and base types"
```

---

### Task 2: 13F Adapter

**Files:**
- Create: `src/signals/13f_adapter.py`
- Create: `tests/signals/test_13f_adapter.py`

**Interfaces:**
- Consumes: `Signal`, `SignalStrength` from `src.signals.base`
- Produces: `ThirteenthFSignalAdapter.to_signals(records: list[dict], quarter: str, comparison: Optional[dict]) -> list[Signal]`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for src.signals.13f_adapter."""
from datetime import datetime, timezone

import pytest

from src.signals.base import Signal, SignalStrength
from src.signals.13f_adapter import ThirteenthFSignalAdapter


class TestThirteenthFSignalAdapter:
    def test_to_signals_converts_top_holdings(self):
        adapter = ThirteenthFSignalAdapter()
        records = [
            {
                "name_of_issuer": "Apple Inc",
                "cusip": "037833100",
                "value": 10_000_000_000.0,
                "shares": 100_000,
                "title_of_class": "COM",
            },
        ]
        comparison = {
            "total_value": 500_000_000_000.0,
            "new_positions": 3,
            "sold_positions": 1,
            "increased_positions": 5,
            "decreased_positions": 2,
        }
        signals = adapter.to_signals(records, "2026-Q1", comparison)
        assert len(signals) >= 1
        top_signal = signals[0]
        assert "Apple" in top_signal.title or "Apple" in top_signal.companies
        assert top_signal.source == "13F"
        assert top_signal.strength in (SignalStrength.HIGH, SignalStrength.MEDIUM)

    def test_to_signals_empty_records_returns_empty_list(self):
        adapter = ThirteenthFSignalAdapter()
        signals = adapter.to_signals([], "2026-Q1", None)
        assert signals == []

    def test_to_signals_without_comparison(self):
        adapter = ThirteenthFSignalAdapter()
        records = [
            {
                "name_of_issuer": "Apple Inc",
                "value": 10_000_000_000.0,
            },
        ]
        signals = adapter.to_signals(records, "2026-Q1", None)
        # Should still produce signals, just without change context
        assert len(signals) >= 1

    def test_to_signals_limits_to_top_n(self):
        adapter = ThirteenthFSignalAdapter(max_signals=3)
        records = [
            {"name_of_issuer": f"Company {i}", "value": float(1000 - i * 10)}
            for i in range(20)
        ]
        signals = adapter.to_signals(records, "2026-Q1", None)
        assert len(signals) <= 3

    def test_to_signals_sorts_by_value_descending(self):
        adapter = ThirteenthFSignalAdapter(max_signals=5)
        records = [
            {"name_of_issuer": "Small Co", "value": 100.0},
            {"name_of_issuer": "Big Co", "value": 1_000_000_000.0},
            {"name_of_issuer": "Medium Co", "value": 500_000.0},
        ]
        signals = adapter.to_signals(records, "2026-Q1", None)
        assert signals[0].companies[0] == "Big Co"
        assert signals[1].companies[0] == "Medium Co"
        assert signals[2].companies[0] == "Small Co"

    def test_signal_published_at_uses_quarter_end(self):
        adapter = ThirteenthFSignalAdapter()
        records = [{"name_of_issuer": "Apple Inc", "value": 100.0}]
        signals = adapter.to_signals(records, "2026-Q1", None)
        # Q1 ends March 31
        expected = datetime(2026, 3, 31, tzinfo=timezone.utc)
        assert signals[0].published_at.date() == expected.date()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_13f_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.signals.13f_adapter'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Adapter converting existing 13F holdings into Signal format."""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

QUARTER_END_MONTHS = {"Q1": 3, "Q2": 6, "Q3": 9, "Q4": 12}


def _quarter_end_date(quarter: str) -> datetime:
    """Return the last day of the quarter as a UTC datetime."""
    year_str, q = quarter.split("-")
    year = int(year_str)
    month = QUARTER_END_MONTHS[q]
    # Last day of the month — use day 28 and let month roll
    if month == 12:
        return datetime(year, 12, 31, tzinfo=timezone.utc)
    # Use the 1st of next month minus 1 day
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    return datetime(year, month, last_day, tzinfo=timezone.utc)


class ThirteenthFSignalAdapter:
    """Wrap existing 13F holdings data as Signal objects.

    Does NOT modify SEC13FFetcher — wraps its output post-fetch.
    """

    def __init__(self, max_signals: int = 10) -> None:
        self.max_signals = max_signals

    def to_signals(
        self,
        records: List[Dict[str, Any]],
        quarter: str,
        comparison: Optional[Dict[str, Any]] = None,
    ) -> List[Signal]:
        """Convert holdings records into Signals, sorted by value desc."""
        if not records:
            return []

        published_at = _quarter_end_date(quarter)
        # Sort by value descending, take top N
        sorted_records = sorted(
            records,
            key=lambda r: float(r.get("value", 0) or 0),
            reverse=True,
        )[:self.max_signals]

        signals: List[Signal] = []
        for record in sorted_records:
            name = record.get("name_of_issuer", "Unknown")
            value = float(record.get("value", 0) or 0)

            # Build title with context from comparison if available
            title = f"高盛持仓: {name}"
            summary_parts = [f"高盛持有 {name}"]
            if value > 0:
                if value >= 1e9:
                    summary_parts.append(f"市值 ${value / 1e9:.1f}B")
                else:
                    summary_parts.append(f"市值 ${value / 1e6:.0f}M")

            # Determine strength from position size relative to total
            total_value = None
            if comparison and comparison.get("total_value"):
                total_value = float(comparison["total_value"])
            if total_value and total_value > 0:
                pct = value / total_value
                if pct > 0.05:
                    strength = SignalStrength.HIGH
                elif pct > 0.01:
                    strength = SignalStrength.MEDIUM
                else:
                    strength = SignalStrength.LOW
                summary_parts.append(f"占比 {pct * 100:.1f}%")
            else:
                strength = SignalStrength.MEDIUM

            signals.append(Signal(
                title=title,
                source="13F",
                published_at=published_at,
                summary="，".join(summary_parts) + "。",
                companies=[name],
                strength=strength,
            ))

        return signals
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/signals/test_13f_adapter.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/signals/13f_adapter.py tests/signals/test_13f_adapter.py
git commit -m "feat(signals): add 13F adapter wrapping existing holdings"
```

---

### Task 3: RSS News Signal Source

**Files:**
- Create: `src/signals/news_source.py`
- Create: `tests/signals/test_news_source.py`
- Modify: `src/config.py` — add `RSS_FEEDS` and `SIGNAL_LOOKBACK_DAYS` config

**Interfaces:**
- Consumes: `Signal`, `SignalStrength` from `src.signals.base`
- Produces: `NewsSource.fetch(quarter: str) -> list[Signal]`, `NewsSource.close() -> None`

- [ ] **Step 1: Write config additions test**

In `tests/test_config.py`, add:

```python
def test_rss_feeds_default():
    assert isinstance(config.RSS_FEEDS, list)


def test_signal_lookback_days_default():
    assert config.SIGNAL_LOOKBACK_DAYS == 90
```

Run: `pytest tests/test_config.py::test_rss_feeds_default tests/test_config.py::test_signal_lookback_days_default -v`
Expected: FAIL — `AttributeError: module 'src.config' has no attribute 'RSS_FEEDS'`

- [ ] **Step 2: Add config values**

In `src/config.py`, add after existing config lines:

```python
# Signal aggregation
RSS_FEEDS_RAW = os.getenv("RSS_FEEDS", "https://feeds.content.dowjones.io/public/rss/RSSWSJ,https://www.reuters.com/arc/outboundfeeds/v3/all/?outputType=xml&utm_medium=web&utm_campaign=site&utm_source=reuters&utm_content=MLP")
RSS_FEEDS: list[str] = [u.strip() for u in RSS_FEEDS_RAW.split(",") if u.strip()]
SIGNAL_LOOKBACK_DAYS = int(os.getenv("SIGNAL_LOOKBACK_DAYS", "90"))
```

Run: `pytest tests/test_config.py::test_rss_feeds_default tests/test_config.py::test_signal_lookback_days_default -v`
Expected: PASS (2 tests)

- [ ] **Step 3: Write the failing test for NewsSource**

```python
"""Tests for src.signals.news_source."""
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from pytest_httpx import HTTPXMock

from src.signals.base import Signal
from src.signals.news_source import NewsSource


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>WSJ Markets</title>
    <item>
      <title>Goldman Sachs Increases Apple Stake by 5%</title>
      <link>https://wsj.com/gs-apple</link>
      <description>Goldman Sachs disclosed a 5% increase in its Apple position...</description>
      <pubDate>Mon, 15 May 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Goldman Eyes Tech Sector Rotation</title>
      <link>https://wsj.com/gs-tech</link>
      <description>The bank is shifting from software to semiconductors...</description>
      <pubDate>Tue, 16 May 2026 14:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""


@pytest_asyncio.fixture
async def news_source():
    source = NewsSource(rss_urls=["https://example.com/rss"])
    yield source
    await source.close()


class TestNewsSource:
    @pytest.mark.asyncio
    async def test_fetch_parses_rss_items(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(text=SAMPLE_RSS, status_code=200)
        source = NewsSource(rss_urls=["https://example.com/rss"])
        signals = await source.fetch("2026-Q2")
        assert len(signals) == 2
        assert signals[0].source == "news"
        assert "Apple" in signals[0].title or "Apple" in signals[0].summary
        assert isinstance(signals[0].published_at, datetime)
        await source.close()

    @pytest.mark.asyncio
    async def test_fetch_handles_http_error(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(status_code=500)
        source = NewsSource(rss_urls=["https://example.com/rss"])
        signals = await source.fetch("2026-Q2")
        assert signals == []  # degraded — no crash
        await source.close()

    @pytest.mark.asyncio
    async def test_fetch_handles_timeout(self, httpx_mock: HTTPXMock):
        import httpx
        httpx_mock.add_exception(httpx.TimeoutException("timed out"))
        source = NewsSource(rss_urls=["https://example.com/rss"])
        signals = await source.fetch("2026-Q2")
        assert signals == []  # degraded
        await source.close()

    @pytest.mark.asyncio
    async def test_fetch_handles_invalid_xml(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(text="not valid xml <<<", status_code=200)
        source = NewsSource(rss_urls=["https://example.com/rss"])
        signals = await source.fetch("2026-Q2")
        assert signals == []

    @pytest.mark.asyncio
    async def test_fetch_empty_feed(self, httpx_mock: HTTPXMock):
        empty_rss = """<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>"""
        httpx_mock.add_response(text=empty_rss, status_code=200)
        source = NewsSource(rss_urls=["https://example.com/rss"])
        signals = await source.fetch("2026-Q2")
        assert signals == []

    @pytest.mark.asyncio
    async def test_fetch_multiple_feeds(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(text=SAMPLE_RSS, status_code=200)
        source = NewsSource(rss_urls=["https://a.com/rss", "https://b.com/rss"])
        signals = await source.fetch("2026-Q2")
        # Both feeds return the same SAMPLE_RSS (2 items each), then deduped
        assert len(signals) >= 2
        await source.close()

    @pytest.mark.asyncio
    async def test_fetch_filters_by_keywords(self, httpx_mock: HTTPXMock):
        """Items without Goldman Sachs or holding company keywords should be filtered."""
        mixed_rss = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item><title>Goldman Sachs News</title><link>https://a.com/1</link><description>GS related</description><pubDate>Mon, 15 May 2026 10:00:00 GMT</pubDate></item>
          <item><title>Unrelated Sports News</title><link>https://a.com/2</link><description>Sports</description><pubDate>Mon, 15 May 2026 10:00:00 GMT</pubDate></item>
          <item><title>Apple Earnings Report</title><link>https://a.com/3</link><description>AAPL beats estimates</description><pubDate>Mon, 15 May 2026 10:00:00 GMT</pubDate></item>
        </channel></rss>"""
        httpx_mock.add_response(text=mixed_rss, status_code=200)
        source = NewsSource(rss_urls=["https://example.com/rss"])
        signals = await source.fetch("2026-Q2")
        # Goldman and Apple items kept; "Unrelated Sports" filtered out
        assert len(signals) == 2
        titles = [s.title for s in signals]
        assert any("Goldman" in t for t in titles)
        assert any("Apple" in t for t in titles)
        await source.close()
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/signals/test_news_source.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 5: Write minimal implementation**

```python
"""RSS news signal source."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import feedparser
import httpx

from src.config import SIGNAL_LOOKBACK_DAYS, SEC_USER_AGENT
from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

# Keywords for filtering relevant news items
GS_KEYWORDS = [
    "goldman sachs", "goldman", "高盛",
]
# Top holdings tickers/names to match in news
HOLDING_KEYWORDS = [
    "apple", "aapl", "microsoft", "msft", "nvidia", "nvda",
    "amazon", "amzn", "meta", "googl", "google", "tesla", "tsla",
    "berkshire", "brk", "jpmorgan", "jpm", "visa", "v",
    "unitedhealth", "unh", "mastercard", "ma",
]


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
        """Fetch RSS items and convert to Signals."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=SIGNAL_LOOKBACK_DAYS)
        all_items: List[dict] = []

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
                        "published": getattr(entry, "published", ""),
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

            # Filter: must mention GS or a known holding
            text_lower = (title + " " + summary_text).lower()
            has_gs = any(kw in text_lower for kw in GS_KEYWORDS)
            has_holding = any(kw in text_lower for kw in HOLDING_KEYWORDS)
            if not (has_gs or has_holding):
                continue

            # Parse publication date
            published_at = datetime.now(timezone.utc)
            if item.get("published_parsed"):
                try:
                    tp = item["published_parsed"]
                    published_at = datetime(*tp[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    pass

            # Skip items older than lookback window
            if published_at < cutoff:
                continue

            # Determine companies mentioned
            companies: List[str] = []
            for kw in HOLDING_KEYWORDS:
                if kw in text_lower:
                    companies.append(kw.upper())

            # Score strength: GS directly mentioned = HIGH, holding only = MEDIUM
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/signals/test_news_source.py -v`
Expected: PASS (7 tests)

- [ ] **Step 7: Commit**

```bash
git add src/config.py tests/test_config.py src/signals/news_source.py tests/signals/test_news_source.py
git commit -m "feat(signals): add RSS news signal source with keyword filtering"
```

---

### Task 4: SEC 8-K Signal Source

**Files:**
- Create: `src/signals/sec_8k_source.py`
- Create: `tests/signals/test_sec_8k_source.py`

**Interfaces:**
- Consumes: `Signal`, `SignalStrength` from `src.signals.base`, `SEC_USER_AGENT`, `GOLDMAN_CIK` from `src.config`
- Produces: `Sec8kSource.fetch(quarter: str) -> list[Signal]`, `Sec8kSource.close() -> None`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for src.signals.sec_8k_source."""
import json
from datetime import datetime, timezone

import pytest
from pytest_httpx import HTTPXMock

from src.signals.base import Signal
from src.signals.sec_8k_source import Sec8kSource


# Mock SEC EDGAR submissions API response
MOCK_SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["8-K", "8-K", "10-Q", "8-K", "4"],
            "filingDate": ["2026-05-15", "2026-05-10", "2026-05-08", "2026-04-20", "2026-04-15"],
            "accessionNumber": [
                "0000886982-26-000001",
                "0000886982-26-000002",
                "0000886982-26-000003",
                "0000886982-26-000004",
                "0000886982-26-000005",
            ],
            "primaryDocument": [
                "form8k-001.htm",
                "form8k-002.htm",
                "form10q-003.htm",
                "form8k-004.htm",
                "form4-005.htm",
            ],
            "items": [
                "2.02,9.01",
                "5.02",
                "",
                "1.01,2.03",
                "",
            ],
        }
    }
}


class TestSec8kSource:
    @pytest.mark.asyncio
    async def test_fetch_returns_8k_signals(self, httpx_mock: HTTPXMock):
        submissions_url = "https://data.sec.gov/submissions/CIK0000886982.json"
        httpx_mock.add_response(
            url=submissions_url,
            json=MOCK_SUBMISSIONS,
            status_code=200,
        )
        source = Sec8kSource()
        signals = await source.fetch("2026-Q2")
        # 4 out of 5 filings are 8-K (form == "8-K")
        assert len(signals) >= 1
        for s in signals:
            assert s.source == "8-K"
            assert isinstance(s.published_at, datetime)
            assert s.companies  # at minimum ["GS"]
        await source.close()

    @pytest.mark.asyncio
    async def test_fetch_handles_sec_error(self, httpx_mock: HTTPXMock):
        submissions_url = "https://data.sec.gov/submissions/CIK0000886982.json"
        httpx_mock.add_response(url=submissions_url, status_code=500)
        source = Sec8kSource()
        signals = await source.fetch("2026-Q2")
        assert signals == []  # degraded
        await source.close()

    @pytest.mark.asyncio
    async def test_fetch_handles_invalid_json(self, httpx_mock: HTTPXMock):
        submissions_url = "https://data.sec.gov/submissions/CIK0000886982.json"
        httpx_mock.add_response(url=submissions_url, text="not json", status_code=200)
        source = Sec8kSource()
        signals = await source.fetch("2026-Q2")
        assert signals == []

    @pytest.mark.asyncio
    async def test_fetch_filters_by_quarter(self, httpx_mock: HTTPXMock):
        """Only 8-K filings within the quarter's date range should be returned."""
        quarter_data = {
            "filings": {
                "recent": {
                    "form": ["8-K", "8-K"],
                    "filingDate": ["2026-04-15", "2026-07-01"],  # Q2 = Apr-Jun
                    "accessionNumber": ["0000886982-26-000010", "0000886982-26-000011"],
                    "primaryDocument": ["form8k-010.htm", "form8k-011.htm"],
                    "items": ["2.02", "5.02"],
                }
            }
        }
        submissions_url = "https://data.sec.gov/submissions/CIK0000886982.json"
        httpx_mock.add_response(url=submissions_url, json=quarter_data, status_code=200)
        source = Sec8kSource()
        signals = await source.fetch("2026-Q2")
        # July 1 filing is outside Q2, should be excluded
        assert len(signals) == 1
        assert "2026-04-15" in signals[0].summary or signals[0].published_at.day == 15
        await source.close()

    @pytest.mark.asyncio
    async def test_fetch_no_8k_filings(self, httpx_mock: HTTPXMock):
        no_8k = {
            "filings": {
                "recent": {
                    "form": ["10-Q", "4"],
                    "filingDate": ["2026-05-15", "2026-05-10"],
                    "accessionNumber": ["0000886982-26-000020", "0000886982-26-000021"],
                    "primaryDocument": ["form10q.htm", "form4.htm"],
                    "items": ["", ""],
                }
            }
        }
        submissions_url = "https://data.sec.gov/submissions/CIK0000886982.json"
        httpx_mock.add_response(url=submissions_url, json=no_8k, status_code=200)
        source = Sec8kSource()
        signals = await source.fetch("2026-Q2")
        assert signals == []

    @pytest.mark.asyncio
    async def test_fetch_respects_max_items(self, httpx_mock: HTTPXMock):
        """Should limit to max_items most recent 8-Ks."""
        forms = ["8-K"] * 10
        dates = [f"2026-05-{d:02d}" for d in range(1, 11)]
        acc_nums = [f"0000886982-26-0000{d:02d}" for d in range(1, 11)]
        docs = [f"form8k-{d:03d}.htm" for d in range(1, 11)]
        items = ["2.02"] * 10

        many_8k = {
            "filings": {
                "recent": {
                    "form": forms,
                    "filingDate": dates,
                    "accessionNumber": acc_nums,
                    "primaryDocument": docs,
                    "items": items,
                }
            }
        }
        submissions_url = "https://data.sec.gov/submissions/CIK0000886982.json"
        httpx_mock.add_response(url=submissions_url, json=many_8k, status_code=200)
        source = Sec8kSource(max_items=5)
        signals = await source.fetch("2026-Q2")
        assert len(signals) <= 5
        await source.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_sec_8k_source.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
"""SEC 8-K filing signal source."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from src.config import GOLDMAN_CIK, SEC_BACKOFF_BASE, SEC_MAX_RETRIES, SEC_USER_AGENT
from src.signals.base import Signal, SignalStrength
from src.signals.news_source import GS_KEYWORDS  # reuse GS keyword list

logger = logging.getLogger(__name__)

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{}.json"

# 8-K item type → human-readable label
ITEM_LABELS: Dict[str, str] = {
    "1.01": "重大合作协议",
    "1.02": "重大合作协议终止",
    "2.01": "重大资产收购/处置",
    "2.02": "财务业绩披露",
    "2.03": "重大财务义务",
    "2.04": "加速债务触发事件",
    "2.05": "资产退出成本",
    "2.06": "商誉减值",
    "3.01": "退市/转板通知",
    "3.02": "股权发行",
    "3.03": "股东权利变更",
    "4.01": "审计师变更",
    "4.02": "重述/不再依赖此前财报",
    "5.01": "控制权变更",
    "5.02": "高管/董事任免",
    "5.03": "章程修订",
    "5.07": "股东投票结果",
    "7.01": "监管FD披露",
    "8.01": "其他重大事件",
    "9.01": "财务报表与展品",
}

QUARTER_DATE_RANGES = {
    "Q1": ("-01-01", "-03-31"),
    "Q2": ("-04-01", "-06-30"),
    "Q3": ("-07-01", "-09-30"),
    "Q4": ("-10-01", "-12-31"),
}


class Sec8kSource:
    """Fetch 8-K filing signals from SEC EDGAR."""

    source_name = "8-K"

    def __init__(self, cik: str = GOLDMAN_CIK, max_items: int = 10) -> None:
        self.cik = cik.lstrip("0")  # SEC API uses CIK without leading zeros
        self.max_items = max_items
        self.client = httpx.AsyncClient(
            timeout=20.0,
            headers={"User-Agent": SEC_USER_AGENT},
        )

    async def fetch(self, quarter: str) -> List[Signal]:
        """Fetch recent 8-K filings and convert to Signals."""
        try:
            url = SEC_SUBMISSIONS_URL.format(self.cik.zfill(10))
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
            logger.warning("Failed to fetch SEC submissions: %s", exc)
            return []

        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        dates = filings.get("filingDate", [])
        acc_nums = filings.get("accessionNumber", [])
        docs = filings.get("primaryDocument", [])
        items = filings.get("items", [])

        signals: List[Signal] = []
        count = 0

        year_str, q = quarter.split("-")
        year = int(year_str)
        range_start, range_end = QUARTER_DATE_RANGES.get(q, ("-01-01", "-12-31"))
        quarter_start = f"{year}{range_start}"
        quarter_end = f"{year}{range_end}"

        for i in range(len(forms)):
            if count >= self.max_items:
                break
            if forms[i] != "8-K":
                continue

            filing_date = dates[i] if i < len(dates) else ""
            # Filter to filings within the quarter
            if filing_date < quarter_start or filing_date > quarter_end:
                continue

            item_list = items[i].split(",") if i < len(items) and items[i] else []
            item_labels = [
                ITEM_LABELS.get(it.strip(), f"Item {it.strip()}")
                for it in item_list
                if it.strip()
            ]

            acc_num = acc_nums[i] if i < len(acc_nums) else ""
            doc_name = docs[i] if i < len(docs) else ""

            title = "高盛 8-K: "
            if item_labels:
                title += "、".join(item_labels[:3])
            else:
                title += "重大事件披露"

            published_at = datetime.strptime(filing_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

            signals.append(Signal(
                title=title,
                source="8-K",
                published_at=published_at,
                summary=f"高盛于 {filing_date} 提交 8-K 报告。涉及事项: {', '.join(item_labels) if item_labels else '待解析'}。SEC 文件编号: {acc_num}。",
                companies=["GS"],
                strength=SignalStrength.HIGH if item_labels else SignalStrength.MEDIUM,
                url=f"https://www.sec.gov/Archives/edgar/data/{self.cik.zfill(10)}/{acc_num.replace('-', '')}/{doc_name}" if acc_num and doc_name else None,
            ))

            count += 1

        return signals

    async def close(self) -> None:
        await self.client.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/signals/test_sec_8k_source.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/signals/sec_8k_source.py tests/signals/test_sec_8k_source.py
git commit -m "feat(signals): add SEC 8-K filing signal source"
```

---

### Task 5: SignalAggregator

**Files:**
- Create: `src/signals/aggregator.py`
- Create: `tests/signals/test_aggregator.py`

**Interfaces:**
- Consumes: `Signal`, `SignalStrength` from `src.signals.base`, all source classes
- Produces: `SignalAggregator.aggregate(quarter: str) -> AggregationResult`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for src.signals.aggregator."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.signals.aggregator import AggregationResult, SignalAggregator
from src.signals.base import Signal, SignalStrength


def make_signal(title, source, companies=None, strength=None, offset_days=0):
    return Signal(
        title=title,
        source=source,
        published_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
        summary=f"Summary for {title}",
        companies=companies or ["GS"],
        strength=strength or SignalStrength.MEDIUM,
    )


class TestSignalAggregator:
    @pytest.mark.asyncio
    async def test_aggregate_merges_sources(self):
        """Multiple sources produce signals that get merged and deduped."""
        mock_13f = AsyncMock()
        mock_13f.to_signals.return_value = [
            make_signal("高盛持仓: Apple Inc", "13F", companies=["Apple Inc"]),
            make_signal("高盛持仓: Microsoft Corp", "13F", companies=["Microsoft Corp"]),
        ]
        mock_news = AsyncMock()
        mock_news.fetch.return_value = [
            make_signal("Goldman Increases Apple Stake", "news", companies=["AAPL"]),
            make_signal("Goldman Tech Pivot", "news", companies=["GS"]),
        ]
        mock_8k = AsyncMock()
        mock_8k.fetch.return_value = [
            make_signal("高盛 8-K: 财务业绩披露", "8-K", companies=["GS"]),
        ]

        aggregator = SignalAggregator(
            adapter_13f=mock_13f,
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        result = await aggregator.aggregate(
            quarter="2026-Q2",
            holdings_records=[
                {"name_of_issuer": "Apple Inc", "value": 100.0},
                {"name_of_issuer": "Microsoft Corp", "value": 50.0},
            ],
            comparison={"total_value": 150.0},
        )

        assert isinstance(result, AggregationResult)
        assert len(result.signals) >= 5  # 2 13F + 2 news + 1 8-K
        assert result.errors == []
        mock_news.fetch.assert_awaited_once_with("2026-Q2")
        mock_8k.fetch.assert_awaited_once_with("2026-Q2")

    @pytest.mark.asyncio
    async def test_aggregate_handles_source_failure(self):
        """When one source fails, others still produce signals."""
        mock_13f = AsyncMock()
        mock_13f.to_signals.return_value = [
            make_signal("高盛持仓: Apple Inc", "13F"),
        ]
        mock_news = AsyncMock()
        mock_news.fetch.side_effect = RuntimeError("RSS source down")
        mock_8k = AsyncMock()
        mock_8k.fetch.return_value = [
            make_signal("高盛 8-K: 重大事件", "8-K"),
        ]

        aggregator = SignalAggregator(
            adapter_13f=mock_13f,
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        result = await aggregator.aggregate(
            quarter="2026-Q2",
            holdings_records=[{"name_of_issuer": "Apple Inc", "value": 100.0}],
        )

        assert len(result.signals) >= 2  # 13F + 8-K, news failed
        assert len(result.errors) == 1
        assert "news" in result.errors[0].lower()

    @pytest.mark.asyncio
    async def test_aggregate_dedup_by_title(self):
        """Signals with the same title (from different sources) are deduped."""
        mock_13f = AsyncMock()
        mock_13f.to_signals.return_value = []
        mock_news = AsyncMock()
        mock_news.fetch.return_value = [
            make_signal("Goldman Increases Apple Stake", "news"),
            make_signal("Goldman Increases Apple Stake", "news"),  # duplicate
        ]
        mock_8k = AsyncMock()
        mock_8k.fetch.return_value = []

        aggregator = SignalAggregator(
            adapter_13f=mock_13f,
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        result = await aggregator.aggregate(
            quarter="2026-Q2",
            holdings_records=[],
        )
        assert len(result.signals) == 1  # deduped

    @pytest.mark.asyncio
    async def test_aggregate_all_sources_fail(self):
        """When all sources fail, returns empty signals with error list."""
        mock_13f = AsyncMock()
        mock_13f.to_signals.side_effect = RuntimeError("fail")
        mock_news = AsyncMock()
        mock_news.fetch.side_effect = RuntimeError("fail")
        mock_8k = AsyncMock()
        mock_8k.fetch.side_effect = RuntimeError("fail")

        aggregator = SignalAggregator(
            adapter_13f=mock_13f,
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        result = await aggregator.aggregate(
            quarter="2026-Q2",
            holdings_records=[],
        )
        assert result.signals == []
        assert len(result.errors) == 3

    @pytest.mark.asyncio
    async def test_aggregate_sorts_by_strength_then_date(self):
        """Signals are sorted: HIGH before MEDIUM before LOW; within same strength, newest first."""
        mock_13f = AsyncMock()
        mock_13f.to_signals.return_value = []
        mock_news = AsyncMock()
        mock_news.fetch.return_value = [
            make_signal("Old High News", "news", strength=SignalStrength.HIGH, offset_days=-30),
            make_signal("New Low News", "news", strength=SignalStrength.LOW, offset_days=-1),
            make_signal("Old Medium News", "news", strength=SignalStrength.MEDIUM, offset_days=-60),
            make_signal("New High News", "news", strength=SignalStrength.HIGH, offset_days=-1),
        ]
        mock_8k = AsyncMock()
        mock_8k.fetch.return_value = []

        aggregator = SignalAggregator(
            adapter_13f=mock_13f,
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        result = await aggregator.aggregate(
            quarter="2026-Q2",
            holdings_records=[],
        )
        strengths = [s.strength for s in result.signals]
        # HIGH signals come before MEDIUM before LOW
        assert strengths[0] == SignalStrength.HIGH
        assert strengths[1] == SignalStrength.HIGH
        assert strengths[2] == SignalStrength.MEDIUM
        assert strengths[3] == SignalStrength.LOW

    @pytest.mark.asyncio
    async def test_close_releases_resources(self):
        mock_news = AsyncMock()
        mock_8k = AsyncMock()
        aggregator = SignalAggregator(
            adapter_13f=AsyncMock(),
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        await aggregator.close()
        mock_news.close.assert_awaited_once()
        mock_8k.close.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_aggregator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
"""Signal aggregation engine — merge, dedup, sort signals from all sources."""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.signals.base import Signal, SignalStrength
from src.signals.13f_adapter import ThirteenthFSignalAdapter
from src.signals.news_source import NewsSource
from src.signals.sec_8k_source import Sec8kSource

logger = logging.getLogger(__name__)


@dataclass
class AggregationResult:
    """Output of a signal aggregation run."""

    signals: List[Signal] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    source_status: Dict[str, str] = field(default_factory=dict)


class SignalAggregator:
    """Orchestrate multi-source signal fetching, merging, and deduplication."""

    def __init__(
        self,
        adapter_13f: Optional[ThirteenthFSignalAdapter] = None,
        news_source: Optional[NewsSource] = None,
        sec8k_source: Optional[Sec8kSource] = None,
    ) -> None:
        self.adapter_13f = adapter_13f or ThirteenthFSignalAdapter()
        self.news_source = news_source
        self.sec8k_source = sec8k_source

    async def aggregate(
        self,
        quarter: str,
        holdings_records: List[Dict[str, Any]],
        comparison: Optional[Dict[str, Any]] = None,
    ) -> AggregationResult:
        """Fetch all sources in parallel, merge, dedup, sort."""
        result = AggregationResult()
        all_signals: List[Signal] = []

        # 13F: synchronous conversion (no async needed)
        try:
            signals_13f = self.adapter_13f.to_signals(holdings_records, quarter, comparison)
            all_signals.extend(signals_13f)
            result.source_status["13F"] = "ok"
        except Exception as exc:
            logger.exception("13F adapter failed")
            result.errors.append(f"13F 信号转换失败: {exc}")
            result.source_status["13F"] = "error"

        # News + 8-K: parallel async fetch
        news_task = None
        sec8k_task = None

        if self.news_source:
            news_task = asyncio.create_task(self._safe_fetch(
                self.news_source, quarter, "news", result,
            ))
        if self.sec8k_source:
            sec8k_task = asyncio.create_task(self._safe_fetch(
                self.sec8k_source, quarter, "8-K", result,
            ))

        if news_task:
            news_signals = await news_task
            all_signals.extend(news_signals)
        if sec8k_task:
            sec8k_signals = await sec8k_task
            all_signals.extend(sec8k_signals)

        # Dedup by (source, title)
        seen: set = set()
        deduped: List[Signal] = []
        for s in all_signals:
            if s.dedupe_key not in seen:
                seen.add(s.dedupe_key)
                deduped.append(s)

        # Sort: strength (HIGH→LOW), then date (newest first)
        strength_order = {SignalStrength.HIGH: 0, SignalStrength.MEDIUM: 1, SignalStrength.LOW: 2}
        deduped.sort(key=lambda s: (strength_order.get(s.strength, 2), -s.published_at.timestamp()))

        result.signals = deduped
        return result

    async def _safe_fetch(
        self,
        source: Any,
        quarter: str,
        source_name: str,
        result: AggregationResult,
    ) -> List[Signal]:
        """Fetch from one source, catching all errors so one failure doesn't block others."""
        try:
            signals = await source.fetch(quarter)
            result.source_status[source_name] = "ok"
            return signals
        except Exception as exc:
            logger.exception("%s source failed", source_name)
            result.errors.append(f"{source_name} 信号获取失败: {exc}")
            result.source_status[source_name] = "error"
            return []

    async def close(self) -> None:
        """Release all source resources."""
        if self.news_source:
            await self.news_source.close()
        if self.sec8k_source:
            await self.sec8k_source.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/signals/test_aggregator.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/signals/aggregator.py tests/signals/test_aggregator.py
git commit -m "feat(signals): add SignalAggregator with merge, dedup and fault tolerance"
```

---

### Task 6: SignalScorer

**Files:**
- Create: `src/signals/scorer.py`
- Create: `tests/signals/test_scorer.py`

**Interfaces:**
- Consumes: `Signal`, `SignalStrength` from `src.signals.base`
- Produces: `SignalScorer.score(signals: list[Signal]) -> list[ScoredSignal]`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for src.signals.scorer."""
from datetime import datetime, timedelta, timezone

import pytest

from src.signals.base import Signal, SignalStrength
from src.signals.scorer import ScoredSignal, SignalScorer


NOW = datetime(2026, 5, 20, tzinfo=timezone.utc)


def make_signal(title, source, days_ago=0):
    return Signal(
        title=title,
        source=source,
        published_at=NOW - timedelta(days=days_ago),
        summary=f"Summary for {title}",
        companies=["TEST"],
        strength=SignalStrength.MEDIUM,
    )


class TestSignalScorer:
    def test_score_assigns_recent_signals_higher(self):
        """More recent signals should score higher."""
        scorer = SignalScorer(reference_date=NOW)
        recent = make_signal("Recent", "news", days_ago=1)
        old = make_signal("Old", "news", days_ago=60)
        signals = [recent, old]
        scored = scorer.score(signals)
        assert scored[0].relevance_score > scored[1].relevance_score

    def test_score_assigns_high_strength_higher_weight(self):
        """HIGH strength signals get higher base weight."""
        scorer = SignalScorer(reference_date=NOW)
        high = Signal(
            title="High",
            source="news",
            published_at=NOW - timedelta(days=5),
            summary="Summary",
            companies=["TEST"],
            strength=SignalStrength.HIGH,
        )
        low = Signal(
            title="Low",
            source="news",
            published_at=NOW - timedelta(days=5),
            summary="Summary",
            companies=["TEST"],
            strength=SignalStrength.LOW,
        )
        scored = scorer.score([high, low])
        assert scored[0].relevance_score > scored[1].relevance_score

    def test_score_cross_source_signals_rank_higher(self):
        """Multiple sources covering same company = cross-validation signal."""
        scorer = SignalScorer(reference_date=NOW)
        s1 = make_signal("Signal A", "news", days_ago=3)
        s2 = make_signal("Signal B", "8-K", days_ago=5)
        # Same company mentioned in both = cross-signal
        signals = [s1, s2]
        scored = scorer.score(signals)
        # At least one should have cross_refs populated
        assert any(s.cross_refs for s in scored)

    def test_score_single_signal_no_cross_ref(self):
        """Single signal with no crossover should have empty cross_refs."""
        scorer = SignalScorer(reference_date=NOW)
        signals = [make_signal("Only Signal", "news", days_ago=1)]
        scored = scorer.score(signals)
        assert scored[0].cross_refs == []

    def test_score_empty_input(self):
        scorer = SignalScorer()
        assert scorer.score([]) == []

    def test_score_assigns_final_strength(self):
        """Score thresholds map to final strengths."""
        scorer = SignalScorer(reference_date=NOW)
        signals = [
            make_signal("S1", "news", days_ago=1),
            make_signal("S2", "news", days_ago=30),
            make_signal("S3", "news", days_ago=90),
        ]
        scored = scorer.score(signals)
        # All three signals get a final_strength assigned
        for s in scored:
            assert s.final_strength in (
                SignalStrength.HIGH,
                SignalStrength.MEDIUM,
                SignalStrength.LOW,
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_scorer.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
"""Rule-based signal scoring engine."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

STRENGTH_WEIGHT: Dict[SignalStrength, float] = {
    SignalStrength.HIGH: 3.0,
    SignalStrength.MEDIUM: 1.5,
    SignalStrength.LOW: 0.5,
}
SOURCE_CREDIBILITY: Dict[str, float] = {
    "13F": 1.2,   # SEC filing, authoritative
    "8-K": 1.2,   # SEC filing, authoritative
    "news": 0.8,  # news, subject to media bias
}
DECAY_HALF_LIFE_DAYS = 14.0  # relevance halves every 14 days
CROSS_SIGNAL_BONUS = 2.0  # bonus per additional source mentioning same company
STRENGTH_THRESHOLD_HIGH = 6.0
STRENGTH_THRESHOLD_MEDIUM = 3.0


@dataclass
class ScoredSignal:
    """A Signal with computed relevance score and final strength."""

    signal: Signal
    relevance_score: float
    final_strength: SignalStrength
    cross_refs: List[str] = field(default_factory=list)


class SignalScorer:
    """Compute relevance scores and cross-source signal detection."""

    def __init__(self, reference_date: Optional[datetime] = None) -> None:
        self.reference_date = reference_date or datetime.now(timezone.utc)

    def score(self, signals: List[Signal]) -> List[ScoredSignal]:
        """Score and rank signals by relevance."""
        if not signals:
            return []

        # Build company → signal index for cross-reference detection
        company_index: Dict[str, List[Signal]] = {}
        for s in signals:
            for company in s.companies:
                company_lower = company.lower()
                company_index.setdefault(company_lower, []).append(s)

        scored: List[ScoredSignal] = []
        for signal in signals:
            score = self._compute_raw_score(signal)
            cross_refs = self._find_cross_refs(signal, company_index)

            # Cross-signal bonus
            if cross_refs:
                score += CROSS_SIGNAL_BONUS * len(cross_refs)

            final_strength = self._threshold(score)
            scored.append(ScoredSignal(
                signal=signal,
                relevance_score=round(score, 2),
                final_strength=final_strength,
                cross_refs=cross_refs,
            ))

        # Sort by relevance score descending
        scored.sort(key=lambda x: x.relevance_score, reverse=True)
        return scored

    def _compute_raw_score(self, signal: Signal) -> float:
        """Compute base score from time decay + source credibility + strength weight."""
        # Time decay
        age_days = (self.reference_date - signal.published_at).total_seconds() / 86400.0
        age_days = max(0.0, age_days)
        time_factor = 2.0 ** (-age_days / DECAY_HALF_LIFE_DAYS)

        # Source credibility weight
        credibility = SOURCE_CREDIBILITY.get(signal.source, 1.0)

        # Signal's own strength weight
        strength_w = STRENGTH_WEIGHT.get(signal.strength, 1.0)

        return time_factor * credibility * strength_w * 3.0

    def _find_cross_refs(self, signal: Signal, company_index: Dict[str, List[Signal]]) -> List[str]:
        """Find other signals that mention the same companies (cross-source validation)."""
        refs: set = set()
        for company in signal.companies:
            related = company_index.get(company.lower(), [])
            for other in related:
                if other.id != signal.id and other.source != signal.source:
                    refs.add(other.id)
        return sorted(refs)

    @staticmethod
    def _threshold(score: float) -> SignalStrength:
        if score >= STRENGTH_THRESHOLD_HIGH:
            return SignalStrength.HIGH
        elif score >= STRENGTH_THRESHOLD_MEDIUM:
            return SignalStrength.MEDIUM
        return SignalStrength.LOW
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/signals/test_scorer.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/signals/scorer.py tests/signals/test_scorer.py
git commit -m "feat(signals): add SignalScorer with time-decay relevance ranking"
```

---

### Task 7: Pipeline Integration (main.py + reporter.py)

**Files:**
- Modify: `src/main.py` — add signal aggregation after existing 13F pipeline
- Modify: `src/reporter.py` — accept signals parameter and pass to template
- Modify: `tests/test_main.py` — add integration test with mocked signal sources
- Modify: `tests/test_reporter.py` — verify signals passed to template

**Interfaces:**
- Consumes: `SignalAggregator`, `AggregationResult` from signals package
- Produces: Updated `run_pipeline()` and `ReportGenerator.generate_report()`

- [ ] **Step 1: Write integration test**

In `tests/test_main.py`, add:

```python
@pytest.mark.asyncio
async def test_run_pipeline_aggregates_signals(tmp_path, monkeypatch):
    """Pipeline should aggregate signals from all sources."""
    monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)

    mock_df = pd.DataFrame(
        {
            "cusip": ["A"],
            "name_of_issuer": ["Apple"],
            "title_of_class": ["COM"],
            "value": [1000000.0],
            "shares": [1000],
            "investment_discretion": ["SOLE"],
        }
    )

    async def fake_fetch(filing_info):
        filing_info["report_date"] = "2026-06-30"
        return mock_df

    with patch("src.main.SEC13FFetcher") as MockFetcher:
        MockFetcher.report_date_to_quarter = SEC13FFetcher.report_date_to_quarter
        instance = MockFetcher.return_value.__aenter__.return_value
        instance.fetch_latest_holdings = fake_fetch
        with patch("src.main.save_holdings"):
            with patch("src.main.GSAnalyzer") as MockAnalyzer:
                analyzer = MockAnalyzer.return_value
                analyzer.analyze_holdings = AsyncMock(return_value=MagicMock())
                with patch("src.main.ReportGenerator") as MockReporter:
                    reporter = MockReporter.return_value
                    reporter.generate_report = lambda *args, **kwargs: tmp_path / "2026-Q2.html"
                    with patch("src.main.SignalAggregator") as MockAgg:
                        mock_agg = MockAgg.return_value
                        mock_result = MagicMock()
                        mock_result.signals = []
                        mock_result.errors = []
                        mock_result.source_status = {"13F": "ok"}
                        mock_agg.aggregate = AsyncMock(return_value=mock_result)
                        mock_agg.close = AsyncMock()

                        with patch("src.main.FEISHU_WEBHOOK", ""):
                            with patch("src.main.get_holdings", return_value=[]):
                                await run_pipeline()
                                # SignalAggregator should be called
                                mock_agg.aggregate.assert_awaited_once()
                                mock_agg.close.assert_awaited_once()
```

Run: `pytest tests/test_main.py::test_run_pipeline_aggregates_signals -v`
Expected: FAIL — `ImportError: cannot import name 'SignalAggregator'`

- [ ] **Step 2: Write reporter test**

In `tests/test_reporter.py`, add:

```python
def test_generate_report_accepts_signals(sample_holdings_df, tmp_path, monkeypatch):
    monkeypatch.setattr("src.reporter.REPORT_OUTPUT_DIR", tmp_path)

    class FakeAnalysis:
        summary = "test"
        concentration_analysis = "test"
        top_holdings_analysis = "test"
        sector_preference = "test"
        trading_signals = "test"
        risk_warnings = "test"
        retail_insights = "test"
        key_tickers = ["AAPL"]
        sentiment = "neutral"
        confidence = 0.8

    reporter = ReportGenerator()
    path = reporter.generate_report(
        quarter="2026-Q2",
        holdings_df=sample_holdings_df,
        analysis=FakeAnalysis(),
        signals=[],
        signal_errors=[],
        source_status={},
    )
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    # Report should render without signal panel crash
    assert "2026-Q2" in content
```

Run: `pytest tests/test_reporter.py::test_generate_report_accepts_signals -v`
Expected: FAIL — `generate_report() got unexpected keyword argument 'signals'`

- [ ] **Step 3: Implement pipeline integration**

In `src/main.py`, add after imports:

```python
from src.signals.aggregator import SignalAggregator
from src.signals.news_source import NewsSource
from src.signals.sec_8k_source import Sec8kSource
from src.config import RSS_FEEDS  # noqa: F401
```

In `run_pipeline()`, add after `reporter.generate_report()` line (before the notification block), replace the reporter call with:

```python
    # --- Multi-source signal aggregation ---
    aggregator = SignalAggregator(
        news_source=NewsSource(rss_urls=RSS_FEEDS),
        sec8k_source=Sec8kSource(),
    )
    try:
        aggregation = await aggregator.aggregate(quarter, df.to_dict("records"), summary)
        logger.info(
            "Aggregated %d signals from sources: %s (errors: %d)",
            len(aggregation.signals),
            aggregation.source_status,
            len(aggregation.errors),
        )
    except Exception:
        logger.exception("Signal aggregation failed; report will lack signal panel")
        aggregation = None  # type: ignore[assignment]
    finally:
        await aggregator.close()

    reporter = ReportGenerator()
    report_path = await asyncio.to_thread(
        reporter.generate_report,
        quarter,
        df,
        analysis,
        signals=aggregation.signals if aggregation else [],
        signal_errors=aggregation.errors if aggregation else [],
        source_status=aggregation.source_status if aggregation else {},
    )
    logger.info("Report generated at %s", report_path)
```

Remove the earlier `reporter = ReportGenerator()` and `report_path = ...` lines that were above the signal aggregation block.

- [ ] **Step 4: Implement reporter changes**

In `src/reporter.py`, update `generate_report()` signature:

```python
    def generate_report(
        self,
        quarter: str,
        holdings_df: pd.DataFrame,
        analysis: AnalysisResult,
        output_path: Optional[Path] = None,
        signals: Optional[list] = None,
        signal_errors: Optional[list] = None,
        source_status: Optional[dict] = None,
    ) -> Path:
```

And update the `template.render()` call:

```python
        rendered = template.render(
            quarter=quarter,
            holdings=holdings_df.to_dict(orient="records"),
            analysis=analysis,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            signals=signals or [],
            signal_errors=signal_errors or [],
            source_status=source_status or {},
        )
```

- [ ] **Step 5: Run all tests to verify**

Run: `pytest tests/test_main.py tests/test_reporter.py tests/signals/ -v`
Expected: All tests PASS (including 63 existing + all new signal tests)

- [ ] **Step 6: Commit**

```bash
git add src/main.py src/reporter.py tests/test_main.py tests/test_reporter.py
git commit -m "feat(main): integrate signal aggregation into pipeline"
```

---

### Task 8: HTML Signal Panel Template

**Files:**
- Modify: `templates/report.html` — add signal panel section

**Interfaces:**
- Consumes: Jinja2 variables `signals`, `signal_errors`, `source_status`

- [ ] **Step 1: Test that signal data renders in template**

In `tests/test_reporter.py`, expand `test_generate_report_accepts_signals` to also check for signal content:

```python
def test_generate_report_renders_signal_panel(sample_holdings_df, tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from src.signals.base import Signal, SignalStrength

    monkeypatch.setattr("src.reporter.REPORT_OUTPUT_DIR", tmp_path)

    class FakeAnalysis:
        summary = "test"
        concentration_analysis = "test"
        top_holdings_analysis = "test"
        sector_preference = "test"
        trading_signals = "test"
        risk_warnings = "test"
        retail_insights = "test"
        key_tickers = ["AAPL"]
        sentiment = "neutral"
        confidence = 0.8

    test_signals = [
        Signal(
            title="高盛增持 Apple",
            source="13F",
            published_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
            summary="高盛增持 Apple 5%，持仓市值 $10B",
            companies=["Apple"],
            strength=SignalStrength.HIGH,
        ),
    ]

    reporter = ReportGenerator()
    path = reporter.generate_report(
        quarter="2026-Q2",
        holdings_df=sample_holdings_df,
        analysis=FakeAnalysis(),
        signals=test_signals,
        signal_errors=[],
        source_status={"13F": "ok", "news": "error", "8-K": "ok"},
    )
    content = path.read_text(encoding="utf-8")
    assert "多源信号" in content
    assert "高盛增持 Apple" in content
    assert "高" in content  # HIGH strength indicator
    assert "不可用" in content or "news" in content.lower()  # degraded source status
```

Run: `pytest tests/test_reporter.py::test_generate_report_renders_signal_panel -v`
Expected: FAIL — signal content not found in existing template

- [ ] **Step 2: Add signal panel to template**

In `templates/report.html`, add the signal panel section before the closing `</body>` or after the main analysis section. Insert this Jinja2 block:

```html
<!-- 多源信号面板 -->
{% if signals %}
<section class="signal-panel">
    <h2>📡 多源信号面板</h2>

    <!-- Source Status -->
    <div class="source-status">
        {% for src, status in source_status.items() %}
        <span class="status-badge status-{{ status }}">
            {{ src }}: {% if status == 'ok' %}✅{% else %}⚠️ 暂不可用{% endif %}
        </span>
        {% endfor %}
    </div>

    {% if signal_errors %}
    <div class="signal-errors">
        <p>⚠️ 部分信号源获取失败：</p>
        <ul>
            {% for err in signal_errors %}
            <li>{{ err }}</li>
            {% endfor %}
        </ul>
    </div>
    {% endif %}

    <!-- Signal List -->
    <div class="signal-list">
        {% set strength_groups = {} %}
        {% for sig in signals %}
            {% set _ = strength_groups.setdefault(sig.strength.value, []).append(sig) %}
        {% endfor %}

        {% for level in ['high', 'medium', 'low'] %}
        {% set group = strength_groups.get(level, []) %}
        {% if group %}
        <div class="signal-group signal-{{ level }}">
            <h3>
                {% if level == 'high' %}🔴 高优先级信号
                {% elif level == 'medium' %}🟡 中优先级信号
                {% else %}🟢 低优先级信号
                {% endif %}
                ({{ group|length }})
            </h3>
            {% for sig in group %}
            <div class="signal-card">
                <div class="signal-header">
                    <span class="signal-source source-{{ sig.source }}">{{ sig.source }}</span>
                    <span class="signal-date">{{ sig.published_at.strftime('%Y-%m-%d') }}</span>
                </div>
                <h4>{{ sig.title }}</h4>
                <p class="signal-summary">{{ sig.summary }}</p>
                <div class="signal-meta">
                    {% if sig.companies %}
                    <span class="signal-tickers">
                        相关公司: {{ sig.companies|join(', ') }}
                    </span>
                    {% endif %}
                    {% if sig.cross_refs %}
                    <span class="cross-signal-badge">🔗 交叉信号</span>
                    {% endif %}
                    {% if sig.url %}
                    <a href="{{ sig.url }}" target="_blank" rel="noopener">查看原文 →</a>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>
        {% endif %}
        {% endfor %}
    </div>
</section>
{% elif signal_errors %}
<section class="signal-panel signal-degraded">
    <h2>📡 多源信号面板</h2>
    <p>⚠️ 所有信号源暂时不可用，请稍后重试。</p>
</section>
{% endif %}

<!-- End 多源信号面板 -->
```

- [ ] **Step 3: Run test to verify**

Run: `pytest tests/test_reporter.py::test_generate_report_renders_signal_panel -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add templates/report.html tests/test_reporter.py
git commit -m "feat(reporter): add multi-source signal panel to HTML template"
```

---

### Task 9: Full Regression + Code Quality

**Files:**
- All files created/modified in Tasks 1-8

- [ ] **Step 1: Run full test suite**

Run: `pytest -v`
Expected: All tests PASS (63 existing + ~35 new signal tests = ~98 total)

- [ ] **Step 2: Check code quality**

Run: `flake8 src/signals/ tests/signals/ src/main.py src/reporter.py`
Expected: No errors

Run: `mypy src/signals/ --ignore-missing-imports`
Expected: No errors (or known pandas/feedparser missing stub warnings)

- [ ] **Step 3: Add feedparser to dependencies**

In `pyproject.toml`, add `feedparser` to the dependencies list if not already present.

Run: `pip install feedparser`

- [ ] **Step 4: Final commit**

```bash
git add pyproject.toml
git commit -m "chore(deps): add feedparser for RSS parsing

Full test suite: ~98 tests passing, flake8 + mypy clean."
```
