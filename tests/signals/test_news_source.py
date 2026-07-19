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


class TestNewsSource:
    @pytest.mark.asyncio
    async def test_fetch_parses_rss_items(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(text=SAMPLE_RSS, status_code=200)
        source = NewsSource(rss_urls=["https://example.com/rss"])
        signals = await source.fetch("2026-Q2")
        assert len(signals) == 2
        assert signals[0].source == "news"
        assert isinstance(signals[0].published_at, datetime)
        await source.close()

    @pytest.mark.asyncio
    async def test_fetch_handles_http_error(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(status_code=500)
        source = NewsSource(rss_urls=["https://example.com/rss"])
        signals = await source.fetch("2026-Q2")
        assert signals == []
        await source.close()

    @pytest.mark.asyncio
    async def test_fetch_handles_timeout(self, httpx_mock: HTTPXMock):
        import httpx
        httpx_mock.add_exception(httpx.TimeoutException("timed out"))
        source = NewsSource(rss_urls=["https://example.com/rss"])
        signals = await source.fetch("2026-Q2")
        assert signals == []
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
    async def test_fetch_filters_by_keywords(self, httpx_mock: HTTPXMock):
        mixed_rss = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item><title>Goldman Sachs News</title><link>https://a.com/1</link><description>GS related</description><pubDate>Mon, 15 May 2026 10:00:00 GMT</pubDate></item>
          <item><title>Unrelated Sports News</title><link>https://a.com/2</link><description>Sports</description><pubDate>Mon, 15 May 2026 10:00:00 GMT</pubDate></item>
          <item><title>Apple Earnings Report</title><link>https://a.com/3</link><description>AAPL beats estimates</description><pubDate>Mon, 15 May 2026 10:00:00 GMT</pubDate></item>
        </channel></rss>"""
        httpx_mock.add_response(text=mixed_rss, status_code=200)
        source = NewsSource(rss_urls=["https://example.com/rss"])
        signals = await source.fetch("2026-Q2")
        assert len(signals) == 2
        titles = [s.title for s in signals]
        assert any("Goldman" in t for t in titles)
        assert any("Apple" in t for t in titles)
        await source.close()
