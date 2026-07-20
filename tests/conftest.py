"""Shared pytest configuration and fixtures."""
from datetime import datetime, timezone

import pytest

from src.signals.base import Signal, SignalStrength


@pytest.fixture
def sample_holdings_df():
    """Return a minimal sample holdings DataFrame."""
    import pandas as pd

    return pd.DataFrame(
        {
            "cusip": ["123456789", "987654321"],
            "name_of_issuer": ["Example Corp", "Another Inc"],
            "title_of_class": ["COM", "COM"],
            "value": [1000000.0, 500000.0],
            "shares": [10000, 5000],
            "investment_discretion": ["SOLE", "SOLE"],
        }
    )


@pytest.fixture
def make_signal():
    """Return a Signal factory with sensible defaults; kwargs override."""
    def _make(**overrides) -> Signal:
        defaults = dict(
            title="高盛增持苹果",
            source="13F",
            published_at=datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc),
            summary="苹果占组合 12.3%",
            companies=["AAPL"],
            strength=SignalStrength.HIGH,
            url="https://example.com/a",
            cross_refs=["news:高盛看好苹果"],
            id="sig00001",
        )
        defaults.update(overrides)
        return Signal(**defaults)

    return _make
