"""News and sentiment monitoring."""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List

import httpx

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """A single news article."""

    title: str
    source: str
    link: str
    published_at: datetime
    summary: str
    keywords: List[str]


class NewsMonitor:
    """Monitor news related to Goldman Sachs and its holdings."""

    def __init__(self, rss_sources: List[str] = None) -> None:
        self.rss_sources = rss_sources or []
        self.client = httpx.AsyncClient(timeout=20.0)

    async def fetch_news(self, tickers: List[str] = None) -> List[NewsItem]:
        """Fetch recent news filtered by tickers/keywords."""
        raise NotImplementedError("TODO: implement news fetching")

    async def close(self) -> None:
        await self.client.aclose()
