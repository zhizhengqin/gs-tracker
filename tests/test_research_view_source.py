"""Tests for research_view GS Insights source."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.signals.research_view_source import (
    ResearchViewSource,
    _extract_first,
    _title_from_url,
)

SITEMAP_ONE = '<?xml version="1.0"?><urlset><url><loc>https://www.goldmansachs.com/insights/articles/test-art</loc></url></urlset>'

SITEMAP_MULTI = '<?xml version="1.0"?><urlset>\
<url><loc>https://www.goldmansachs.com/insights/articles/good</loc></url>\
<url><loc>https://www.goldmansachs.com/insights/articles/bad</loc></url>\
<url><loc>https://www.goldmansachs.com/insights/videos/skip</loc></url>\
</urlset>'

ARTICLE_GOOD = """<!DOCTYPE html><html><head>
<meta name="description" content="Test summary.">
<script type="application/ld+json">
{"headline":"Test Headline","datePublished":"2026-07-15T00:00:00"}
</script></head></html>"""


class TestTitleFromUrl:
    def test_slug_to_title(self):
        assert "The Fed Is Forecast To Cut Rates" == _title_from_url(
            "/insights/articles/the-fed-is-forecast-to-cut-rates"
        )

    def test_trailing_slash_handled(self):
        title = _title_from_url("/insights/articles/global-economy-2026/")
        assert "Global Economy 2026" in title


class TestResearchViewSource:
    @pytest.mark.asyncio
    async def test_extracts_from_html(self):
        """Core extraction logic: headline, date, description from static HTML."""
        source = ResearchViewSource(max_items=1)

        mock_get = AsyncMock()
        mock_get.side_effect = [
            _mock_httpx_response(200, SITEMAP_ONE),
            _mock_httpx_response(200, ARTICLE_GOOD),
        ]
        source.client.get = mock_get

        signals, wm = await source.fetch_since()
        await source.close()

        assert len(signals) == 1
        s = signals[0]
        assert s.source == "research_view"
        assert "Test Headline" in s.title
        assert s.published_at.year == 2026
        assert s.published_at.month == 7
        assert "Test summary" in (s.summary or "")

    @pytest.mark.asyncio
    async def test_filters_tracked_categories(self):
        """Videos/podcasts/careers URLs should be excluded."""
        source = ResearchViewSource(max_items=5)

        mock_get = AsyncMock()
        mock_get.side_effect = [
            _mock_httpx_response(200, SITEMAP_MULTI),
            _mock_httpx_response(200, ARTICLE_GOOD),
            _mock_httpx_response(500, ""),
        ]
        source.client.get = mock_get

        signals, _ = await source.fetch_since()
        await source.close()

        # 2 articles tracked + 1 video skipped → 2 signals (1 good + 1 failed)
        assert len(signals) == 1  # 'bad' article returns 500 → skipped

    @pytest.mark.asyncio
    async def test_respects_watermark(self):
        sitemap = '<?xml version="1.0"?><urlset>\
<url><loc>https://www.goldmansachs.com/insights/articles/newest</loc></url>\
<url><loc>https://www.goldmansachs.com/insights/articles/middle</loc></url>\
<url><loc>https://www.goldmansachs.com/insights/articles/oldest</loc></url>\
</urlset>'

        source = ResearchViewSource(max_items=10)
        mock_get = AsyncMock()
        mock_get.side_effect = [
            _mock_httpx_response(200, sitemap),
            _mock_httpx_response(200, ARTICLE_GOOD),
        ]
        source.client.get = mock_get

        signals, wm = await source.fetch_since(
            watermark="https://www.goldmansachs.com/insights/articles/middle"
        )
        await source.close()

        assert len(signals) == 1
        assert wm == "https://www.goldmansachs.com/insights/articles/newest"

    @pytest.mark.asyncio
    async def test_title_fallback_from_url(self):
        source = ResearchViewSource(max_items=1)
        no_headline_html = "<html><head></head><body>No schema here</body></html>"

        mock_get = AsyncMock()
        mock_get.side_effect = [
            _mock_httpx_response(200, SITEMAP_ONE),
            _mock_httpx_response(200, no_headline_html),
        ]
        source.client.get = mock_get

        signals, _ = await source.fetch_since()
        await source.close()

        assert len(signals) == 1
        assert "Test Art" in signals[0].title  # URL-derived fallback

    @pytest.mark.asyncio
    async def test_sitemap_error_returns_empty(self):
        source = ResearchViewSource()
        mock_get = AsyncMock()
        source.client.get = mock_get
        # Simulate httpx.HTTPError
        import httpx
        mock_get.side_effect = httpx.ConnectError("connection refused")

        signals, wm = await source.fetch_since(watermark="last-url")
        await source.close()

        assert signals == []
        assert wm == "last-url"


def _mock_httpx_response(status: int, text: str):
    """Create a mock httpx.Response that supports .text and .raise_for_status()."""
    import httpx
    req = httpx.Request("GET", "https://example.com")
    return httpx.Response(status, text=text, request=req)
