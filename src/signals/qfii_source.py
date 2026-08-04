"""QFII A-share holdings data source (Eastmoney 主力数据-QFII持仓).

Fetches the latest quarterly QFII holdings from Eastmoney's zlsj API:
  1. datacenter-web RPT_MAIN_REPORTDATE -> latest report date (quarter-end)
  2. data.eastmoney.com/dataapi/zlsj/list?type=2&date=... -> QFII holdings
     sorted by market value, including change direction (新进/增仓/减仓)

Data is quarterly (disclosed with A-share periodic reports). Signals are
tagged institution_id="all" because QFII aggregates many foreign
institutions (this is where GS/JPM A-share positions actually show up).

Both endpoints are occasionally unreachable from CN networks, so each
request is retried with backoff.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import httpx

from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

REPORTDATE_API = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get"
    "?reportName=RPT_MAIN_REPORTDATE&columns=REPORT_DATE"
    "&pageNumber=1&pageSize=1&sortTypes=-1&sortColumns=REPORT_DATE"
    "&source=WEB&client=WEB"
)

# type=2 is QFII on data.eastmoney.com/zlsj (type=0 基金 type=1 券商?).
ZLSJ_API = (
    "https://data.eastmoney.com/dataapi/zlsj/list"
    "?date={date}&type=2&zjc=0&sortField=HOLD_VALUE&sortDirec=1"
    "&pageNum=1&pageSize={limit}"
)

_RETRIES = 3
_BACKOFF = (0.5, 1.5, 3.0)


class QFIISource:
    """Fetch quarterly QFII A-share holdings from Eastmoney."""

    source_name = "qfii"

    def __init__(self, max_items: int = 10) -> None:
        self.max_items = max_items
        self.institution_id = "all"
        self.client = httpx.AsyncClient(
            timeout=15.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                "Referer": "https://data.eastmoney.com/zlsj/qfii.html",
            },
        )

    async def _get_json(self, url: str) -> Optional[dict]:
        """GET JSON with retry/backoff. Returns None on repeated failure."""
        for attempt in range(_RETRIES):
            try:
                resp = await self.client.get(url)
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.debug("QFII request failed (attempt %d): %s", attempt + 1, exc)
                if attempt < _RETRIES - 1:
                    await asyncio.sleep(_BACKOFF[attempt])
        logger.warning("QFII API unavailable after %d attempts", _RETRIES)
        return None

    async def _latest_report_date(self) -> Optional[str]:
        data = await self._get_json(REPORTDATE_API)
        rows = (data or {}).get("result", {}).get("data") or []
        if not rows:
            return None
        return str(rows[0].get("REPORT_DATE", ""))[:10] or None

    async def fetch(self, quarter: str = "") -> List[Signal]:
        signals, _ = await self.fetch_since()
        return signals

    async def fetch_since(
        self, watermark: Optional[str] = None
    ) -> Tuple[List[Signal], Optional[str]]:
        """Fetch latest-quarter QFII holdings. Watermark is the report date
        (YYYY-MM-DD); a new quarter disclosure produces a fresh batch."""
        report_date = await self._latest_report_date()
        if not report_date:
            return [], watermark
        if watermark and watermark >= report_date:
            return [], watermark

        data = await self._get_json(
            ZLSJ_API.format(date=report_date, limit=self.max_items)
        )
        items = (data or {}).get("data") or []
        if not items:
            return [], watermark

        signals: List[Signal] = []
        now = datetime.now(timezone.utc)

        for item in items[: self.max_items]:
            name = item.get("SECURITY_NAME_ABBR", "")
            if not name:
                continue
            holders = item.get("HOULD_NUM", 0) or 0
            value_yi = round((item.get("HOLD_VALUE") or 0) / 1e8, 1)
            pct = round(item.get("FREESHARES_RATIO") or 0, 2)
            change = item.get("HOLDCHA") or "不变"
            change_pct = item.get("HOLDCHA_RATIO")
            code = item.get("SECUCODE", "")

            change_txt = f"，较上期{change}"
            if change in ("增仓", "减仓") and change_pct is not None:
                change_txt += f"{abs(round(change_pct, 1))}%"

            signals.append(
                Signal(
                    title=f"QFII持仓: {name}",
                    source="qfii",
                    published_at=now,
                    summary=(
                        f"{report_date}季度：{holders}家QFII持有{name}"
                        f"（{code}），市值{value_yi}亿元，占流通股{pct}%{change_txt}。"
                    ),
                    companies=[name],
                    strength=(
                        SignalStrength.HIGH
                        if change in ("新进", "增仓") and value_yi >= 5
                        else SignalStrength.MEDIUM
                    ),
                    url="https://data.eastmoney.com/zlsj/qfii.html",
                    institution_id="all",
                )
            )

        logger.info(
            "qfii: %d holdings from report date %s", len(signals), report_date
        )
        return signals, report_date

    async def close(self) -> None:
        await self.client.aclose()
