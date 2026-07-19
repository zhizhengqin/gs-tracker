"""Signal aggregation engine — merge, dedup, sort signals from all sources."""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.signals.base import Signal, SignalStrength
from src.signals.thirteenf_adapter import ThirteenthFSignalAdapter
from src.signals.news_source import NewsSource
from src.signals.sec_8k_source import Sec8kSource

logger = logging.getLogger(__name__)


@dataclass
class AggregationResult:
    """Output of a signal aggregation run."""

    signals: List[Signal] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    source_status: Dict[str, str] = field(default_factory=dict)


class SignalAggregator:
    """Orchestrate multi-source signal fetching, merging, and deduplication."""

    def __init__(
        self,
        adapter_13f: Optional[ThirteenthFSignalAdapter] = None,
        news_source: Optional[NewsSource] = None,
        sec8k_source: Optional[Sec8kSource] = None,
    ) -> None:
        self.adapter_13f = adapter_13f or ThirteenthFSignalAdapter()
        self.news_source = news_source
        self.sec8k_source = sec8k_source

    async def aggregate(
        self,
        quarter: str,
        holdings_records: List[Dict[str, Any]],
        comparison: Optional[Dict[str, Any]] = None,
    ) -> AggregationResult:
        """Fetch all sources in parallel, merge, dedup, sort."""
        result = AggregationResult()
        all_signals: List[Signal] = []

        # 13F: synchronous conversion (no async needed)
        try:
            signals_13f = self.adapter_13f.to_signals(holdings_records, quarter, comparison)
            all_signals.extend(signals_13f)
            result.source_status["13F"] = "ok"
        except Exception as exc:
            logger.exception("13F adapter failed")
            result.errors.append(f"13F 信号转换失败: {exc}")
            result.source_status["13F"] = "error"

        # News + 8-K: parallel async fetch
        news_task = None
        sec8k_task = None

        if self.news_source:
            news_task = asyncio.create_task(self._safe_fetch(
                self.news_source, quarter, "news", result,
            ))
        if self.sec8k_source:
            sec8k_task = asyncio.create_task(self._safe_fetch(
                self.sec8k_source, quarter, "8-K", result,
            ))

        if news_task:
            news_signals = await news_task
            all_signals.extend(news_signals)
        if sec8k_task:
            sec8k_signals = await sec8k_task
            all_signals.extend(sec8k_signals)

        # Dedup by (source, title)
        seen: set = set()
        deduped: List[Signal] = []
        for s in all_signals:
            if s.dedupe_key not in seen:
                seen.add(s.dedupe_key)
                deduped.append(s)

        # Sort: strength (HIGH→LOW), then date (newest first)
        strength_order = {SignalStrength.HIGH: 0, SignalStrength.MEDIUM: 1, SignalStrength.LOW: 2}
        deduped.sort(key=lambda s: (strength_order.get(s.strength, 2), -s.published_at.timestamp()))

        result.signals = deduped
        return result

    async def _safe_fetch(
        self,
        source: Any,
        quarter: str,
        source_name: str,
        result: AggregationResult,
    ) -> List[Signal]:
        """Fetch from one source, catching all errors — one failure doesn't block others."""
        try:
            signals = await source.fetch(quarter)
            result.source_status[source_name] = "ok"
            return signals
        except Exception as exc:
            logger.exception("%s source failed", source_name)
            result.errors.append(f"{source_name} 信号获取失败: {exc}")
            result.source_status[source_name] = "error"
            return []

    async def close(self) -> None:
        """Release all source resources."""
        if self.news_source:
            await self.news_source.close()
        if self.sec8k_source:
            await self.sec8k_source.close()
