"""Test QFII data source."""
import pytest
from src.signals.qfii_source import QFIISource


class TestQFIISource:
    def test_source_name(self):
        src = QFIISource()
        assert src.source_name == "qfii"

    def test_institution_id_stored(self):
        src = QFIISource()
        assert src.institution_id == "all"

    @pytest.mark.asyncio
    async def test_fetch_returns_signals(self):
        src = QFIISource(max_items=3)
        signals = await src.fetch("2026-Q2")
        assert isinstance(signals, list)
        if signals:
            s = signals[0]
            assert s.source == "qfii"
            assert s.institution_id == "all"

    @pytest.mark.asyncio
    async def test_fetch_since_watermark(self):
        src = QFIISource(max_items=3)
        sigs, wm = await src.fetch_since()
        assert isinstance(sigs, list)
        assert wm is not None or len(sigs) == 0
