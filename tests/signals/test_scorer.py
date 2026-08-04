"""Tests for src.signals.scorer."""
from datetime import datetime, timedelta, timezone


from src.signals.base import Signal, SignalStrength
from src.signals.scorer import SignalScorer


NOW = datetime(2026, 5, 20, tzinfo=timezone.utc)


def make_signal(title, source, days_ago=0, strength=None):
    return Signal(
        title=title,
        source=source,
        published_at=NOW - timedelta(days=days_ago),
        summary=f"Summary for {title}",
        companies=["TEST"],
        strength=strength or SignalStrength.MEDIUM,
    )


class TestSignalScorer:
    def test_score_assigns_recent_signals_higher(self):
        scorer = SignalScorer(reference_date=NOW)
        recent = make_signal("Recent", "news", days_ago=1)
        old = make_signal("Old", "news", days_ago=60)
        scored = scorer.score([recent, old])
        assert scored[0].relevance_score > scored[1].relevance_score

    def test_score_assigns_high_strength_higher_weight(self):
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
        scorer = SignalScorer(reference_date=NOW)
        s1 = Signal(
            title="Signal A",
            source="news",
            published_at=NOW - timedelta(days=3),
            summary="AAPL mentioned",
            companies=["AAPL"],
            strength=SignalStrength.MEDIUM,
        )
        s2 = Signal(
            title="Signal B",
            source="8-K",
            published_at=NOW - timedelta(days=5),
            summary="AAPL also here",
            companies=["AAPL"],
            strength=SignalStrength.MEDIUM,
        )
        scored = scorer.score([s1, s2])
        # At least one should have cross_refs populated (both mention AAPL)
        assert any(s.cross_refs for s in scored)

    def test_self_company_mentions_create_no_cross_refs(self):
        # A GS news item tagged "GS" must not pull in GS's own 8-K filings
        # as cross-references; self-mentions are noise, not shared views.
        scorer = SignalScorer(reference_date=NOW)
        s1 = Signal(
            title="GS outlook on S&P 500",
            source="news",
            published_at=NOW - timedelta(days=1),
            summary="macro view",
            companies=["GS"],
            strength=SignalStrength.MEDIUM,
        )
        s2 = Signal(
            title="GS 8-K filing",
            source="8-K",
            published_at=NOW - timedelta(days=2),
            summary="routine filing",
            companies=["GS"],
            strength=SignalStrength.MEDIUM,
        )
        scored = scorer.score([s1, s2])
        assert all(sc.cross_refs == [] for sc in scored)

    def test_score_single_signal_no_cross_ref(self):
        scorer = SignalScorer(reference_date=NOW)
        signals = [make_signal("Only Signal", "news", days_ago=1)]
        scored = scorer.score(signals)
        assert scored[0].cross_refs == []

    def test_score_empty_input(self):
        scorer = SignalScorer()
        assert scorer.score([]) == []

    def test_score_assigns_final_strength(self):
        scorer = SignalScorer(reference_date=NOW)
        signals = [
            make_signal("S1", "news", days_ago=1),
            make_signal("S2", "news", days_ago=30),
            make_signal("S3", "news", days_ago=90),
        ]
        scored = scorer.score(signals)
        for s in scored:
            assert s.final_strength in (
                SignalStrength.HIGH,
                SignalStrength.MEDIUM,
                SignalStrength.LOW,
            )


def _inst_signal(title, source, institution_id, companies=None, days_ago=0):
    """Signal factory with institution_id for cross-institution tests."""
    return Signal(
        title=title,
        source=source,
        published_at=NOW - timedelta(days=days_ago),
        summary=f"Summary for {title}",
        companies=companies or ["宁德时代"],
        strength=SignalStrength.MEDIUM,
        institution_id=institution_id,
    )


