"""Tests for src.signals.sec_8k_source."""
from datetime import datetime

import pytest
from pytest_httpx import HTTPXMock

from src.signals.sec_8k_source import Sec8kSource


MOCK_SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["8-K", "8-K", "10-Q", "8-K", "4"],
            "filingDate": ["2026-05-15", "2026-05-10", "2026-05-08", "2026-04-20", "2026-04-15"],
            "accessionNumber": [
                "0000886982-26-000001",
                "0000886982-26-000002",
                "0000886982-26-000003",
                "0000886982-26-000004",
                "0000886982-26-000005",
            ],
            "primaryDocument": [
                "form8k-001.htm",
                "form8k-002.htm",
                "form10q-003.htm",
                "form8k-004.htm",
                "form8k-005.htm",
            ],
            "items": [
                "2.02,9.01",
                "5.02",
                "",
                "1.01,2.03",
                "",
            ],
        }
    }
}


class TestSec8kSource:
    @pytest.mark.asyncio
    async def test_fetch_returns_8k_signals(self, httpx_mock: HTTPXMock):
        submissions_url = "https://data.sec.gov/submissions/CIK0000886982.json"
        httpx_mock.add_response(
            url=submissions_url,
            json=MOCK_SUBMISSIONS,
            status_code=200,
        )
        source = Sec8kSource()
        signals = await source.fetch("2026-Q2")
        # 4 out of 5 filings are 8-K (form == "8-K"), but Q2 starts Apr 1 — "2026-04-15" and "2026-04-20" are in Q2, "2026-05-*" also in Q2
        assert len(signals) >= 1
        for s in signals:
            assert s.source == "8-K"
            assert isinstance(s.published_at, datetime)
        await source.close()

    @pytest.mark.asyncio
    async def test_fetch_handles_sec_error(self, httpx_mock: HTTPXMock):
        submissions_url = "https://data.sec.gov/submissions/CIK0000886982.json"
        httpx_mock.add_response(url=submissions_url, status_code=500)
        source = Sec8kSource()
        signals = await source.fetch("2026-Q2")
        assert signals == []
        await source.close()

    @pytest.mark.asyncio
    async def test_fetch_handles_invalid_json(self, httpx_mock: HTTPXMock):
        submissions_url = "https://data.sec.gov/submissions/CIK0000886982.json"
        httpx_mock.add_response(url=submissions_url, text="not json", status_code=200)
        source = Sec8kSource()
        signals = await source.fetch("2026-Q2")
        assert signals == []

    @pytest.mark.asyncio
    async def test_fetch_filters_by_quarter(self, httpx_mock: HTTPXMock):
        quarter_data = {
            "filings": {
                "recent": {
                    "form": ["8-K", "8-K"],
                    "filingDate": ["2026-04-15", "2026-07-01"],
                    "accessionNumber": ["0000886982-26-000010", "0000886982-26-000011"],
                    "primaryDocument": ["form8k-010.htm", "form8k-011.htm"],
                    "items": ["2.02", "5.02"],
                }
            }
        }
        submissions_url = "https://data.sec.gov/submissions/CIK0000886982.json"
        httpx_mock.add_response(url=submissions_url, json=quarter_data, status_code=200)
        source = Sec8kSource()
        signals = await source.fetch("2026-Q2")
        assert len(signals) == 1
        await source.close()

    @pytest.mark.asyncio
    async def test_fetch_no_8k_filings(self, httpx_mock: HTTPXMock):
        no_8k = {
            "filings": {
                "recent": {
                    "form": ["10-Q", "4"],
                    "filingDate": ["2026-05-15", "2026-05-10"],
                    "accessionNumber": ["0000886982-26-000020", "0000886982-26-000021"],
                    "primaryDocument": ["form10q.htm", "form4.htm"],
                    "items": ["", ""],
                }
            }
        }
        submissions_url = "https://data.sec.gov/submissions/CIK0000886982.json"
        httpx_mock.add_response(url=submissions_url, json=no_8k, status_code=200)
        source = Sec8kSource()
        signals = await source.fetch("2026-Q2")
        assert signals == []

    @pytest.mark.asyncio
    async def test_fetch_respects_max_items(self, httpx_mock: HTTPXMock):
        forms = ["8-K"] * 10
        dates = [f"2026-05-{d:02d}" for d in range(1, 11)]
        acc_nums = [f"0000886982-26-0000{d:02d}" for d in range(1, 11)]
        docs = [f"form8k-{d:03d}.htm" for d in range(1, 11)]
        items = ["2.02"] * 10

        many_8k = {
            "filings": {
                "recent": {
                    "form": forms,
                    "filingDate": dates,
                    "accessionNumber": acc_nums,
                    "primaryDocument": docs,
                    "items": items,
                }
            }
        }
        submissions_url = "https://data.sec.gov/submissions/CIK0000886982.json"
        httpx_mock.add_response(url=submissions_url, json=many_8k, status_code=200)
        source = Sec8kSource(max_items=5)
        signals = await source.fetch("2026-Q2")
        assert len(signals) <= 5
        await source.close()
