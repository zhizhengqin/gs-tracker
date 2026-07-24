"""CLI entry point and one-shot pipeline runner."""
import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from src.analyzer import GSAnalyzer
from src.config import (  # noqa: F401  (REPORT_OUTPUT_DIR kept as a patchable name for tests)
    RSS_FEEDS,
    FEISHU_WEBHOOK,
    PUBLIC_BASE_URL,
    REPORT_OUTPUT_DIR,
    ensure_directories,
)
from src.data_fetcher import SEC13FFetcher
from src.notifier import Notification, Notifier, _format_summary
from src.quarter_compare import QuarterComparator
from src.reporter import ReportGenerator
from src.signals.aggregator import SignalAggregator
from src.signals.base import Signal
from src.signals.news_source import NewsSource
from src.signals.scorer import SignalScorer
from src.signals.sec_8k_source import Sec8kSource
from src.signals.research_view_source import ResearchViewSource
from src.signals.thirteen_dg_source import ThirteenDGSource
from src.storage import (
    cleanup_expired_signals,
    get_holdings,
    get_recent_signals,
    get_setting,
    get_source_state,
    init_db,
    is_notification_sent,
    mark_notification_sent,
    save_holdings,
    save_signal_payload,
    save_signal_run,
    save_signals_incremental,
    save_source_state,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


ALL_SOURCE_NAMES = ("13F", "8-K", "13D/13G", "research_view", "news", "macro_view")


def _enabled_source_names() -> set:
    """Return enabled source names from the sources_config setting (default: all on)."""
    try:
        raw = get_setting("sources_config", "")
        if raw:
            config = json.loads(raw)
            return {s.get("name", "") for s in config if s.get("enabled", True)}
    except Exception:
        logger.warning("Failed to read sources_config; defaulting to all sources enabled")
    return set(ALL_SOURCE_NAMES)


def _all_rss_feeds() -> list:
    """Env-configured RSS feeds plus custom RSS sources added in the settings page."""
    feeds = list(RSS_FEEDS)
    try:
        raw = get_setting("sources_config", "")
        if raw:
            for entry in json.loads(raw):
                if entry.get("type") == "rss" and entry.get("enabled", True):
                    url = (entry.get("url") or "").strip()
                    if url and url not in feeds:
                        feeds.append(url)
    except Exception:
        logger.warning("Failed to parse custom RSS feeds from sources_config")
    return feeds


def _build_daily_sources() -> list:
    """Instantiate daily-intel sources, honoring per-source enable switches."""
    enabled = _enabled_source_names()
    sources: list[tuple[str, object]] = []
    if "8-K" in enabled:
        sources.append(("8-K", Sec8kSource()))
    if "13D/13G" in enabled:
        sources.append(("13D/13G", ThirteenDGSource()))
    if "research_view" in enabled:
        sources.append(("research_view", ResearchViewSource()))
    if "news" in enabled:
        feeds = _all_rss_feeds()
        if feeds:
            sources.append(("news", NewsSource(rss_urls=feeds)))
    return sources


async def run_daily_intel_stream():
    """Async generator: run daily intel with per-source progress events (SSE)."""
    ensure_directories()
    init_db()

    sources = _build_daily_sources()
    source_names = [n for n, _ in sources]
    yield json.dumps({"event": "start", "sources": source_names})

    new_signals: list[Signal] = []
    source_status: dict[str, str] = {}
    errors: list[str] = []

    async def _fetch_one(name: str, src: object) -> tuple[str, list[Signal]]:
        try:
            if hasattr(src, "fetch_since"):
                wm = get_source_state(name, "default") if name != "8-K" else None
                result, new_wm = await src.fetch_since(watermark=wm)
                if new_wm and new_wm != wm:
                    save_source_state(name, "default", new_wm)
                source_status[name] = "ok"
                return name, result
            else:
                result = await src.fetch("")
                source_status[name] = "ok"
                return name, result
        except Exception as exc:
            logger.exception("%s source failed in daily intel", name)
            errors.append(f"{name}: {exc}")
            source_status[name] = "error"
            return name, []

    # Run sources in parallel, yield progress as each completes.
    # NOTE: as_completed yields wrapper coroutines, not the original tasks,
    # so results must carry the source name (a task->name dict lookup fails).
    tasks = [asyncio.create_task(_fetch_one(n, s)) for n, s in sources]
    for fut in asyncio.as_completed(tasks):
        name, sigs = await fut
        new_signals.extend(sigs)
        status = source_status.get(name, "ok")
        yield json.dumps({
            "event": "source_done",
            "source": name,
            "status": status,
            "count": len(sigs),
            "error": errors[-1] if status == "error" and errors else "",
        })

    # Merge + score
    recent = get_recent_signals(days=30)
    combined = new_signals + recent
    if combined:
        scorer = SignalScorer()
        scored = scorer.score(combined)
        id_to_signal = {s.id: s for s in combined}
        for sc in scored:
            sig = sc.signal
            sig.cross_refs = [
                f"{id_to_signal[rid].source}:{id_to_signal[rid].title}"
                for rid in sc.cross_refs
                if rid in id_to_signal
            ]
            sig.strength = sc.final_strength

    now = datetime.now(timezone.utc)
    quarter = f"{now.year}-Q{(now.month - 1) // 3 + 1}"
    try:
        save_signals_incremental(quarter, combined if combined else new_signals)
        save_signal_run(quarter, job="daily", source_status=source_status, errors=errors)
    except Exception:
        logger.exception("Failed to persist daily intel signals")

    try:
        cleanup_expired_signals(90)
    except Exception:
        logger.exception("Daily cleanup failed")

    for _name, src in sources:
        try:
            await src.close()
        except Exception:
            logger.exception("Source close failed")

    yield json.dumps({
        "event": "complete",
        "new_signals": len(new_signals),
        "total_scored": len(combined),
        "source_status": source_status,
        "errors": errors,
    })


async def run_daily_intel() -> dict:
    """Non-streaming daily intel: consume the streaming job and return its summary."""
    summary: dict = {
        "new_signals": 0,
        "total_scored": 0,
        "source_status": {},
        "errors": [],
    }
    async for event_json in run_daily_intel_stream():
        data = json.loads(event_json)
        if data.get("event") == "complete":
            summary = {
                "new_signals": data.get("new_signals", 0),
                "total_scored": data.get("total_scored", 0),
                "source_status": data.get("source_status", {}),
                "errors": data.get("errors", []),
            }
    return summary


async def run_pipeline() -> None:
    """Run the full fetch-analyze-report pipeline once."""
    ensure_directories()
    init_db()

    quarter = "2026-Q1"
    cik = "0000886982"

    filing_info: dict[str, str] = {}
    async with SEC13FFetcher() as fetcher:
        df = await fetcher.fetch_latest_holdings(filing_info)
        if filing_info.get("report_date"):
            quarter = SEC13FFetcher.report_date_to_quarter(filing_info["report_date"])

    save_holdings(cik, quarter, df.to_dict("records"), filing_info)

    analyzer = GSAnalyzer()
    analysis = await analyzer.analyze_holdings(df)

    summary = None
    previous_quarter = _previous_quarter(quarter)
    if previous_quarter:
        previous_records = get_holdings(cik, previous_quarter)
        if previous_records:
            prev_df = pd.DataFrame(previous_records)
            comparison = QuarterComparator().compare(
                df, prev_df, quarter, previous_quarter
            )
            summary = {
                "total_value": float(df["value"].sum()),
                "new_positions": len(comparison.new_positions),
                "sold_positions": len(comparison.sold_positions),
                "increased_positions": len(comparison.increased_positions),
                "decreased_positions": len(comparison.decreased_positions),
            }

    # --- Multi-source signal aggregation ---
    aggregation_signals = []
    aggregation_errors = []
    aggregation_status = {}
    aggregation_ok = False
    aggregator = SignalAggregator(
        news_source=NewsSource(rss_urls=RSS_FEEDS) if RSS_FEEDS else None,
        sec8k_source=Sec8kSource(),
    )
    try:
        aggregation = await aggregator.aggregate(quarter, df.to_dict("records"), summary)
        aggregation_signals = aggregation.signals
        aggregation_errors = aggregation.errors
        aggregation_status = aggregation.source_status
        aggregation_ok = True
        logger.info(
            "Aggregated %d signals (errors: %d, status: %s)",
            len(aggregation_signals), len(aggregation_errors), aggregation_status,
        )
    except Exception as exc:
        logger.exception("Signal aggregation failed; report will lack signal panel")
        # Record the failure so the dashboard stops showing stale "ok" badges;
        # previously saved signals (last known good) are kept as-is.
        try:
            save_signal_run(
                quarter,
                job="reconciliation",
                source_status={},
                errors=[f"信号聚合失败: {exc}"],
            )
        except Exception:
            logger.exception("Failed to record signal run failure for %s", quarter)
    finally:
        await aggregator.close()

    if aggregation_ok:
        try:
            save_signal_payload(
                quarter,
                aggregation_signals,
                job="reconciliation",
                source_status=aggregation_status,
                errors=aggregation_errors,
            )
        except Exception:
            logger.exception("Failed to persist signals for %s", quarter)

    reporter = ReportGenerator()
    report_path = await asyncio.to_thread(
        reporter.generate_report,
        quarter,
        df,
        analysis,
        signals=aggregation_signals,
        signal_errors=aggregation_errors,
        source_status=aggregation_status,
    )
    logger.info("Report generated at %s", report_path)

    if FEISHU_WEBHOOK:
        if is_notification_sent(quarter):
            logger.info(
                "Notification already sent for %s; skipping send", quarter
            )
            return

        base = (PUBLIC_BASE_URL or "").rstrip("/")
        report_url = f"{base}/reports/{quarter}.html" if base else None
        if not base:
            logger.warning("PUBLIC_BASE_URL not set; notification will not include report link")

        notification = Notification(
            title=f"高盛动向情报 — {quarter} 报告已生成",
            body=_format_summary(summary),
            link=report_url,
        )
        notifier = Notifier()
        try:
            await notifier.send(notification)
        except Exception:
            logger.exception("Failed to send notification for %s", quarter)
        else:
            mark_notification_sent(quarter)
        finally:
            await notifier.close()


def _previous_quarter(quarter: str) -> Optional[str]:
    """Return the quarter before the given one, or None for the first quarter."""
    year_str, q = quarter.split("-")
    year = int(year_str)
    q_num = int(q.replace("Q", ""))
    if q_num == 1:
        return f"{year - 1}-Q4"
    return f"{year}-Q{q_num - 1}"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="GS-Tracker CLI")
    parser.add_argument("--run-now", action="store_true", help="Run pipeline once immediately")
    args = parser.parse_args(argv)

    if args.run_now:
        asyncio.run(run_pipeline())
        return 0

    parser.print_help()
    parser.exit(1)


if __name__ == "__main__":
    sys.exit(main())
