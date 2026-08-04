"""Northbound (沪深港通) capital flow data source.

Fetches daily northbound capital flow summary from Eastmoney API.
Provides aggregate foreign institutional flow into A-shares via
Shanghai/Shenzhen Connect.

API: push2.eastmoney.com/api/qt/klist/get
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import httpx

from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

NORTHBOUND_API = (
    "https://push2his.eastmoney.com/api/qt/klist/get"
    "?secid=1.000001&fields1=f1,f2,f3,f4,f5,f6"
    "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
    "&klt=101&fqt=1&lmt={limit}"
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
            url = NORTHBOUND_API.format(limit=self.max_items + 5)
            resp = await self.client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Northbound API failed: %s", exc)
            return [], watermark

        klines = data.get("data", {}).get("klines", [])
        if not klines:
            return [], watermark

        signals: List[Signal] = []
        new_watermark = watermark

        for line in klines[-self.max_items :]:
            parts = line.split(",")
            if len(parts) < 11:
                continue

            date_str = parts[0]
            net_buy = _parse_float(parts[7])  # 净买入 (万元)
            buy_amt = _parse_float(parts[5])   # 买入成交额
            sell_amt = _parse_float(parts[6])  # 卖出成交额

            if net_buy is None:
                continue

            try:
                published_at = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            if watermark and date_str <= watermark:
                continue

            direction = "净流入" if net_buy > 0 else "净流出"
            net_yi = abs(net_buy) / 10000  # 万元→亿元
            summary = (
                f"北向资金{date_str}：{direction}{net_yi:.1f}亿元"
                f"（买入{buy_amt/10000:.1f}亿，卖出{sell_amt/10000:.1f}亿）"
            )

            signals.append(
                Signal(
                    title=f"北向资金: {direction}{net_yi:.1f}亿",
                    source="northbound",
                    published_at=published_at,
                    summary=summary,
                    companies=["北向资金"],
                    strength=SignalStrength.HIGH if abs(net_yi) > 50 else SignalStrength.MEDIUM,
                )
            )

            if not new_watermark or date_str > new_watermark:
                new_watermark = date_str

        logger.info("northbound: %d signals", len(signals))
        return signals, new_watermark

    async def close(self) -> None:
        await self.client.aclose()


def _parse_float(val: str) -> Optional[float]:
    try:
        v = val.replace(",", "")
        return float(v) if v and v != "-" else None
    except (ValueError, TypeError):
        return None
