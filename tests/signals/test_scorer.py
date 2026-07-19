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
