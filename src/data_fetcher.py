"""SEC 13F data fetcher."""
import logging
import xml.etree.ElementTree as ET
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
        submissions = await self.fetch_submissions()
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])

        if not forms or not accession_numbers or len(forms) != len(accession_numbers):
            raise ValueError("No 13F-HR filing found")

        try:
            index = forms.index("13F-HR")
        except ValueError:
            raise ValueError("No 13F-HR filing found")

        accession_number = accession_numbers[index]
        accession_no_dash = accession_number.replace("-", "")
        cik_numeric = self.cik.lstrip("0") or "886982"
        xml_url = (
            f"{self.BASE_URL}/Archives/edgar/data/{cik_numeric}/"
            f"{accession_no_dash}/{accession_number}_infotable.xml"
        )
        return await self.parse_13f_infotable(xml_url)

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
        response = await self.client.get(xml_url)
        response.raise_for_status()
        root = ET.fromstring(response.text)

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
