"""QFII A-share holdings data source.

Pulls the latest QFII (Qualified Foreign Institutional Investor) holdings
data from Eastmoney's public push2 API. Each holding record is converted
into a Signal with the institution's tag.

API: push2.eastmoney.com/api/qt/clist/get
Fields: f12=code, f14=name, f62=mkt_cap, f69=holding_pct, f184=prev_pct
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import httpx

from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

QFII_API = (
    "https://push2.eastmoney.com/api/qt/clist/get"
    "?fid=f62&po=1&pz={limit}&pn=1&np=1&fltt=2&invt=2"
    "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
    "&fields=f12,f14,f2,f3,f62,f69,f184,f124"
)


class QFIISource:
    """Fetch QFII A-share holdings from Eastmoney public API."""

    source_name = "qfii"

    def __init__(self, max_items: int = 10) -> None:
        self.max_items = max_items
        self.institution_id = "all"
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
        """Fetch QFII holdings. Watermark is YYYY-MM-DD of last fetch."""
        try:
            url = QFII_API.format(limit=self.max_items)
            resp = await self.client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("QFII API failed: %s", exc)
            return [], watermark

        items = data.get("data", {}).get("diff", [])
        if not items:
            return [], watermark

        signals: List[Signal] = []
        now = datetime.now(timezone.utc)

        new_watermark = now.strftime("%Y-%m-%d")

        for item in items[: self.max_items]:
            code = item.get("f12", "")
            name = item.get("f14", "")
            price = item.get("f2", 0) or 0
            mkt_cap = item.get("f62", 0) or 0
            pct = item.get("f69", 0) or 0
            prev_pct = item.get("f184", 0) or 0

            if not name:
                continue

            change_dir = "增持" if pct > prev_pct else ("减持" if pct < prev_pct else "持平")
            summary = (
                f"QFII持有{name}({code})，持仓市值{_fmt_yi(mkt_cap)}亿元，"
                f"占流通股{pct}%，较上期{change_dir}。"
            )

            signals.append(
                Signal(
                    title=f"外资 QFII持仓: {name}",
                    source="qfii",
                    published_at=now,
                    summary=summary,
                    companies=[name],
                    strength=SignalStrength.HIGH if abs(pct - prev_pct) > 1 else SignalStrength.MEDIUM,
                    institution_id="all",
                )
            )

        logger.info("qfii: %d signals", len(signals))
        return signals, new_watermark

    async def close(self) -> None:
        await self.client.aclose()


def _fmt_yi(value: float) -> str:
    """Format market cap in 亿 units."""
    yi = value / 1e8
    if yi >= 10000:
        return f"{yi / 10000:.1f}万"
    return f"{yi:.1f}"
