"""Tests for macro_view FRED signal source."""
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from src.signals.macro_view_source import MacroViewSource


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_all_sources_fail():
    source = MacroViewSource()
    source.api_key = ""
    # No FRED key + fallback also fails → all series return empty
    with patch.object(source, "_fetch_series", return_value=None):
        signals, wm = await source.fetch_since()
        assert signals == []
    await source.close()


@pytest.mark.asyncio
async def test_dgs10_bp_threshold_medium():
    """10bp change → MEDIUM signal: 4.35 - 4.23 = 0.12pp = 12bp"""
    source = MacroViewSource()
    source.api_key = "test-key"

    with patch.object(source, "_fetch_series") as mock_fetch:
        mock_fetch.side_effect = [
            # DGS10: 12bp change → MEDIUM
            {"observations": [
                {"date": "2026-07-20", "value": "4.35"},
                {"date": "2026-07-17", "value": "4.23"},
            ]},
            # VIXCLS: 1 observation → not enough
            {"observations": [{"date": "2026-07-20", "value": "15.0"}]},
            # DTWEXBGS: 1 observation → not enough
            {"observations": [{"date": "2026-07-20", "value": "125.0"}]},
        ]

        signals, wm = await source.fetch_since()

    dgs_signals = [s for s in signals if "10Y Treasury" in s.title]
    assert len(dgs_signals) == 1
    assert dgs_signals[0].strength.value == "medium"
    assert dgs_signals[0].companies == []
    assert "↑12.0bp" in dgs_signals[0].title
    await source.close()


@pytest.mark.asyncio
async def test_dgs10_bp_threshold_high():
    """≥20bp change → HIGH signal: 4.45 - 4.23 = 0.22pp = 22bp"""
    source = MacroViewSource()
    source.api_key = "test-key"

    with patch.object(source, "_fetch_series") as mock_fetch:
        mock_fetch.side_effect = [
            {"observations": [
                {"date": "2026-07-20", "value": "4.45"},
                {"date": "2026-07-17", "value": "4.23"},
            ]},
            {"observations": []},
            {"observations": []},
        ]

        signals, wm = await source.fetch_since()

    dgs_signals = [s for s in signals if "10Y Treasury" in s.title]
    assert dgs_signals[0].strength.value == "high"
    assert "↑22.0bp" in dgs_signals[0].title
    await source.close()


@pytest.mark.asyncio
async def test_no_signal_below_threshold():
    """<10bp change → no signal: 4.24 - 4.23 = 0.01pp = 1bp"""
    source = MacroViewSource()
    source.api_key = "test-key"

    with patch.object(source, "_fetch_series") as mock_fetch:
        mock_fetch.side_effect = [
            {"observations": [
                {"date": "2026-07-20", "value": "4.24"},
                {"date": "2026-07-17", "value": "4.23"},
            ]},
            {"observations": []},
            {"observations": []},
        ]

        signals, _ = await source.fetch_since()

    assert signals == []
    await source.close()


@pytest.mark.asyncio
async def test_respects_watermark():
    """Observations on or before watermark date are skipped."""
    source = MacroViewSource()
    source.api_key = "test-key"

    with patch.object(source, "_fetch_series") as mock_fetch:
        mock_fetch.side_effect = [
            {"observations": [
                {"date": "2026-07-20", "value": "4.45"},
                {"date": "2026-07-17", "value": "4.23"},
            ]},
            {"observations": []},
            {"observations": []},
        ]

        signals, wm = await source.fetch_since(watermark="2026-07-20")

    # Both latest dates ≤ watermark → no signal
    assert signals == []
    await source.close()


@pytest.mark.asyncio
async def test_vix_pct_threshold():
    """VIX 20% daily change → MEDIUM."""
    source = MacroViewSource()
    source.api_key = "test-key"

    with patch.object(source, "_fetch_series") as mock_fetch:
        mock_fetch.side_effect = [
            {"observations": []},  # DGS10 empty
            {  # VIXCLS: 18 → 21.6 = +20% → MEDIUM
                "observations": [
                    {"date": "2026-07-20", "value": "21.6"},
                    {"date": "2026-07-17", "value": "18.0"},
                ],
            },
            {"observations": []},  # DTWEXBGS empty
        ]

        signals, _ = await source.fetch_since()

    vix_signals = [s for s in signals if "VIX" in s.title]
    assert len(vix_signals) == 1
    assert vix_signals[0].strength.value == "medium"
    assert "↑20.0%" in vix_signals[0].title
    await source.close()


@pytest.mark.asyncio
async def test_fallback_eastmoney_without_fred_key():
    """Without FRED_API_KEY, DGS10 should use East Money fallback."""
    source = MacroViewSource()
    source.api_key = ""  # no FRED key

    with patch.object(source, "_fetch_series_fallback") as mock_fb:
        mock_fb.return_value = {
            "observations": [
                {"date": "2026-07-20", "value": "4.35"},
                {"date": "2026-07-17", "value": "4.23"},
            ]
        }
        # The real _fetch_series tries FRED first (fails — no key),
        # then calls _fetch_series_fallback for DGS10.
        # VIX and DTWEXBGS have no fallback → return None.
        signals, wm = await source.fetch_since()

    dgs_signals = [s for s in signals if "10Y Treasury" in s.title]
    assert len(dgs_signals) == 1
    assert dgs_signals[0].strength.value == "medium"
    await source.close()


@pytest.mark.asyncio
async def test_fallback_returns_none_for_non_dgs10():
    """East Money fallback only supports DGS10 — VIX/DTWEXBGS return None."""
    source = MacroViewSource()
    source.api_key = ""

    result = await source._fetch_series_fallback("VIXCLS")
    assert result is None

    result = await source._fetch_series_fallback("DTWEXBGS")
    assert result is None
    await source.close()
