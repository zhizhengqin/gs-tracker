"""Test QFII data source (Eastmoney zlsj API)."""
import pytest

from src.signals.base import SignalStrength
from src.signals.qfii_source import QFIISource


def _reportdate_payload(date="2026-06-30"):
    return {"result": {"data": [{"REPORT_DATE": f"{date} 00:00:00"}]}}


def _zlsj_payload():
    return {
        "data": [
            {
                "SECURITY_NAME_ABBR": "宁德时代",
                "SECUCODE": "300750.SZ",
                "REPORT_DATE": "2026-06-30 00:00:00",
                "ORG_TYPE_NAME": "QFII",
                "HOULD_NUM": 1,
                "HOLD_VALUE": 10_760_000_000,
                "FREESHARES_RATIO": 0.64,
                "HOLDCHA": "新进",
                "HOLDCHA_RATIO": None,
            },
            {
                "SECURITY_NAME_ABBR": "宏发股份",
                "SECUCODE": "600885.SH",
                "REPORT_DATE": "2026-06-30 00:00:00",
                "ORG_TYPE_NAME": "QFII",
                "HOULD_NUM": 4,
                "HOLD_VALUE": 2_140_000_000,
                "FREESHARES_RATIO": 4.01,
                "HOLDCHA": "增仓",
                "HOLDCHA_RATIO": 15.5,
            },
        ]
    }


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    """Routes by URL substring to canned payloads."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def get(self, url):
        self.calls.append(url)
        for key, payload in self.routes.items():
            if key in url:
                if isinstance(payload, Exception):
                    raise payload
                return _FakeResponse(payload)
        return _FakeResponse({})

    async def aclose(self):
        pass


class TestQFIISource:
    def test_source_name(self):
        assert QFIISource().source_name == "qfii"

    def test_institution_id_stored(self):
        assert QFIISource().institution_id == "all"

    @pytest.mark.asyncio
    async def test_fetch_parses_zlsj_rows(self):
        src = QFIISource(max_items=5)
        src.client = _FakeClient({
            "RPT_MAIN_REPORTDATE": _reportdate_payload(),
            "zlsj/list": _zlsj_payload(),
        })
        signals = await src.fetch()
        assert len(signals) == 2

        new_entrant = signals[0]
        assert new_entrant.title == "QFII持仓: 宁德时代"
        assert new_entrant.source == "qfii"
        assert new_entrant.institution_id == "all"
        assert new_entrant.strength == SignalStrength.HIGH  # 新进 + 市值≥5亿
        assert "新进" in new_entrant.summary
        assert "107.6亿元" in new_entrant.summary

        add = signals[1]
        assert add.strength == SignalStrength.HIGH  # 增仓 + 市值21.4亿
        assert "增仓15.5%" in add.summary

    @pytest.mark.asyncio
    async def test_watermark_suppresses_same_quarter(self):
        src = QFIISource()
        src.client = _FakeClient({
            "RPT_MAIN_REPORTDATE": _reportdate_payload(),
            "zlsj/list": _zlsj_payload(),
        })
        signals, wm = await src.fetch_since()
        assert wm == "2026-06-30"
        assert signals

        # Same report date -> no new signals
        again, wm2 = await src.fetch_since(watermark=wm)
        assert again == []
        assert wm2 == wm

    @pytest.mark.asyncio
    async def test_api_failure_returns_empty_never_raises(self):
        import httpx
        src = QFIISource()
        src.client = _FakeClient({
            "RPT_MAIN_REPORTDATE": httpx.ConnectError("boom"),
        })
        signals, wm = await src.fetch_since()
        assert signals == []
        assert wm is None
