"""Tests for src.data_fetcher."""
import httpx
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


@pytest.mark.asyncio
async def test_fetch_latest_holdings_parses_index_json(httpx_mock):
    fetcher = SEC13FFetcher()

    submissions = {
        "filings": {
            "recent": {
                "form": ["13F-HR", "10-Q"],
                "accessionNumber": ["0001193125-26-000001", "0001193125-26-000002"],
                "reportDate": ["2026-03-31", "2026-02-28"],
            }
        }
    }
    index_json = {
        "directory": {
            "item": [
                {"name": "primary_doc.xml", "type": "1", "size": "12345"},
                {"name": "0001193125-26-000001-infotable.xml", "type": "1", "size": "67890"},
            ]
        }
    }

    httpx_mock.add_response(
        url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000886982&type=13F-HR&output=json",
        json=submissions,
    )
    httpx_mock.add_response(
        url="https://www.sec.gov/Archives/edgar/data/886982/000119312526000001/index.json",
        json=index_json,
    )
    httpx_mock.add_response(
        url="https://www.sec.gov/Archives/edgar/data/886982/000119312526000001/0001193125-26-000001-infotable.xml",
        text=SAMPLE_13F_XML,
    )

    df = await fetcher.fetch_latest_holdings()
    assert len(df) == 1
    assert df.iloc[0]["name_of_issuer"] == "Apple Inc"
    await fetcher.close()


@pytest.mark.asyncio
async def test_fetch_latest_holdings_missing_infotable_raises(httpx_mock):
    fetcher = SEC13FFetcher()

    submissions = {
        "filings": {
            "recent": {
                "form": ["13F-HR"],
                "accessionNumber": ["0001193125-26-000001"],
                "reportDate": ["2026-03-31"],
            }
        }
    }
    index_json = {"directory": {"item": [{"name": "primary_doc.xml", "type": "1", "size": "12345"}]}}

    httpx_mock.add_response(
        url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000886982&type=13F-HR&output=json",
        json=submissions,
    )
    httpx_mock.add_response(
        url="https://www.sec.gov/Archives/edgar/data/886982/000119312526000001/index.json",
        json=index_json,
    )

    with pytest.raises(ValueError, match="No infotable XML found"):
        await fetcher.fetch_latest_holdings()
    await fetcher.close()


def test_report_date_to_quarter():
    assert SEC13FFetcher.report_date_to_quarter("2026-03-31") == "2026-Q1"
    assert SEC13FFetcher.report_date_to_quarter("2026-06-30") == "2026-Q2"
    assert SEC13FFetcher.report_date_to_quarter("2026-09-30") == "2026-Q3"
    assert SEC13FFetcher.report_date_to_quarter("2026-12-31") == "2026-Q4"


@pytest.mark.asyncio
async def test_parse_13f_infotable_malformed_xml(httpx_mock):
    fetcher = SEC13FFetcher()
    httpx_mock.add_response(
        url="https://www.sec.gov/broken.xml",
        text="<not-an-information-table></no-tag-closure",
    )
    df = await fetcher.parse_13f_infotable("https://www.sec.gov/broken.xml")
    assert df.empty
    await fetcher.close()


@pytest.mark.asyncio
async def test_parse_13f_infotable_429_then_success(httpx_mock, monkeypatch):
    fetcher = SEC13FFetcher()

    async def _no_sleep(*_args, **_kwargs):
        pass

    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    httpx_mock.add_response(url="https://www.sec.gov/retry.xml", status_code=429)
    httpx_mock.add_response(url="https://www.sec.gov/retry.xml", text=SAMPLE_13F_XML)

    df = await fetcher.parse_13f_infotable("https://www.sec.gov/retry.xml")
    assert len(df) == 1
    assert df.iloc[0]["name_of_issuer"] == "Apple Inc"
    assert len(httpx_mock.get_requests(url="https://www.sec.gov/retry.xml")) == 2
    await fetcher.close()