class TestCrossInstitution:
    """Cross-institution collision: same company covered by >=2 real institutions."""

    def test_flagged_when_two_institutions_share_company(self):
        gs = _inst_signal("高盛看好宁德时代", "news", "gs")
        jpm = _inst_signal("摩根大通上调宁德时代目标价", "news_jpm", "jpm")
        scored = SignalScorer(reference_date=NOW).score([gs, jpm])
        assert len(scored) == 2
        assert all(sc.cross_institutional for sc in scored)

    def test_same_institution_not_flagged(self):
        s1 = _inst_signal("高盛新闻提及宁德时代", "news", "gs")
        s2 = _inst_signal("高盛研究报告覆盖宁德时代", "research_view", "gs")
        scored = SignalScorer(reference_date=NOW).score([s1, s2])
        # Cross-source refs exist, but no cross-institution flag
        assert all(sc.cross_refs for sc in scored)
        assert not any(sc.cross_institutional for sc in scored)

    def test_aggregate_all_does_not_count_as_institution(self):
        gs = _inst_signal("高盛看好宁德时代", "news", "gs")
        qfii = _inst_signal("QFII 增持宁德时代", "qfii", "all")
        scored = SignalScorer(reference_date=NOW).score([gs, qfii])
        assert not any(sc.cross_institutional for sc in scored)

    def test_aggregate_signal_flagged_when_two_real_institutions_cover(self):
        gs = _inst_signal("高盛看好宁德时代", "news", "gs")
        jpm = _inst_signal("摩根大通上调宁德时代", "news_jpm", "jpm")
        qfii = _inst_signal("QFII 增持宁德时代", "qfii", "all")
        scored = SignalScorer(reference_date=NOW).score([gs, jpm, qfii])
        assert all(sc.cross_institutional for sc in scored)

    def test_cross_institution_boosts_score(self):
        gs = _inst_signal("高盛看好宁德时代", "news", "gs")
        jpm = _inst_signal("摩根大通上调宁德时代", "news_jpm", "jpm")
        solo = _inst_signal("高盛看好贵州茅台", "news", "gs",
                            companies=["贵州茅台"])
        scored = SignalScorer(reference_date=NOW).score([gs, jpm, solo])
        by_title = {sc.signal.title: sc for sc in scored}
        assert by_title["高盛看好宁德时代"].cross_institutional
        assert not by_title["高盛看好贵州茅台"].cross_institutional
        assert (by_title["高盛看好宁德时代"].relevance_score
                > by_title["高盛看好贵州茅台"].relevance_score)

    def test_company_matching_is_case_insensitive(self):
        gs = _inst_signal("GS covers AAPL", "news", "gs", companies=["AAPL"])
        jpm = _inst_signal("JPM covers Apple", "news_jpm", "jpm", companies=["aapl"])
        scored = SignalScorer(reference_date=NOW).score([gs, jpm])
        assert all(sc.cross_institutional for sc in scored)


class TestSelfTokenExclusion:
    """Institution-name tokens (GS/高盛/JPM/摩根大通) are not covered companies —
    they must not create fake cross-institution consensus."""

    def test_self_tokens_do_not_flag(self):
        gs = _inst_signal("高盛发布宏观研报", "news", "gs", companies=["GS"])
        jpm = _inst_signal("摩根大通新闻提到高盛", "news_jpm", "jpm", companies=["GS"])
        scored = SignalScorer(reference_date=NOW).score([gs, jpm])
        assert not any(sc.cross_institutional for sc in scored)

    def test_chinese_self_tokens_do_not_flag(self):
        gs = _inst_signal("高盛动态", "news", "gs", companies=["高盛"])
        jpm = _inst_signal("摩根大通动态", "news_jpm", "jpm", companies=["高盛"])
        scored = SignalScorer(reference_date=NOW).score([gs, jpm])
        assert not any(sc.cross_institutional for sc in scored)

    def test_real_company_still_flags_alongside_self_tokens(self):
        gs = _inst_signal("高盛看好宁德时代", "news", "gs", companies=["GS", "宁德时代"])
        jpm = _inst_signal("摩根大通看好宁德时代", "news_jpm", "jpm", companies=["JPM", "宁德时代"])
        scored = SignalScorer(reference_date=NOW).score([gs, jpm])
        assert all(sc.cross_institutional for sc in scored)
