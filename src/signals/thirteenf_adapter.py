"""Adapter converting existing 13F holdings into Signal format."""
import calendar
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

QUARTER_END_MONTHS = {"Q1": 3, "Q2": 6, "Q3": 9, "Q4": 12}


def _quarter_end_date(quarter: str) -> datetime:
    """Return the last day of the quarter as a UTC datetime."""
    year_str, q = quarter.split("-")
    year = int(year_str)
    month = QUARTER_END_MONTHS[q]
    last_day = calendar.monthrange(year, month)[1]
    return datetime(year, month, last_day, tzinfo=timezone.utc)


class ThirteenthFSignalAdapter:
    """Wrap existing 13F holdings data as Signal objects.

    Does NOT modify SEC13FFetcher — wraps its output post-fetch.
    """

    def __init__(self, max_signals: int = 10) -> None:
        self.max_signals = max_signals

    def to_signals(
        self,
        records: List[Dict[str, Any]],
        quarter: str,
        comparison: Optional[Dict[str, Any]] = None,
    ) -> List[Signal]:
        """Convert holdings records into Signals, sorted by value desc."""
        if not records:
            return []

        published_at = _quarter_end_date(quarter)
        sorted_records = sorted(
            records,
            key=lambda r: float(r.get("value", 0) or 0),
            reverse=True,
        )[:self.max_signals]

        signals: List[Signal] = []
        for record in sorted_records:
            name = record.get("name_of_issuer", "Unknown")
            value = float(record.get("value", 0) or 0)

            title = f"高盛持仓: {name}"
            summary_parts = [f"高盛持有 {name}"]
            if value > 0:
                if value >= 1e9:
                    summary_parts.append(f"市值 ${value / 1e9:.1f}B")
                else:
                    summary_parts.append(f"市值 ${value / 1e6:.0f}M")

            total_value = None
            if comparison and comparison.get("total_value"):
                total_value = float(comparison["total_value"])
            if total_value and total_value > 0:
                pct = value / total_value
                if pct > 0.05:
                    strength = SignalStrength.HIGH
                elif pct > 0.01:
                    strength = SignalStrength.MEDIUM
                else:
                    strength = SignalStrength.LOW
                summary_parts.append(f"占比 {pct * 100:.1f}%")
            else:
                strength = SignalStrength.MEDIUM

            signals.append(Signal(
                title=title,
                source="13F",
                published_at=published_at,
                summary="，".join(summary_parts) + "。",
                companies=[name],
                strength=strength,
            ))

        return signals
