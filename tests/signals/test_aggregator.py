"""Tests for src.signals.aggregator."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

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
    async def test_aggregate_sorts_by_scored_relevance(self):
        """Scorer re-ranks by relevance_score — HIGH before MEDIUM before LOW."""
        mock_13f = MagicMock()
        mock_13f.to_signals.return_value = []
        now = datetime.now(timezone.utc)
        # All signals recent (time decay ≈ 1) so scorer preserves strength order
        high1 = Signal(
            title="High A", source="news",
            published_at=now - timedelta(hours=2),
            summary="A", companies=["GS"], strength=SignalStrength.HIGH,
        )
        low = Signal(
            title="Low", source="news",
            published_at=now - timedelta(hours=1),
            summary="Low", companies=["GS"], strength=SignalStrength.LOW,
        )
        medium = Signal(
            title="Medium", source="news",
            published_at=now - timedelta(hours=3),
            summary="M", companies=["GS"], strength=SignalStrength.MEDIUM,
        )
        high2 = Signal(
            title="High B", source="news",
            published_at=now - timedelta(hours=2),
            summary="B", companies=["GS"], strength=SignalStrength.HIGH,
        )
        mock_news = AsyncMock()
        mock_news.fetch.return_value = [high1, low, medium, high2]
        mock_8k = AsyncMock()
        mock_8k.fetch.return_value = []

        aggregator = SignalAggregator(
            adapter_13f=mock_13f,
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        result = await aggregator.aggregate(
            quarter="2026-Q2", holdings_records=[],
        )
        strengths = [s.strength for s in result.signals]
        # HIGH before MEDIUM before LOW (scorer preserves original strength
        # when time decay is negligible)
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

    @pytest.mark.asyncio
    async def test_aggregate_populates_cross_refs(self):
        """Signals sharing companies across different sources get cross_refs."""
        now = datetime.now(timezone.utc)
        s1 = Signal(
            title="高盛增持苹果",
            source="13F",
            published_at=now - timedelta(hours=4),
            summary="苹果仓位增加",
            companies=["AAPL"],
            strength=SignalStrength.HIGH,
        )
        s2 = Signal(
            title="Goldman Raises Apple Target",
            source="news",
            published_at=now - timedelta(hours=2),
            summary="Apple target raised",
            companies=["AAPL"],
            strength=SignalStrength.MEDIUM,
        )
        s3 = Signal(
            title="Microsoft Unrelated",
            source="news",
            published_at=now - timedelta(hours=1),
            summary="MSFT only",
            companies=["MSFT"],
            strength=SignalStrength.LOW,
        )

        mock_13f = MagicMock()
        mock_13f.to_signals.return_value = [s1]
        mock_news = AsyncMock()
        mock_news.fetch.return_value = [s2, s3]
        mock_8k = AsyncMock()
        mock_8k.fetch.return_value = []

        aggregator = SignalAggregator(
            adapter_13f=mock_13f,
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        result = await aggregator.aggregate(
            quarter="2026-Q3", holdings_records=[{"name_of_issuer": "Apple Inc", "value": 100.0}],
        )

        # s1 and s2 share AAPL across different sources → cross_refs populated
        s1_out = next(s for s in result.signals if s.title == "高盛增持苹果")
        s2_out = next(s for s in result.signals if s.title == "Goldman Raises Apple Target")
        s3_out = next(s for s in result.signals if s.title == "Microsoft Unrelated")

        assert len(s1_out.cross_refs) >= 1
        assert len(s2_out.cross_refs) >= 1
        assert s3_out.cross_refs == []  # MSFT only, no cross-source match

        # Cross-refs use human-readable "source:title" format
        assert any("news:Goldman Raises Apple Target" in ref for ref in s1_out.cross_refs)
        assert any("13F:高盛增持苹果" in ref for ref in s2_out.cross_refs)

    @pytest.mark.asyncio
    async def test_aggregate_scorer_upgrades_strength(self):
        """Cross-source validation bonus can upgrade signal strength."""
        now = datetime.now(timezone.utc)
        s1 = Signal(
            title="高盛建仓英伟达",
            source="13F",
            published_at=now - timedelta(hours=3),
            summary="新建 NVDA 仓位",
            companies=["NVDA"],
            strength=SignalStrength.HIGH,
        )
        s2 = Signal(
            title="高盛 8-K: NVDA 投资披露",
            source="8-K",
            published_at=now - timedelta(hours=2),
            summary="重大持仓披露",
            companies=["NVDA"],
            strength=SignalStrength.LOW,
        )

        mock_13f = MagicMock()
        mock_13f.to_signals.return_value = [s1]
        mock_news = AsyncMock()
        mock_news.fetch.return_value = []
        mock_8k = AsyncMock()
        mock_8k.fetch.return_value = [s2]

        aggregator = SignalAggregator(
            adapter_13f=mock_13f,
            news_source=mock_news,
            sec8k_source=mock_8k,
        )
        result = await aggregator.aggregate(
            quarter="2026-Q3", holdings_records=[{"name_of_issuer": "NVIDIA", "value": 100.0}],
        )

        s2_out = next(s for s in result.signals if s.title == "高盛 8-K: NVDA 投资披露")
        # Cross-ref bonus (2.0) pushes LOW (base ~1.8) past MEDIUM threshold (3.0)
        assert s2_out.strength == SignalStrength.MEDIUM
        assert len(s2_out.cross_refs) >= 1