@pytest.mark.asyncio
async def test_parse_13f_infotable_timeout_then_success(httpx_mock, monkeypatch):
    fetcher = SEC13FFetcher()

    async def _no_sleep(*_args, **_kwargs):
        pass

    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    httpx_mock.add_exception(url="https://www.sec.gov/retry.xml", exception=httpx.TimeoutException("timeout"))
    httpx_mock.add_response(url="https://www.sec.gov/retry.xml", text=SAMPLE_13F_XML)

    df = await fetcher.parse_13f_infotable("https://www.sec.gov/retry.xml")
    assert len(df) == 1
    assert df.iloc[0]["name_of_issuer"] == "Apple Inc"
    assert len(httpx_mock.get_requests(url="https://www.sec.gov/retry.xml")) == 2
    await fetcher.close()


@pytest.mark.asyncio
async def test_parse_13f_infotable_403_fatal(httpx_mock):
    fetcher = SEC13FFetcher()
    httpx_mock.add_response(url="https://www.sec.gov/forbidden.xml", status_code=403)

    with pytest.raises(httpx.HTTPStatusError):
        await fetcher.parse_13f_infotable("https://www.sec.gov/forbidden.xml")
    assert len(httpx_mock.get_requests(url="https://www.sec.gov/forbidden.xml")) == 1
    await fetcher.close()


@pytest.mark.asyncio
async def test_fetch_latest_holdings_populates_filing_info(httpx_mock):
    """filing_info dict should be populated with accession/report/filing/xml metadata."""
    fetcher = SEC13FFetcher()

    submissions = {
        "filings": {
            "recent": {
                "form": ["13F-HR"],
                "accessionNumber": ["0001193125-26-000001"],
                "reportDate": ["2026-03-31"],
                "filingDate": ["2026-05-15"],
            }
        }
    }
    index_json = {
        "directory": {
            "item": [
                {"name": "0001193125-26-000001-infotable.xml", "type": "1", "size": "67890"},
            ]
        }
    }

    httpx_mock.add_response(
        url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000886982&type=13F-HR&output=json",
        json=submissions,
    )
    httpx_mock.add_response(
        url="https://www.sec.gov/Archives/edgar/data/886982/000119312526000001/index.json",
        json=index_json,
    )
    httpx_mock.add_response(
        url="https://www.sec.gov/Archives/edgar/data/886982/000119312526000001/0001193125-26-000001-infotable.xml",
        text=SAMPLE_13F_XML,
    )

    filing_info: dict = {}
    df = await fetcher.fetch_latest_holdings(filing_info)

    assert len(df) == 1
    assert filing_info["accession_number"] == "0001193125-26-000001"
    assert filing_info["report_date"] == "2026-03-31"
    assert filing_info["filing_date"] == "2026-05-15"
    assert filing_info["period_of_report"] == "2026-03-31"
    assert filing_info["xml_url"].endswith("/0001193125-26-000001-infotable.xml")
    await fetcher.close()


@pytest.mark.asyncio
async def test_missing_infotable_leaves_filing_info_without_xml_url(httpx_mock):
    """Error path: early metadata is populated, but xml_url must not be set."""
    fetcher = SEC13FFetcher()

    submissions = {
        "filings": {
            "recent": {
                "form": ["13F-HR"],
                "accessionNumber": ["0001193125-26-000001"],
                "reportDate": ["2026-03-31"],
                "filingDate": ["2026-05-15"],
            }
        }
    }
    index_json = {
        "directory": {"item": [{"name": "primary_doc.xml", "type": "1", "size": "12345"}]}
    }

    httpx_mock.add_response(
        url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000886982&type=13F-HR&output=json",
        json=submissions,
    )
    httpx_mock.add_response(
        url="https://www.sec.gov/Archives/edgar/data/886982/000119312526000001/index.json",
        json=index_json,
    )

    filing_info: dict = {}
    with pytest.raises(ValueError, match="No infotable XML found"):
        await fetcher.fetch_latest_holdings(filing_info)

    assert filing_info["accession_number"] == "0001193125-26-000001"
    assert filing_info["report_date"] == "2026-03-31"
    assert "xml_url" not in filing_info
    await fetcher.close()
