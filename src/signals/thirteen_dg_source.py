"""SEC 13D/13G beneficial ownership filing signal source.

13D = initial filing (≥5% stake within 10 days of acquisition).
13G = annual/quarterly update for qualified institutional investors.
13D/A, 13G/A = amendments.

These filings are the closest thing to "real-time" signal for large
institutional position changes — filed within 10 days (13D) vs 13F's 45 days.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx

from src.config import GOLDMAN_CIK, SEC_USER_AGENT
from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{}.json"

THIRTEEN_DG_FORMS = frozenset({"SC 13D", "SC 13G", "SC 13D/A", "SC 13G/A"})

FORM_LABELS: Dict[str, str] = {
    "SC 13D": "13D 首次申报(持股超5%)",
    "SC 13G": "13G 机构投资者例行申报",
    "SC 13D/A": "13D 修正案(持仓变动)",
    "SC 13G/A": "13G 修正案",
}


def _build_13dg_summary(form: str, filing_date: str, acc_num: str) -> str:
    label = FORM_LABELS.get(form, form)
    return (
        f"高盛于 {filing_date} 提交 {label}。"
        f"SEC 文件编号: {acc_num}。"
    )


class ThirteenDGSource:
    """Fetch 13D/13G filing signals from SEC EDGAR submissions API.

    Primary path: match Goldman CIK filings by form type.
    Keyword search path (EFTS): planned as secondary path for broader
    coverage — not yet implemented.
    """

    source_name = "13D/13G"

    def __init__(self, cik: str = GOLDMAN_CIK, max_items: int = 10) -> None:
        self.cik = cik.lstrip("0")
        self.max_items = max_items
        self.client = httpx.AsyncClient(
            timeout=20.0,
            headers={"User-Agent": SEC_USER_AGENT},
        )

    async def fetch(self, quarter: str) -> List[Signal]:
        """Fetch recent 13D/13G filings as Signals (backward compat).

        For daily use, prefer fetch_since(watermark) for incremental fetching.
        """
        signals, _ = await self.fetch_since(watermark=None)
        return signals

    async def fetch_since(
        self, watermark: Optional[str] = None
    ) -> Tuple[List[Signal], Optional[str]]:
        """Fetch 13D/13G filings newer than *watermark*.

        Returns (signals, new_watermark). When watermark is None, returns all
        available filings (subject to max_items). Always returns a list;
        never raises — returns empty on failure.
        """
        try:
            padded_cik = self.cik.zfill(10)
            url = SEC_SUBMISSIONS_URL.format(padded_cik)
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
            logger.warning("Failed to fetch SEC submissions for 13D/13G: %s", exc)
            return [], watermark

        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        dates = filings.get("filingDate", [])
        acc_nums = filings.get("accessionNumber", [])
        docs = filings.get("primaryDocument", [])

        signals: List[Signal] = []
        new_watermark = watermark
        count = 0

        for i in range(len(forms)):
            if count >= self.max_items:
                break
            if forms[i] not in THIRTEEN_DG_FORMS:
                continue

            filing_date = dates[i] if i < len(dates) else ""
            acc_num = acc_nums[i] if i < len(acc_nums) else ""
            doc_name = docs[i] if i < len(docs) else ""

            # Watermark-based filtering: skip filings on or before the watermark.
            if watermark and acc_num <= watermark:
                continue

            published_at = datetime.strptime(filing_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )

            signals.append(
                Signal(
                    title=f"高盛 {forms[i]}: {FORM_LABELS.get(forms[i], forms[i])}",
                    source="13D/13G",
                    published_at=published_at,
                    summary=_build_13dg_summary(forms[i], filing_date, acc_num),
                    companies=["GS"],
                    strength=SignalStrength.HIGH,
                    url=(
                        (
                            "https://www.sec.gov/Archives/edgar/data/"
                            f"{padded_cik}/{acc_num.replace('-', '')}/{doc_name}"
                        )
                        if acc_num and doc_name
                        else None
                    ),
                )
            )
            count += 1
            # Advance watermark to the latest accession seen.
            if new_watermark is None or acc_num > new_watermark:
                new_watermark = acc_num

        logger.info(
            "13D/13G: %d filings found (watermark %s → %s)",
            len(signals), watermark, new_watermark,
        )
        return signals, new_watermark

    async def close(self) -> None:
        await self.client.aclose()
