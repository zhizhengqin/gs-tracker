"""Tests for scripts/backfill_summaries.py (loaded by path; it is a tool script)."""
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "backfill_summaries.py"
_spec = importlib.util.spec_from_file_location("backfill_summaries", _SCRIPT)
bf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bf)


class TestExtractDescription:
    def test_name_before_content(self):
        html = '<html><head><meta name="description" content="高盛发布最新研报。"></head></html>'
        assert bf.extract_description(html) == "高盛发布最新研报。"

    def test_content_before_name(self):
        html = '<meta content="内容在前" name="description">'
        assert bf.extract_description(html) == "内容在前"

    def test_og_description_preferred(self):
        html = (
            '<meta name="description" content="普通描述">'
            '<meta property="og:description" content="OG 描述更长更完整">'
        )
        assert bf.extract_description(html) == "OG 描述更长更完整"

    def test_twitter_description_fallback(self):
        html = '<meta name="twitter:description" content="推特描述">'
        assert bf.extract_description(html) == "推特描述"

    def test_single_quotes_supported(self):
        html = "<meta name='description' content='单引号内容'>"
        assert bf.extract_description(html) == "单引号内容"

    def test_no_description_returns_none(self):
        assert bf.extract_description("<html><head><title>T</title></head></html>") is None

    def test_empty_content_returns_none(self):
        assert bf.extract_description('<meta name="description" content="">') is None


class TestLooksTruncated:
    @pytest.mark.parametrize("length,expected", [
        (200, True),
        (300, True),
        (150, False),
        (350, False),
    ])
    def test_length_detection(self, length, expected):
        summary = "字" * length
        assert bf.looks_truncated(summary) is expected

    def test_none_and_empty(self):
        assert bf.looks_truncated(None) is False
        assert bf.looks_truncated("") is False

    def test_ellipsis_ending_not_truncated(self):
        assert bf.looks_truncated("字" * 199 + "…") is False


class TestRssItemsFromXml:
    SAMPLE = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item><title>高盛研报</title><link>https://a.com/1</link>
      <description>&lt;p&gt;完整的第一段。&lt;/p&gt;完整的第二段，很长。</description></item>
      <item><title>无链接</title><description>没有链接的条目</description></item>
    </channel></rss>"""

    def test_maps_link_to_cleaned_summary(self):
        items = bf.rss_items_from_xml(self.SAMPLE)
        assert items == {"https://a.com/1": "完整的第一段。 完整的第二段，很长。"}

    def test_invalid_xml_returns_empty(self):
        assert bf.rss_items_from_xml("not xml <<<") == {}


class TestWscnArticle:
    def test_article_id_extraction(self):
        assert bf.wscn_article_id("https://wallstreetcn.com/articles/3778037") == "3778037"
        assert bf.wscn_article_id("https://www.goldmansachs.com/insights/x") is None

    def test_parse_prefers_full_content(self):
        payload = {"data": {"content": "<p>正文第一段。</p><p>正文第二段。</p>",
                            "content_short": "短摘要"}}
        assert bf.parse_wscn_article(payload) == "正文第一段。 正文第二段。"

    def test_parse_falls_back_to_content_short(self):
        payload = {"data": {"content": "", "content_short": "只有短摘要。"}}
        assert bf.parse_wscn_article(payload) == "只有短摘要。"

    def test_parse_empty_returns_none(self):
        assert bf.parse_wscn_article({"data": {}}) is None
        assert bf.parse_wscn_article({}) is None
