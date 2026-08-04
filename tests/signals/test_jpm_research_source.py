"""Test JPM research-viewpoint source (RSS-based, viewpoint-filtered)."""
import pytest

from src.signals.base import SignalStrength
from src.signals.jpm_research_source import JPMResearchSource

RSS_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>{t1}</title><link>https://example.com/1</link>
<description>{d1}</description>
<pubDate>Mon, 03 Aug 2026 08:00:00 GMT</pubDate></item>
<item><title>{t2}</title><link>https://example.com/2</link>
<description>{d2}</description>
<pubDate>Mon, 03 Aug 2026 09:00:00 GMT</pubDate></item>
<item><title>{t3}</title><link>https://example.com/3</link>
<description>{d3}</description>
<pubDate>Mon, 03 Aug 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""

FEED = RSS_TMPL.format(
    t1="摩根大通上调中国股市评级至超配", d1="摩根大通预计A股盈利改善",
    t2="摩根大通CEO访华谈合作", d2="摩根大通集团业务动态",
    t3="高盛发布最新研报", d3="高盛预计美联储降息",
)


class _FakeResponse:
    text = FEED

    def raise_for_status(self):
        pass


class _FakeClient:
    async def get(self, url):
        return _FakeResponse()

    async def aclose(self):
        pass


class TestJPMResearchSource:
    def test_source_name(self):
        assert JPMResearchSource().source_name == "jpm_research"

    @pytest.mark.asyncio
    async def test_keeps_only_jpm_viewpoint_items(self):
        src = JPMResearchSource(rss_urls=["https://example.com/rss"])
        src.client = _FakeClient()
        signals = await src.fetch()

        # Item 1: JPM + viewpoint -> kept. Item 2: JPM mention only -> dropped.
        # Item 3: GS viewpoint -> dropped.
        assert len(signals) == 1
        s = signals[0]
        assert s.title.startswith("摩根大通研究: ")
        assert "上调中国股市评级" in s.title
        assert s.source == "jpm_research"
        assert s.institution_id == "jpm"
        assert s.strength == SignalStrength.HIGH

    @pytest.mark.asyncio
    async def test_no_feeds_returns_empty(self):
        src = JPMResearchSource(rss_urls=[])
        signals, wm = await src.fetch_since()
        assert signals == []
        assert wm is not None

    @pytest.mark.asyncio
    async def test_feed_failure_never_raises(self):
        import httpx

        class _BoomClient:
            async def get(self, url):
                raise httpx.ConnectError("boom")

            async def aclose(self):
                pass

        src = JPMResearchSource(rss_urls=["https://example.com/rss"])
        src.client = _BoomClient()
        signals, _ = await src.fetch_since()
        assert signals == []
