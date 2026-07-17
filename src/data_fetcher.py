"""SEC 13F data fetcher."""
import logging
from dataclasses import dataclass
from typing import List, Optional

import httpx
import pandas as pd

from src.config import GOLDMAN_CIK, SEC_USER_AGENT

logger = logging.getLogger(__name__)


@dataclass
class FilingInfo:
    """Basic 13F filing metadata."""

    accession_number: str
    filing_date: str
    period_of_report: str
    primary_doc_url: str
    info_table_url: str


class SEC13FFetcher:
    """Fetch and parse 13F-HR filings from SEC EDGAR."""

    BASE_URL = "https://www.sec.gov"

    def __init__(self, cik: str = GOLDMAN_CIK, user_agent: str = SEC_USER_AGENT) -> None:
        self.cik = cik.zfill(10)
        self.headers = {"User-Agent": user_agent}
        self.client = httpx.AsyncClient(headers=self.headers, timeout=30.0)

    async def fetch_submissions(self) -> dict:
        """Fetch company submissions JSON from EDGAR."""
        url = f"{self.BASE_URL}/cgi-bin/browse-edgar?action=getcompany&CIK={self.cik}&type=13F-HR&output=json"
        response = await self.client.get(url)
        response.raise_for_status()
        return response.json()

    async def fetch_latest_holdings(self) -> pd.DataFrame:
        """Fetch the most recent 13F-HR holdings as a DataFrame."""
        raise NotImplementedError("TODO: implement latest holdings fetch")

    async def fetch_historical_holdings(self, quarters: List[str]) -> pd.DataFrame:
        """Fetch holdings for multiple quarters."""
        raise NotImplementedError("TODO: implement historical holdings fetch")

    async def parse_13f_infotable(self, xml_url: str) -> pd.DataFrame:
        """Parse a 13F-HR information table XML into a DataFrame."""
        raise NotImplementedError("TODO: implement XML parsing")

    async def close(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> "SEC13FFetcher":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
