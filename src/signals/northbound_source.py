"""Northbound (沪深港通北向) daily breadth data source.

Since 2024-08-19 HKEX stopped disclosing daily northbound net-buy flows,
so "今日北向净流入" no longer exists in public data. What IS still
published daily (via Eastmoney RPT_MUTUAL_QUOTA):

- 沪股通 / 深股通 constituent breadth: advancing / declining / flat counts
  (quote fields f104 / f105 / f106 on the board quotes)
- Board daily change % (f3)

We emit one honest daily signal summarising northbound-channel breadth —
a sentiment proxy for the stocks foreign investors can actually trade.
Per-stock northbound holdings moved to quarterly disclosure and are
covered by the QFII/zlsj data instead.

The endpoint is occasionally unreachable from CN networks — requests are
retried with backoff.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import httpx

from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

QUOTA_API = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get"
    "?reportName=RPT_MUTUAL_QUOTA"
    "&columns=TRADE_DATE,MUTUAL_TYPE_NAME,FUNDS_DIRECTION,BOARD_CODE"
    "&quoteColumns=f3~07~BOARD_CODE,f104~07~BOARD_CODE,"
    "f105~07~BOARD_CODE,f106~07~BOARD_CODE"
    "&filter=(FUNDS_DIRECTION%3D%22%E5%8C%97%E5%90%91%22)"
    "&pageNumber=1&pageSize=5&source=WEB&client=WEB"
)

_RETRIES = 3
_BACKOFF = (0.5, 1.5, 3.0)


class NorthboundSource:
    """Fetch daily northbound-channel breadth from Eastmoney."""

    source_name = "northbound"

    def __init__(self, max_items: int = 5) -> None:
        self.max_items = max_items
        self.client = httpx.AsyncClient(
            timeout=15.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                "Referer": "https://data.eastmoney.com/hsgtcg/",
            },
        )

    async def fetch(self, quarter: str = "") -> List[Signal]:
        signals, _ = await self.fetch_since()
        return signals

    async def fetch_since(
        self, watermark: Optional[str] = None
    ) -> Tuple[List[Signal], Optional[str]]:
        """Fetch today's northbound breadth. Watermark is the trade date
        (YYYY-MM-DD); same-day re-runs produce no duplicates."""
        data = None
        for attempt in range(_RETRIES):
            try:
                resp = await self.client.get(QUOTA_API)
                resp.raise_for_status()
                data = resp.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                logger.debug(
                    "Northbound request failed (attempt %d): %s", attempt + 1, exc
                )
                if attempt < _RETRIES - 1:
                    await asyncio.sleep(_BACKOFF[attempt])
        if data is None:
            logger.warning("Northbound API unavailable after %d attempts", _RETRIES)
            return [], watermark

        rows = (data.get("result") or {}).get("data") or []
        if not rows:
            return [], watermark

        trade_date = str(rows[0].get("TRADE_DATE", ""))[:10]
        if not trade_date or (watermark and watermark >= trade_date):
            return [], watermark

        parts: List[str] = []
        total_up = total_down = 0
        for row in rows:
            board = row.get("MUTUAL_TYPE_NAME", "")
            up = int(row.get("f104") or 0)
            down = int(row.get("f105") or 0)
            flat = int(row.get("f106") or 0)
            chg = row.get("f3")
            chg_txt = f"，板块涨跌幅{chg}%" if chg is not None else ""
            parts.append(f"{board} {up}涨/{down}跌/{flat}平{chg_txt}")
            total_up += up
            total_down += down

        if not parts:
            return [], watermark

        ratio = total_up / total_down if total_down else float("inf")
        if ratio >= 2:
            mood = "普涨，北向通道情绪偏暖"
        elif ratio <= 0.5:
            mood = "普跌，北向通道情绪偏弱"
        else:
            mood = "涨跌互现，情绪中性"

        signal = Signal(
            title=f"沪深港通北向: {total_up}涨/{total_down}跌",
            source="northbound",
            published_at=datetime.now(timezone.utc),
            summary=(
                f"{trade_date} 北向通道标的宽度：{'；'.join(parts)}。"
                f"{mood}。（2024年8月起港交所不再披露每日北向净买入额，"
                f"此处以通道标的涨跌宽度衡量外资可交易股票的市场情绪）"
            ),
            companies=[],
            strength=(
                SignalStrength.HIGH
                if ratio >= 2 or ratio <= 0.5
                else SignalStrength.MEDIUM
            ),
            url="https://data.eastmoney.com/hsgtcg/",
            institution_id="all",
        )
        logger.info("northbound: breadth %s for %s", signal.title, trade_date)
        return [signal], trade_date

    async def close(self) -> None:
        await self.client.aclose()
