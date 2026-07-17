"""Tests for src.data_fetcher."""
import pytest

from src.data_fetcher import SEC13FFetcher


@pytest.mark.asyncio
async def test_fetcher_initializes_headers():
    fetcher = SEC13FFetcher()
    assert "User-Agent" in fetcher.headers
    await fetcher.close()


@pytest.mark.asyncio
async def test_fetcher_cik_zero_padded():
    fetcher = SEC13FFetcher(cik="886982")
    assert fetcher.cik == "0000886982"
    await fetcher.close()
