"""Quick smoke tests for 13D/13G source."""
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from src.signals.thirteen_dg_source import ThirteenDGSource


@pytest.mark.asyncio
async def test_fetch_since_returns_tuple(httpx_mock):
    """fetch_since should return (signals, watermark) tuple."""
    httpx_mock.add_response(
        url="https://data.sec.gov/submissions/CIK0000886982.json",
        json={
            "filings": {
                "recent": {
                    "form": ["SC 13D", "8-K"],
                    "filingDate": ["2026-07-20", "2026-07-19"],
                    "accessionNumber": ["0000886982-26-000500", "0000886982-26-000499"],
                    "primaryDocument": ["doc1.xml", "doc2.xml"],
                }
            }
        },
    )
    source = ThirteenDGSource(max_items=10)
    signals, watermark = await source.fetch_since()
    assert isinstance(signals, list)
    assert len(signals) == 1
    assert signals[0].source == "13D/13G"
    assert watermark == "0000886982-26-000500"
    await source.close()


@pytest.mark.asyncio
async def test_fetch_since_respects_watermark(httpx_mock):
    """Signals with accession <= watermark should be skipped.

    SEC accession numbers are lexicographically sortable
    (e.g. 0000886982-26-000500 > 0000886982-26-000499).
    """
    httpx_mock.add_response(
        url="https://data.sec.gov/submissions/CIK0000886982.json",
        json={
            "filings": {
                "recent": {
                    "form": ["SC 13D", "SC 13G"],
                    "filingDate": ["2026-07-20", "2026-07-15"],
                    "accessionNumber": [
                        "0000886982-26-000500",
                        "0000886982-26-000300",
                    ],
                    "primaryDocument": ["a.xml", "b.xml"],
                }
            }
        },
    )
    source = ThirteenDGSource(max_items=10)
    signals, watermark = await source.fetch_since(
        watermark="0000886982-26-000300"
    )
    assert len(signals) == 1
    assert "000088698226000500" in (signals[0].url or "")
    assert watermark == "0000886982-26-000500"
    await source.close()


@pytest.mark.asyncio
async def test_fetch_since_respects_max_items(httpx_mock):
    """max_items should cap the returned signals."""
    filings_data = {
        "form": ["SC 13D"] * 10,
        "filingDate": ["2026-07-20"] * 10,
        "accessionNumber": [f"acc-{i:03d}" for i in range(10)],
        "primaryDocument": ["doc.xml"] * 10,
    }
    httpx_mock.add_response(
        url="https://data.sec.gov/submissions/CIK0000886982.json",
        json={"filings": {"recent": filings_data}},
    )
    source = ThirteenDGSource(max_items=3)
    signals, _ = await source.fetch_since()
    assert len(signals) == 3
    await source.close()


@pytest.mark.asyncio
async def test_fetch_since_handles_http_error(httpx_mock):
    """SEC 503 should return empty list, not crash."""
    httpx_mock.add_response(
        url="https://data.sec.gov/submissions/CIK0000886982.json",
        status_code=503,
    )
    source = ThirteenDGSource()
    signals, watermark = await source.fetch_since(watermark="last-acc")
    assert signals == []
    assert watermark == "last-acc"  # unchanged on failure
    await source.close()
