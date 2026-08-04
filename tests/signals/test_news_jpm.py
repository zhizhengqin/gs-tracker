"""Test NewsSource JPM keyword support."""
import re
from src.signals.news_source import NewsSource, _JPM_RE, _GS_RE, _JPM_VIEWPOINT_RE, _VIEWPOINT_RE

class TestNewsSourceJPM:
    def test_jpm_keywords_match(self):
        """JPM keyword regexes match JPM-related Chinese text."""
        assert any(rx.search("摩根大通上调中国股市评级至超配") for rx in _JPM_RE)
        assert any(rx.search("j.p. morgan says china stocks are cheap".lower()) for rx in _JPM_RE)
        assert not any(rx.search("高盛看好A股市场") for rx in _JPM_RE)

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
