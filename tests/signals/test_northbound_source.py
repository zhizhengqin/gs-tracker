"""Test northbound breadth data source (Eastmoney RPT_MUTUAL_QUOTA)."""
import pytest

from src.signals.base import SignalStrength
from src.signals.northbound_source import NorthboundSource


def _quota_payload(up_h=921, down_h=688, up_s=1287, down_s=554, date="2026-08-04"):
    return {
        "result": {
            "data": [
                {
                    "TRADE_DATE": f"{date} 00:00:00",
                    "MUTUAL_TYPE_NAME": "深股通",
                    "FUNDS_DIRECTION": "北向",
                    "BOARD_CODE": "BK0804",
                    "f104": up_s,
                    "f105": down_s,
                    "f106": 34,
                    "f3": 1.2,
                },
                {
                    "TRADE_DATE": f"{date} 00:00:00",
                    "MUTUAL_TYPE_NAME": "沪股通",
                    "FUNDS_DIRECTION": "北向",
                    "BOARD_CODE": "BK0707",
                    "f104": up_h,
                    "f105": down_h,
                    "f106": 30,
                    "f3": 0.8,
                },
            ]
        }
    }


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload

    async def get(self, url):
        if isinstance(self.payload, Exception):
            raise self.payload
        return _FakeResponse(self.payload)

    async def aclose(self):
        pass


class TestNorthboundSource:
    def test_source_name(self):
        assert NorthboundSource().source_name == "northbound"

    @pytest.mark.asyncio
    async def test_breadth_signal_parsing(self):
        src = NorthboundSource()
        src.client = _FakeClient(_quota_payload())
        signals, wm = await src.fetch_since()
        assert wm == "2026-08-04"
        assert len(signals) == 1
        s = signals[0]
        assert s.source == "northbound"
        assert s.institution_id == "all"
        assert "2208涨/1242跌" in s.title
        assert "沪股通" in s.summary and "深股通" in s.summary
        # 2208/1242 ≈ 1.78 → 中性 → MEDIUM
        assert s.strength == SignalStrength.MEDIUM
        # Honest wording: never claims a net inflow number
        assert "净流入" not in s.title

    @pytest.mark.asyncio
    async def test_extreme_breadth_is_high(self):
        src = NorthboundSource()
        src.client = _FakeClient(_quota_payload(up_h=1800, down_h=200, up_s=1900, down_s=150))
        signals, _ = await src.fetch_since()
        assert signals[0].strength == SignalStrength.HIGH
        assert "偏暖" in signals[0].summary

    @pytest.mark.asyncio
    async def test_same_day_watermark_suppresses_duplicates(self):
        src = NorthboundSource()
        src.client = _FakeClient(_quota_payload())
        signals, wm = await src.fetch_since()
        again, wm2 = await src.fetch_since(watermark=wm)
        assert again == []
        assert wm2 == wm

    @pytest.mark.asyncio
    async def test_api_failure_never_raises(self):
        import httpx
        src = NorthboundSource()
        src.client = _FakeClient(httpx.ConnectError("boom"))
        signals, wm = await src.fetch_since()
        assert signals == []
        assert wm is None
