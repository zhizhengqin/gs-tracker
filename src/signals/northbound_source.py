"""Northbound (沪深港通) capital flow data source.

TODO: The eastmoney API endpoint for northbound daily flow data needs
verification. Current stub returns empty — pipeline won't crash.
Expected data: daily net buy/sell amounts for Shanghai/Shenzhen Connect.
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import httpx

from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

# TODO: verify correct northbound flow API endpoint
NORTHBOUND_API = (
    "https://push2.eastmoney.com/api/qt/clist/get"
    "?fid=f62&po=1&pz={limit}&pn=1&np=1&fltt=2&invt=2"
    "&fs=b:BK0707+f:!50"
    "&fields=f12,f14,f2,f3,f62,f184,f66,f69"
)


class NorthboundSource:
    """Fetch daily northbound capital flow from Eastmoney."""

    source_name = "northbound"

    def __init__(self, max_items: int = 5) -> None:
        self.max_items = max_items
        self.client = httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": "BridgeIQ/1.0 (market research)"},
        )

    async def fetch(self, quarter: str = "") -> List[Signal]:
        signals, _ = await self.fetch_since()
        return signals

    async def fetch_since(
        self, watermark: Optional[str] = None
    ) -> Tuple[List[Signal], Optional[str]]:
        """Fetch recent northbound flow data. Watermark is YYYY-MM-DD."""
        try:
            url = NORTHBOUND_API.format(limit=self.max_items)
            resp = await self.client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("Northbound API unavailable (TODO): %s", exc)
            return [], watermark

        items = data.get("data", {}).get("diff", [])
        if not items:
            return [], watermark

        signals: List[Signal] = []
        now = datetime.now(timezone.utc)
        new_watermark = now.strftime("%Y-%m-%d")

        for item in items[: self.max_items]:
            name = item.get("f14", "")
            pct = item.get("f69", 0) or 0
            prev_pct = item.get("f184", 0) or 0
            mkt_cap = item.get("f62", 0) or 0

            if not name:
                continue

            signals.append(
                Signal(
                    title=f"北向资金持仓: {name}",
                    source="northbound",
                    published_at=now,
                    summary=f"北向资金持有{name}，占流通股{pct}%",
                    companies=[name],
                    strength=SignalStrength.HIGH if abs(pct - prev_pct) > 1 else SignalStrength.MEDIUM,
                )
            )

        logger.info("northbound: %d signals", len(signals))
        return signals, new_watermark

    async def close(self) -> None:
        await self.client.aclose()
