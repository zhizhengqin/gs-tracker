"""SEC 13F data fetcher."""
import asyncio
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import httpx
import pandas as pd

from src.config import GOLDMAN_CIK, SEC_BACKOFF_BASE, SEC_MAX_RETRIES, SEC_USER_AGENT

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

    async def _get_with_retry(self, url: str, **kwargs) -> httpx.Response:
        """Fetch a URL with exponential-backoff retry for transient SEC failures."""
        last_exception: Optional[Exception] = None
        for attempt in range(SEC_MAX_RETRIES):
            try:
                response = await self.client.get(url, **kwargs)
                # Trigger HTTPStatusError for 4xx/5xx so we can decide retryability.
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exception = exc
                logger.warning("SEC request to %s timed out on attempt %d: %s", url, attempt + 1, exc)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 403:
                    # A 403 usually means a missing/malformed User-Agent; retrying won't help.
                    raise
                if status == 429 or status >= 500:
                    last_exception = exc
                    logger.warning(
                        "SEC request to %s returned %d on attempt %d",
                        url,
                        status,
                        attempt + 1,
                    )
                else:
                    # Non-retryable client error (e.g. 404).
                    raise
            if attempt < SEC_MAX_RETRIES - 1:
                await asyncio.sleep(SEC_BACKOFF_BASE * (2 ** attempt))
        assert last_exception is not None
        raise last_exception

    async def fetch_submissions(self) -> dict:
        """Fetch company submissions JSON from EDGAR."""
        url = f"{self.BASE_URL}/cgi-bin/browse-edgar?action=getcompany&CIK={self.cik}&type=13F-HR&output=json"
        response = await self._get_with_retry(url)
        return response.json()

    async def fetch_latest_holdings(
        self, filing_info: Optional[Dict[str, str]] = None
    ) -> pd.DataFrame:
        """Fetch the most recent 13F-HR holdings as a DataFrame.

        Args:
            filing_info: Optional dict to populate with accession_number and report_date.
        """
        submissions = await self.fetch_submissions()
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        report_dates = recent.get("reportDate", [])

        if not forms or not accession_numbers or len(forms) != len(accession_numbers):
            raise ValueError("No 13F-HR filing found")

        try:
            index = forms.index("13F-HR")
        except ValueError:
            raise ValueError("No 13F-HR filing found")

        accession_number = accession_numbers[index]
        report_date = report_dates[index] if index < len(report_dates) else ""
        if filing_info is not None:
            filing_info["accession_number"] = accession_number
            filing_info["report_date"] = report_date
            filing_dates = recent.get("filingDate", [])
            if index < len(filing_dates):
                filing_info["filing_date"] = filing_dates[index]
            filing_info["period_of_report"] = report_date
            filing_info["xml_url"] = xml_url

        accession_no_dash = accession_number.replace("-", "")
        cik_numeric = self.cik.lstrip("0") or GOLDMAN_CIK.lstrip("0")

        filing_dir = f"{self.BASE_URL}/Archives/edgar/data/{cik_numeric}/{accession_no_dash}"
        index_url = f"{filing_dir}/index.json"
        response = await self._get_with_retry(index_url)
        filing_index = response.json()

        xml_name = self._find_infotable_filename(filing_index)
        if not xml_name:
            raise ValueError("No infotable XML found in filing directory")

        xml_url = f"{filing_dir}/{xml_name}"
        return await self.parse_13f_infotable(xml_url)

    @staticmethod
    def report_date_to_quarter(report_date: str) -> str:
        """Convert a YYYY-MM-DD report date into YYYY-QN format."""
        if not report_date:
            raise ValueError("Empty report date")
        date = datetime.strptime(report_date, "%Y-%m-%d")
        quarter = (date.month - 1) // 3 + 1
        return f"{date.year}-Q{quarter}"

    @staticmethod
    def _find_infotable_filename(filing_index: dict) -> Optional[str]:
        """Find the infotable XML filename from a SEC filing index.json."""
        items = filing_index.get("directory", {}).get("item", [])
        for item in items:
            name = item.get("name", "")
            if "infotable" in name.lower() and name.lower().endswith(".xml"):
                return name
        return None

    async def fetch_historical_holdings(self, quarters: List[str]) -> pd.DataFrame:
        """Fetch holdings for multiple quarters."""
        raise NotImplementedError("TODO: implement historical holdings fetch")

    @staticmethod
    def _get_text(element: ET.Element, tag_name: str) -> str:
        """Return stripped text of the first descendant matching *tag_name* (with or without namespace)."""
        for child in element.iter():
            if child.tag == tag_name or child.tag.endswith(f"}}{tag_name}"):
                text = child.text or ""
                return text.strip()
        return ""

    async def parse_13f_infotable(self, xml_url: str) -> pd.DataFrame:
        """Fetch and parse a 13F-HR information table XML into a DataFrame."""
        response = await self._get_with_retry(xml_url)
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            logger.warning("Failed to parse 13F XML from %s: %s", xml_url, exc)
            return pd.DataFrame()

        namespace = ""
        if root.tag.startswith("{"):
            namespace = root.tag.split("}", 1)[0][1:]

        ns_map = {"ns": namespace} if namespace else {}
        if namespace:
            info_tables = root.findall(".//ns:infoTable", ns_map)
        else:
            info_tables = root.findall(".//infoTable")

        records = []
        for info in info_tables:
            records.append(
                {
                    "name_of_issuer": self._get_text(info, "nameOfIssuer"),
                    "title_of_class": self._get_text(info, "titleOfClass"),
                    "cusip": self._get_text(info, "cusip"),
                    "value": self._get_text(info, "value"),
                    "shares": self._get_text(info, "sshPrnamt"),
                    "investment_discretion": self._get_text(info, "investmentDiscretion"),
                    "voting_sole": self._get_text(info, "Sole"),
                    "voting_shared": self._get_text(info, "Shared"),
                    "voting_none": self._get_text(info, "None"),
                }
            )

        df = pd.DataFrame(records)
        if not df.empty:
            df["value"] = pd.to_numeric(df["value"], errors="coerce") * 1000
            df["shares"] = pd.to_numeric(df["shares"], errors="coerce")
            df["voting_sole"] = pd.to_numeric(df["voting_sole"], errors="coerce")
            df["voting_shared"] = pd.to_numeric(df["voting_shared"], errors="coerce")
            df["voting_none"] = pd.to_numeric(df["voting_none"], errors="coerce")

        return df

    async def close(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> "SEC13FFetcher":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
