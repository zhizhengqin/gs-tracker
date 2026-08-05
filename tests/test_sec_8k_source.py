"""Tests for src.signals.sec_8k_source."""
import pytest

from src.signals.sec_8k_source import Sec8kSource


def test_company_tag_defaults_to_gs():
    src = Sec8kSource()
    assert src.company_tag == "GS"


def test_company_tag_parameterized_for_other_institutions():
    src = Sec8kSource(cik="0000019617", company_tag="JPM")
    assert src.company_tag == "JPM"
    assert src.cik == "19617"


def test_institution_id_defaults_to_gs():
    assert Sec8kSource().institution_id == "gs"


def _fake_submissions_payload():
    return {
        "filings": {
            "recent": {
                "form": ["8-K"],
                "filingDate": ["2026-08-01"],
                "accessionNumber": ["0000000000-26-000001"],
                "primaryDocument": ["doc.htm"],
                "items": ["2.02"],
            }
        }
    }


class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return _fake_submissions_payload()


@pytest.mark.asyncio
async def test_signals_use_configured_company_tag(monkeypatch):
    src = Sec8kSource(cik="0000019617", company_tag="JPM",
                      display_name="摩根大通", institution_id="jpm")

    async def _fake_get(url, **kw):
        return _FakeResp()

    monkeypatch.setattr(src.client, "get", _fake_get)
    signals = await src.fetch("2026-Q3")
    assert signals, "expected at least one parsed 8-K signal"
    assert all(s.companies == ["JPM"] for s in signals)
    assert all("摩根大通" in s.title for s in signals)
    assert all("摩根大通" in s.summary for s in signals)
    assert all(s.institution_id == "jpm" for s in signals)


@pytest.mark.asyncio
async def test_signals_default_display_name_is_gaosheng(monkeypatch):
    src = Sec8kSource()

    async def _fake_get(url, **kw):
        return _FakeResp()

    monkeypatch.setattr(src.client, "get", _fake_get)
    signals = await src.fetch("2026-Q3")
    assert signals
    assert all("高盛" in s.title for s in signals)
