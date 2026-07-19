"""Tests for src.signals.base."""
from datetime import datetime, timezone

import pytest

from src.signals.base import Signal, SignalStrength


class TestSignal:
    def test_signal_creation_with_required_fields(self):
        s = Signal(
            title="高盛增持 Apple 5%",
            source="13F",
            published_at=datetime(2026, 3, 31, tzinfo=timezone.utc),
            summary="高盛在 2026-Q1 增持 Apple 5%，持仓市值达到 $10B",
            companies=["AAPL"],
            strength=SignalStrength.HIGH,
        )
        assert s.title == "高盛增持 Apple 5%"
        assert s.source == "13F"
        assert s.companies == ["AAPL"]
        assert s.strength == SignalStrength.HIGH
        assert s.url is None
        assert s.cross_refs == []

    def test_signal_creation_with_all_fields(self):
        s = Signal(
            title="NVDA Q2 Earnings Beat",
            source="news",
            published_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
            summary="NVIDIA Q2 财报超预期，营收同比增长 120%",
            companies=["NVDA"],
            strength=SignalStrength.HIGH,
            url="https://example.com/nvda-q2",
            cross_refs=["sig-001"],
        )
        assert s.url == "https://example.com/nvda-q2"
        assert s.cross_refs == ["sig-001"]

    def test_signal_equality_by_id(self):
        s1 = Signal(
            title="Same Title",
            source="news",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            summary="Summary",
            companies=["AAPL"],
            strength=SignalStrength.LOW,
        )
        s2 = Signal(
            title="Same Title",
            source="news",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            summary="Summary",
            companies=["AAPL"],
            strength=SignalStrength.LOW,
        )
        assert s1.id != s2.id

    def test_signal_strength_enum_values(self):
        assert SignalStrength.HIGH.value == "high"
        assert SignalStrength.MEDIUM.value == "medium"
        assert SignalStrength.LOW.value == "low"

    def test_signal_dedupe_key(self):
        s = Signal(
            title="Test",
            source="news",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            summary="Summary",
            companies=["TEST"],
            strength=SignalStrength.LOW,
        )
        assert s.dedupe_key == ("news", "Test")
