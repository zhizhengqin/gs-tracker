"""SEC 8-K filing signal source."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import httpx

from src.config import GOLDMAN_CIK, SEC_USER_AGENT
from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{}.json"

ITEM_LABELS: Dict[str, str] = {
    "1.01": "重大合作协议",
    "1.02": "重大合作协议终止",
    "2.01": "重大资产收购/处置",
    "2.02": "财务业绩披露",
    "2.03": "重大财务义务",
    "3.01": "退市/转板通知",
    "3.02": "股权发行",
    "4.01": "审计师变更",
    "4.02": "重述/不再依赖此前财报",
    "5.01": "控制权变更",
    "5.02": "高管/董事任免",
    "5.03": "章程修订",
    "5.07": "股东投票结果",
    "7.01": "监管FD披露",
    "8.01": "其他重大事件",
    "9.01": "财务报表与展品",
}


def _build_8k_summary(filing_date, item_labels, acc_num):
    """Build a Chinese summary line for an 8-K filing."""
    items_text = ', '.join(item_labels) if item_labels else '待解析'
    return (
        f"高盛于 {filing_date} 提交 8-K 报告。"
        f"涉及事项: {items_text}。"
        f"SEC 文件编号: {acc_num}。"
    )


QUARTER_DATE_RANGES = {
    "Q1": ("-01-01", "-03-31"),
    "Q2": ("-04-01", "-06-30"),
    "Q3": ("-07-01", "-09-30"),
    "Q4": ("-10-01", "-12-31"),
}


class Sec8kSource:
    """Fetch 8-K filing signals from SEC EDGAR."""

    source_name = "8-K"

    def __init__(self, cik: str = GOLDMAN_CIK, max_items: int = 10) -> None:
        self.cik = cik.lstrip("0")
        self.max_items = max_items
        self.client = httpx.AsyncClient(
            timeout=20.0,
            headers={"User-Agent": SEC_USER_AGENT},
        )

    async def fetch(self, quarter: str) -> List[Signal]:
        """Fetch recent 8-K filings and convert to Signals.

        Never raises — returns empty list on failure.
        """
        try:
            padded_cik = self.cik.zfill(10)
            url = SEC_SUBMISSIONS_URL.format(padded_cik)
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
            logger.warning("Failed to fetch SEC submissions: %s", exc)
            return []

        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        dates = filings.get("filingDate", [])
        acc_nums = filings.get("accessionNumber", [])
        docs = filings.get("primaryDocument", [])
        items = filings.get("items", [])

        signals: List[Signal] = []
        count = 0

        if quarter:
            year_str, q = quarter.split("-")
            year = int(year_str)
            range_start, range_end = QUARTER_DATE_RANGES.get(q, ("-01-01", "-12-31"))
            quarter_start = f"{year}{range_start}"
            quarter_end = f"{year}{range_end}"
        else:
            # Called from daily intel path — use a 90-day sliding window
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            quarter_start = cutoff.strftime("%Y-%m-%d")
            quarter_end = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for i in range(len(forms)):
            if count >= self.max_items:
                break
            if forms[i] != "8-K":
                continue

            filing_date = dates[i] if i < len(dates) else ""
            if filing_date < quarter_start or filing_date > quarter_end:
                continue

            item_list = items[i].split(",") if i < len(items) and items[i] else []
            item_labels = [
                ITEM_LABELS.get(it.strip(), f"Item {it.strip()}")
                for it in item_list
                if it.strip()
            ]

            acc_num = acc_nums[i] if i < len(acc_nums) else ""
            doc_name = docs[i] if i < len(docs) else ""

            title = "高盛 8-K: "
            if item_labels:
                title += "、".join(item_labels[:3])
            else:
                title += "重大事件披露"

            published_at = datetime.strptime(filing_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

            signals.append(Signal(
                title=title,
                source="8-K",
                published_at=published_at,
                summary=_build_8k_summary(filing_date, item_labels, acc_num),
                companies=["GS"],
                strength=(
                    SignalStrength.HIGH if item_labels
                    else SignalStrength.MEDIUM
                ),
                url=(
                    (
                        "https://www.sec.gov/Archives/edgar/data/"
                        f"{padded_cik}/{acc_num.replace('-', '')}/{doc_name}"
                    ) if acc_num and doc_name else None
                ),
            ))
            count += 1

        return signals

    async def close(self) -> None:
        await self.client.aclose()
