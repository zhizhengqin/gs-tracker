"""Tests for src.signals.13f_adapter."""
from datetime import datetime, timezone

import pytest

from src.signals.base import Signal, SignalStrength
from src.signals.thirteenf_adapter import ThirteenthFSignalAdapter


class TestThirteenthFSignalAdapter:
    def test_to_signals_converts_top_holdings(self):
        adapter = ThirteenthFSignalAdapter()
        records = [
            {
                "name_of_issuer": "Apple Inc",
                "cusip": "037833100",
                "value": 10_000_000_000.0,
                "shares": 100_000,
                "title_of_class": "COM",
            },
        ]
        comparison = {
            "total_value": 500_000_000_000.0,
            "new_positions": 3,
            "sold_positions": 1,
            "increased_positions": 5,
            "decreased_positions": 2,
        }
        signals = adapter.to_signals(records, "2026-Q1", comparison)
        assert len(signals) >= 1
        top_signal = signals[0]
        assert "Apple" in top_signal.title
        assert top_signal.source == "13F"
        assert top_signal.strength in (SignalStrength.HIGH, SignalStrength.MEDIUM)

    def test_to_signals_empty_records_returns_empty_list(self):
        adapter = ThirteenthFSignalAdapter()
        signals = adapter.to_signals([], "2026-Q1", None)
        assert signals == []

    def test_to_signals_without_comparison(self):
        adapter = ThirteenthFSignalAdapter()
        records = [
            {"name_of_issuer": "Apple Inc", "value": 10_000_000_000.0},
        ]
        signals = adapter.to_signals(records, "2026-Q1", None)
        assert len(signals) >= 1

    def test_to_signals_limits_to_top_n(self):
        adapter = ThirteenthFSignalAdapter(max_signals=3)
        records = [
            {"name_of_issuer": f"Company {i}", "value": float(1000 - i * 10)}
            for i in range(20)
        ]
        signals = adapter.to_signals(records, "2026-Q1", None)
        assert len(signals) <= 3

    def test_to_signals_sorts_by_value_descending(self):
        adapter = ThirteenthFSignalAdapter(max_signals=5)
        records = [
            {"name_of_issuer": "Small Co", "value": 100.0},
            {"name_of_issuer": "Big Co", "value": 1_000_000_000.0},
            {"name_of_issuer": "Medium Co", "value": 500_000.0},
        ]
        signals = adapter.to_signals(records, "2026-Q1", None)
        assert signals[0].companies[0] == "Big Co"
        assert signals[1].companies[0] == "Medium Co"
        assert signals[2].companies[0] == "Small Co"

    def test_signal_published_at_uses_quarter_end(self):
        adapter = ThirteenthFSignalAdapter()
        records = [{"name_of_issuer": "Apple Inc", "value": 100.0}]
        signals = adapter.to_signals(records, "2026-Q1", None)
        expected = datetime(2026, 3, 31, tzinfo=timezone.utc)
        assert signals[0].published_at.date() == expected.date()
