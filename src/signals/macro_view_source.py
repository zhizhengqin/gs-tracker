"""Macro background signal source — FRED economic indicators.

Generates signals when key macro indicators cross defined thresholds:
- DGS10 (10Y Treasury): daily change ≥10bp → MEDIUM, ≥20bp → HIGH
- VIX: daily change ≥15% → MEDIUM, ≥30% → HIGH
- DTWEXBGS (broad USD index): weekly change ≥1%

FRED API key is read from FRED_API_KEY env var.
FRED free tier: 120 requests/minute, no registration delays.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import httpx

from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"

# East Money fallback for US 10Y Treasury yield (free, no auth).
# Used when FRED_API_KEY is not configured or FRED is unreachable from JD Cloud.
EASTMONEY_BOND_URL = (
    "https://datacenter.eastmoney.com/api/data/get"
    "?type=RPTA_WEB_TREASURYYIELD&sty=ALL&p=1&ps=5"
    '&filter=(SECURITY_TYPE_CODE="US10YR")'
)

# Map FRED series IDs to their East Money fallback equivalents.
# Only DGS10 has a known-working fallback; VIX and DTWEXBGS are FRED-only.
FALLBACK_SERIES = frozenset({"DGS10"})

# (series_id, label, threshold_medium, threshold_high, unit, comparison)
# comparison: "daily_pct" for % change, "daily_bp" for basis points, "weekly_pct" for weekly
MACRO_SERIES = [
    ("DGS10", "10Y Treasury", 10, 20, "bp", "daily_bp"),
    ("VIXCLS", "VIX", 15, 30, "%", "daily_pct"),
    ("DTWEXBGS", "USD Index (Broad)", 1.0, 2.0, "%", "weekly_pct"),
]


class MacroViewSource:
    """Fetch macro indicator observations from FRED and emit threshold-crossing signals."""

    source_name = "macro_view"

    def __init__(self) -> None:
        self.api_key = os.getenv("FRED_API_KEY", "")
        self.client = httpx.AsyncClient(timeout=15.0)

    async def fetch(self, quarter: str = "") -> List[Signal]:
        """Backward compat: fetch returns list. Use fetch_since for incremental."""
        signals, _ = await self.fetch_since()
        return signals

    async def fetch_since(
        self, watermark: Optional[str] = None
    ) -> Tuple[List[Signal], Optional[str]]:
        """Fetch latest observations and emit signals for threshold crossings.

        *watermark* is the last observation date processed (YYYY-MM-DD).
        Returns (signals, new_watermark).
        """
        signals: List[Signal] = []
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        new_watermark = watermark or today

        for series_id, label, med_thresh, high_thresh, unit, comp in MACRO_SERIES:
            try:
                result = await self._fetch_series(series_id)
                if not result:
                    continue
                signal = self._evaluate(result, series_id, label, med_thresh,
                                        high_thresh, unit, comp, watermark)
                if signal:
                    signals.append(signal)
                    if signal.published_at.strftime("%Y-%m-%d") > (new_watermark or ""):
                        new_watermark = signal.published_at.strftime("%Y-%m-%d")
            except Exception:
                logger.exception("Failed to fetch/evaluate %s", series_id)

        return signals, new_watermark

    async def _fetch_series(self, series_id: str) -> Optional[dict]:
        """Fetch recent observations for a macro series.

        Tries FRED first; falls back to East Money for DGS10 if FRED is
        unavailable (no API key configured or network blocked from JD Cloud).
        """
        if self.api_key:
            params = {
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 3,
            }
            try:
                response = await self.client.get(FRED_API_URL, params=params)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
                logger.warning("FRED fetch failed for %s: %s", series_id, exc)

        # Try East Money fallback for supported series
        if series_id in FALLBACK_SERIES:
            return await self._fetch_series_fallback(series_id)

        return None

    async def _fetch_series_fallback(self, series_id: str) -> Optional[dict]:
        """Fetch US Treasury yield from East Money (domestic China CDN, no auth).

        Transforms East Money's response into the same {observations: [...]}
        shape that FRED returns, so _evaluate() works unchanged.
        """
        if series_id != "DGS10":
            return None
        try:
            response = await self.client.get(EASTMONEY_BOND_URL)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
            logger.warning("East Money fallback failed for %s: %s", series_id, exc)
            return None

        if not data.get("success") or not data.get("result"):
            return None

        records = data["result"].get("data", [])
        if len(records) < 2:
            return None

        # East Money returns records with fields like:
        # DATE, YIELD (%), CHANGE (bp), etc.
        # Transform to FRED-compatible format.
        observations = []
        for rec in records[:3]:
            date_str = rec.get("DATE", "")
            yield_val = rec.get("YIELD", "")
            if date_str and yield_val:
                # East Money date format: "2026-07-21 00:00:00" → "2026-07-21"
                date_str = date_str[:10]
                observations.append({"date": date_str, "value": str(yield_val)})

        logger.info(
            "East Money fallback: %d DGS10 observations (latest %s)",
            len(observations),
            observations[0]["date"] if observations else "N/A",
        )
        return {"observations": observations}

    def _evaluate(
        self, data: dict, series_id: str, label: str,
        med_thresh: float, high_thresh: float,
        unit: str, comp: str, watermark: Optional[str],
    ) -> Optional[Signal]:
        """Check if the latest observation crosses a threshold."""
        observations = data.get("observations", [])
        if len(observations) < 2:
            return None

        latest = observations[0]
        prev = observations[1]

        latest_val = self._parse_float(latest.get("value", ""))
        prev_val = self._parse_float(prev.get("value", ""))
        latest_date = latest.get("date", "")

        if latest_val is None or prev_val is None or not latest_date:
            return None

        # Skip if on or before watermark (already processed)
        if watermark and latest_date <= watermark:
            return None

        # Compute change
        if comp == "daily_bp":
            change = abs(latest_val - prev_val) * 100  # convert to bp
            med_thresh_actual = med_thresh
            high_thresh_actual = high_thresh
        elif comp == "daily_pct":
            if prev_val == 0:
                return None
            change = abs((latest_val - prev_val) / prev_val) * 100
            med_thresh_actual = med_thresh
            high_thresh_actual = high_thresh
        elif comp == "weekly_pct":
            # DTWEXBGS: use weekly change (compare to observation ~7 days ago)
            if prev_val == 0:
                return None
            change = abs((latest_val - prev_val) / prev_val) * 100
            # For weekly, use the same thresholds but compare with the previous observation
            # which may be ~1 week apart for weekly series
            med_thresh_actual = med_thresh
            high_thresh_actual = high_thresh
        else:
            return None

        if change < med_thresh_actual:
            return None

        strength = SignalStrength.HIGH if change >= high_thresh_actual else SignalStrength.MEDIUM
        direction = "↑" if latest_val > prev_val else "↓"
        summary = (
            f"{label} 变动 {direction}{change:.1f}{unit}："
            f"从 {prev_val:.2f} 到 {latest_val:.2f}（数据日: {latest_date}）"
        )

        return Signal(
            title=f"宏观信号: {label} {direction}{change:.1f}{unit}",
            source="macro_view",
            published_at=datetime.strptime(latest_date, "%Y-%m-%d").replace(tzinfo=timezone.utc),
            summary=summary,
            companies=[],  # macro signals don't participate in company-level cross-refs
            strength=strength,
            url=f"https://fred.stlouisfed.org/series/{series_id}",
        )

    @staticmethod
    def _parse_float(value: str) -> Optional[float]:
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    async def close(self) -> None:
        await self.client.aclose()
