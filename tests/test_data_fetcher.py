"""Tests for src.data_fetcher."""
import pandas as pd
import pytest

from src.data_fetcher import SEC13FFetcher

SAMPLE_13F_XML = """<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>Apple Inc</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>100000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>10000</sshPrnamt>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>10000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
</informationTable>"""


@pytest.mark.asyncio
async def test_fetcher_initializes_user_agent():
    fetcher = SEC13FFetcher(user_agent="GS-Tracker test@example.com")
    assert "User-Agent" in fetcher.headers
    assert "test@example.com" in fetcher.headers["User-Agent"]
    await fetcher.close()


@pytest.mark.asyncio
async def test_fetcher_cik_zero_padded():
    fetcher = SEC13FFetcher(cik="886982")
    assert fetcher.cik == "0000886982"
    await fetcher.close()


@pytest.mark.asyncio
async def test_parse_13f_infotable(httpx_mock):
    fetcher = SEC13FFetcher()
    httpx_mock.add_response(url="https://www.sec.gov/test.xml", text=SAMPLE_13F_XML)
    df = await fetcher.parse_13f_infotable("https://www.sec.gov/test.xml")
    assert len(df) == 1
    assert df.iloc[0]["name_of_issuer"] == "Apple Inc"
    assert df.iloc[0]["cusip"] == "037833100"
    assert df.iloc[0]["value"] == 100000000.0  # 千美元 -> 美元
    assert df.iloc[0]["shares"] == 10000
    await fetcher.close()
