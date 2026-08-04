"""Test Signal institution_id field."""
from datetime import datetime, timezone
from src.signals.base import Signal, SignalStrength


class TestSignalInstitution:
    def test_default_institution_id(self):
        """New Signal defaults to institution_id='gs'."""
        s = Signal(
            title="Test",
            source="news",
            published_at=datetime.now(timezone.utc),
            summary="Test summary",
            companies=[],
            strength=SignalStrength.MEDIUM,
        )
        assert s.institution_id == "gs"

    def test_explicit_institution_id(self):
        """Signal can be created with explicit institution_id."""
        s = Signal(
            title="JPM Test",
            source="news",
            published_at=datetime.now(timezone.utc),
            summary="JPM summary",
            companies=[],
            strength=SignalStrength.HIGH,
            institution_id="jpm",
        )
        assert s.institution_id == "jpm"

    def test_dedupe_key_unchanged(self):
        """Dedupe key is still (source, title) — institution NOT included."""
        s1 = Signal(
            title="Same Title", source="news",
            published_at=datetime.now(timezone.utc),
            summary="", companies=[], strength=SignalStrength.LOW,
            institution_id="gs",
        )
        s2 = Signal(
            title="Same Title", source="news",
            published_at=datetime.now(timezone.utc),
            summary="", companies=[], strength=SignalStrength.LOW,
            institution_id="jpm",
        )
        # Same title+source → same dedupe key (by design: different institutions
        # on same topic IS the same signal for dedup purposes)
        assert s1.dedupe_key == s2.dedupe_key
