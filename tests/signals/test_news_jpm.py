import pytest
"""Test NewsSource JPM keyword support."""
import re
from src.signals.news_source import NewsSource, _JPM_RE, _GS_RE, _JPM_VIEWPOINT_RE, _VIEWPOINT_RE

class TestNewsSourceJPM:
    def test_jpm_keywords_match(self):
        """JPM keyword regexes match JPM-related Chinese text."""
        assert any(rx.search("摩根大通上调中国股市评级至超配") for rx in _JPM_RE)
        assert any(rx.search("j.p. morgan says china stocks are cheap".lower()) for rx in _JPM_RE)
        assert not any(rx.search("高盛看好A股市场") for rx in _JPM_RE)

    def test_morgan_stanley_not_confused_with_jpm(self):
        """摩根士丹利 (Morgan Stanley, 大摩) must NOT match JPM keywords;
        小摩 is the Chinese shorthand for JPMorgan and must match."""
        assert not any(rx.search("摩根士丹利上调A股评级") for rx in _JPM_RE)
        assert not any(rx.search("大摩：恒指目标价上调") for rx in _JPM_RE)
        assert any(rx.search("小摩：看好中国消费板块") for rx in _JPM_RE)

    def test_jpm_viewpoint_keywords_match(self):
        """JPM viewpoint regexes identify JPM-authored content."""
        assert any(rx.search("摩根大通 研报：消费复苏超预期") for rx in _JPM_VIEWPOINT_RE)
        assert any(rx.search("jpmorgan upgrades alibaba to overweight".lower()) for rx in _JPM_VIEWPOINT_RE)
        assert not any(rx.search("高盛 研报：科技股估值过高") for rx in _JPM_VIEWPOINT_RE)

    def test_gs_keywords_still_work(self):
        """GS keywords still match GS content."""
        assert any(rx.search("高盛发布最新研报") for rx in _GS_RE)
        assert any(rx.search("高盛 维持 买入评级") for rx in _VIEWPOINT_RE)

    def test_institution_id_stored(self):
        """NewsSource stores institution_id."""
        ns_gs = NewsSource(institution_id="gs")
        ns_jpm = NewsSource(institution_id="jpm")
        assert ns_gs.institution_id == "gs"
        assert ns_jpm.institution_id == "jpm"


    def test_exclude_viewpoint_param_stored(self):
        """exclude_viewpoint flag is stored (news_jpm skips viewpoint items)."""
        ns = NewsSource(institution_id="jpm", exclude_viewpoint=True)
        assert ns.exclude_viewpoint is True
        assert NewsSource().exclude_viewpoint is False

    @pytest.mark.asyncio
    async def test_exclude_viewpoint_skips_viewpoint_items(self):
        """news_jpm with exclude_viewpoint drops viewpoint articles so they
        land only in jpm_research (no duplicates across the two sources)."""
        rss = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
        <item><title>摩根大通上调中国股市评级</title>
        <link>https://example.com/1</link><description>摩根大通预计A股走强</description></item>
        <item><title>摩根大通CEO访华</title>
        <link>https://example.com/2</link><description>业务交流</description></item>
        </channel></rss>"""

        class _Resp:
            text = rss
            def raise_for_status(self):
                pass

        class _Client:
            async def get(self, url):
                return _Resp()
            async def aclose(self):
                pass

        ns = NewsSource(
            rss_urls=["https://example.com/rss"],
            source_name="news_jpm",
            institution_id="jpm",
            exclude_viewpoint=True,
        )
        ns.client = _Client()
        signals = await ns.fetch("")
        titles = [s.title for s in signals]
        assert "摩根大通CEO访华" in titles
        assert not any("上调中国股市评级" in t for t in titles)
