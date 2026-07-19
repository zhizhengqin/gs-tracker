"""Tests for src.signals.aggregator."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.signals.aggregator import AggregationResult, SignalAggregator
from src.signals.base import Signal, SignalStrength


def make_signal(title, source, companies=None, strength=None):
    return Signal(
        title=title,
        source=source,
        published_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
        summary=f"Summary for {title}",
        companies=companies or ["GS"],
        strength=strength or SignalStrength.MEDIUM,
    )


class TestSignalAggregator:
    @pytest.mark.asyncio
    async def test_aggregate_merges_sources(self):
        mock_13f = MagicMock()
        mock_13f.to_signals.return_value = [
            make_signal("高盛持仓: Apple Inc", "13F", companies=["Apple Inc"]),
            make_signal("高盛持仓: Microsoft Corp", "13F", companies=["Microsoft Corp"]),
        ]
        mock_news = AsyncMock()
        mock_news.fetch.return_value = [
            make_signal("Goldman Increases Apple Stake", "news", companies=["AAPL"]),
            make_signal("Goldman Tech Pivot", "news", companies=["GS"]),
        ]
        mock_8k = AsyncMock()
        mock_8k.fetch.return_value = [
            make_signal("高盛 8-K: 财务业绩披露", "8-K", companies=["GS"]),
        ]

        aggregator = SignalAggregator(
            adapter_13f=mock_13f,
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        result = await aggregator.aggregate(
            quarter="2026-Q2",
            holdings_records=[
                {"name_of_issuer": "Apple Inc", "value": 100.0},
                {"name_of_issuer": "Microsoft Corp", "value": 50.0},
            ],
            comparison={"total_value": 150.0},
        )

        assert isinstance(result, AggregationResult)
        assert len(result.signals) >= 5  # 2 13F + 2 news + 1 8-K
        assert result.errors == []
        mock_news.fetch.assert_awaited_once_with("2026-Q2")
        mock_8k.fetch.assert_awaited_once_with("2026-Q2")

    @pytest.mark.asyncio
    async def test_aggregate_handles_source_failure(self):
        mock_13f = MagicMock()
        mock_13f.to_signals.return_value = [
            make_signal("高盛持仓: Apple Inc", "13F"),
        ]
        mock_news = AsyncMock()
        mock_news.fetch.side_effect = RuntimeError("RSS source down")
        mock_8k = AsyncMock()
        mock_8k.fetch.return_value = [
            make_signal("高盛 8-K: 重大事件", "8-K"),
        ]

        aggregator = SignalAggregator(
            adapter_13f=mock_13f,
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        result = await aggregator.aggregate(
            quarter="2026-Q2",
            holdings_records=[{"name_of_issuer": "Apple Inc", "value": 100.0}],
        )

        assert len(result.signals) >= 2  # 13F + 8-K, news failed
        assert len(result.errors) == 1
        assert "news" in result.errors[0].lower()

    @pytest.mark.asyncio
    async def test_aggregate_dedup_by_title(self):
        mock_13f = MagicMock()
        mock_13f.to_signals.return_value = []
        mock_news = AsyncMock()
        mock_news.fetch.return_value = [
            make_signal("Goldman Increases Apple Stake", "news"),
            make_signal("Goldman Increases Apple Stake", "news"),  # duplicate
        ]
        mock_8k = AsyncMock()
        mock_8k.fetch.return_value = []

        aggregator = SignalAggregator(
            adapter_13f=mock_13f,
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        result = await aggregator.aggregate(
            quarter="2026-Q2",
            holdings_records=[],
        )
        assert len(result.signals) == 1  # deduped

    @pytest.mark.asyncio
    async def test_aggregate_all_sources_fail(self):
        mock_13f = MagicMock()
        mock_13f.to_signals.side_effect = RuntimeError("fail")
        mock_news = AsyncMock()
        mock_news.fetch.side_effect = RuntimeError("fail")
        mock_8k = AsyncMock()
        mock_8k.fetch.side_effect = RuntimeError("fail")

        aggregator = SignalAggregator(
            adapter_13f=mock_13f,
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        result = await aggregator.aggregate(
            quarter="2026-Q2",
            holdings_records=[],
        )
        assert result.signals == []
        assert len(result.errors) == 3

    @pytest.mark.asyncio
    async def test_aggregate_sorts_by_strength_then_date(self):
        mock_13f = MagicMock()
        mock_13f.to_signals.return_value = []
        old_high = Signal(
            title="Old High",
            source="news",
            published_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            summary="Old",
            companies=["GS"],
            strength=SignalStrength.HIGH,
        )
        new_low = Signal(
            title="New Low",
            source="news",
            published_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            summary="New",
            companies=["GS"],
            strength=SignalStrength.LOW,
        )
        old_medium = Signal(
            title="Old Medium",
            source="news",
            published_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            summary="Old",
            companies=["GS"],
            strength=SignalStrength.MEDIUM,
        )
        new_high = Signal(
            title="New High",
            source="news",
            published_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            summary="New",
            companies=["GS"],
            strength=SignalStrength.HIGH,
        )
        mock_news = AsyncMock()
        mock_news.fetch.return_value = [old_high, new_low, old_medium, new_high]
        mock_8k = AsyncMock()
        mock_8k.fetch.return_value = []

        aggregator = SignalAggregator(
            adapter_13f=mock_13f,
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        result = await aggregator.aggregate(
            quarter="2026-Q2",
            holdings_records=[],
        )
        strengths = [s.strength for s in result.signals]
        # HIGH before MEDIUM before LOW
        assert strengths[0] == SignalStrength.HIGH
        assert strengths[1] == SignalStrength.HIGH
        assert strengths[2] == SignalStrength.MEDIUM
        assert strengths[3] == SignalStrength.LOW

    @pytest.mark.asyncio
    async def test_close_releases_resources(self):
        mock_news = AsyncMock()
        mock_8k = AsyncMock()
        aggregator = SignalAggregator(
            adapter_13f=AsyncMock(),
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        await aggregator.close()
        mock_news.close.assert_awaited_once()
        mock_8k.close.assert_awaited_once()
