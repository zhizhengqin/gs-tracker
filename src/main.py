"""CLI entry point and one-shot pipeline runner."""
import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
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
from src.daily_report import ensure_daily_report, refresh_daily_report
from src.signal_analysis import auto_analyze_high_signals
from src.llm_config import resolve_llm_config
from src.notifier import Notification, Notifier, _format_summary
from src.quarter_compare import QuarterComparator
from src.reporter import ReportGenerator
from src.signals.aggregator import SignalAggregator, dedup_across_institutions
from src.signals.ai_triage import AiTriage
from src.signals.base import Signal
from src.signals.news_source import NewsSource
from src.signals.jpm_research_source import JPMResearchSource
from src.signals.topic_source import TopicSource
from src.signals.webpage_source import WebpageSource
from src.signals.base import institution_display
from src.signals.scorer import SignalScorer
from src.signals.sec_8k_source import Sec8kSource
from src.signals.research_view_source import ResearchViewSource
from src.signals.thirteen_dg_source import ThirteenDGSource
from src.signals.qfii_source import QFIISource
from src.signals.northbound_source import NorthboundSource
from src.storage import (
    cleanup_expired_signals,
    get_default_llm_model,
    get_holdings,
    get_institutions,
    get_recent_signals,
    get_setting,
    get_sources_config,
    get_source_state,
    init_db,
    is_notification_sent,
    mark_notification_sent,
    save_holdings,
    save_signal_payload,
    save_signal_run,
    save_signals_incremental,
    save_source_state,
    set_setting,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# The dashboard and daily report think in Asia/Shanghai days (UTC+8).
BEIJING_TZ = timezone(timedelta(hours=8))


ALL_SOURCE_NAMES = ("13F", "8-K", "13D/13G", "research_view", "news", "news_jpm", "jpm_research", "macro_view", "qfii", "northbound")


def _enabled_source_names() -> set:
    """Enabled source names from the merged sources_config (default: all on).

    Uses get_sources_config() so built-ins added after an install saved its
    config still appear (the stored list alone would hide them forever).
    """
    try:
        return {s.get("name", "") for s in get_sources_config() if s.get("enabled", True)}
    except Exception:
        logger.warning("Failed to read sources_config; defaulting to all sources enabled")
    return set(ALL_SOURCE_NAMES)


def _custom_source_configs() -> list:
    """Custom (non-builtin) source entries from the merged sources_config."""
    try:
        return [s for s in get_sources_config() if not s.get("builtin", False)]
    except Exception:
        logger.warning("Failed to parse custom sources from sources_config")
    return []


def _build_daily_sources(institution_id: str = "gs") -> list:
    """Instantiate daily-intel sources, honoring per-source enable switches."""
    enabled = _enabled_source_names()
    sources: list[tuple[str, object]] = []
    # SEC filing sources run once per enabled institution, labeled
    # "<source> · <机构名>" so the progress panel shows both clearly.
    institutions = [i for i in get_institutions() if i.get("enabled", True)]
    if "8-K" in enabled:
        for inst in institutions:
            sources.append((
                f"8-K · {inst['display_name']}",
                Sec8kSource(
                    cik=inst["cik"],
                    company_tag=inst["id"].upper(),
                    display_name=inst["display_name"],
                    institution_id=inst["id"],
                ),
            ))
    if "13D/13G" in enabled:
        for inst in institutions:
            sources.append((
                f"13D/13G · {inst['display_name']}",
                ThirteenDGSource(
                    cik=inst["cik"],
                    company_tag=inst["id"].upper(),
                    display_name=inst["display_name"],
                    institution_id=inst["id"],
                ),
            ))
    if "research_view" in enabled:
        sources.append(("research_view", ResearchViewSource()))
    if "qfii" in enabled:
        sources.append(("qfii", QFIISource()))
    if "northbound" in enabled:
        sources.append(("northbound", NorthboundSource()))
    if "news" in enabled:
        feeds = list(RSS_FEEDS)
        if feeds:
            sources.append(("news", NewsSource(rss_urls=feeds)))
    if "news_jpm" in enabled:
        feeds = list(RSS_FEEDS)
        if feeds:
            # Distinct source_name so JPM-tagged items never fingerprint-collide
            # with the GS-tagged copy of the same article.
            sources.append(("news_jpm", NewsSource(
                rss_urls=feeds, source_name="news_jpm", institution_id="jpm",
                exclude_viewpoint=True,
            )))
    if "jpm_research" in enabled:
        feeds = list(RSS_FEEDS)
        if feeds:
            sources.append(("jpm_research", JPMResearchSource(rss_urls=feeds)))
    # Custom sources from the settings page (one instance per source)
    for entry in _custom_source_configs():
        if entry.get("name") not in enabled:
            continue
        if entry.get("type") == "rss" and entry.get("url"):
            sources.append((
                entry["name"],
                NewsSource(
                    rss_urls=[entry["url"]],
                    source_name=entry["name"],
                    filter_policy=entry.get("filter_policy", "gs_only"),
                ),
            ))
        elif entry.get("type") == "webpage" and entry.get("url"):
            sources.append((
                entry["name"],
                WebpageSource(
                    url=entry["url"],
                    instruction=entry.get("instruction", ""),
                    source_name=entry["name"],
                    filter_policy=entry.get("filter_policy", "gs_only"),
                    llm_config=resolve_llm_config(get_default_llm_model()),
                    get_setting=get_setting,
                    set_setting=set_setting,
                    recent_titles=lambda name: {
                        s.title for s in get_recent_signals(days=30) if s.source == name
                    },
                ),
            ))
        elif entry.get("type") == "topic" and entry.get("instruction"):
            sources.append((
                entry["name"],
                TopicSource(
                    topic=entry["instruction"],
                    source_name=entry["name"],
                    filter_policy=entry.get("filter_policy", "gs_only"),
                    llm_config=resolve_llm_config(get_default_llm_model()),
                    get_setting=get_setting,
                    set_setting=set_setting,
                    recent_titles=lambda name: {
                        s.title for s in get_recent_signals(days=30) if s.source == name
                    },
                ),
            ))
    return sources


async def run_daily_intel_stream():
    """Async generator: run daily intel with per-source progress events (SSE)."""
    ensure_directories()
    init_db()

    def _note_of(src: object) -> str:
        # fetch_note is an optional string protocol (webpage sources); mocks
        # and non-conforming sources may return anything — only strings count.
        note = getattr(src, "fetch_note", "")
        return note if isinstance(note, str) else ""

    sources = _build_daily_sources("gs")
    source_names = [n for n, _ in sources]
    yield json.dumps({"event": "start", "sources": source_names})

    new_signals: list[Signal] = []
    source_status: dict[str, str] = {}
    errors: list[str] = []

    async def _fetch_one(name: str, src: object) -> tuple[str, list[Signal], str]:
        try:
            if hasattr(src, "fetch_since"):
                wm = get_source_state(name, "default") if name != "8-K" else None
                result, new_wm = await src.fetch_since(watermark=wm)
                if new_wm and new_wm != wm:
                    save_source_state(name, "default", new_wm)
                source_status[name] = "ok"
                return name, result, _note_of(src)
            else:
                result = await src.fetch("")
                source_status[name] = "ok"
                return name, result, _note_of(src)
        except Exception as exc:
            logger.exception("%s source failed in daily intel", name)
            errors.append(f"{name}: {exc}")
            source_status[name] = "error"
            return name, [], ""

    # Run sources in parallel, yield progress as each completes.
    # NOTE: as_completed yields wrapper coroutines, not the original tasks,
    # so results must carry the source name (a task->name dict lookup fails).
    tasks = [asyncio.create_task(_fetch_one(n, s)) for n, s in sources]
    for fut in asyncio.as_completed(tasks):
        name, sigs, note = await fut
        new_signals.extend(sigs)
        status = source_status.get(name, "ok")
        yield json.dumps({
            "event": "source_done",
            "source": name,
            "status": status,
            "count": len(sigs),
            "error": errors[-1] if status == "error" and errors else "",
        })
        if note:
            yield json.dumps({"event": "triage_note", "source": name, "note": note})

    # AI pre-ingest triage: news-type sources only (builtin "news" + custom
    # sources). Authoritative SEC/research sources bypass triage entirely.
    custom_entries = _custom_source_configs()
    triageable_names = {"news", "news_jpm"} | {e.get("name", "") for e in custom_entries}
    triage_groups: dict[str, list[int]] = {}
    for idx, sig in enumerate(new_signals):
        if sig.source in triageable_names:
            triage_groups.setdefault(sig.source, []).append(idx)

    if triage_groups:
        policy_by_source = {"news": "gs_only", "news_jpm": "jpm_only"}
        policy_by_source.update(
            {e["name"]: e.get("filter_policy", "gs_only") for e in custom_entries}
        )
        llm_cfg = resolve_llm_config(get_default_llm_model())
        triage = AiTriage(llm_cfg, get_setting, set_setting)
        keep_indices: set[int] = set()
        for source_name, idxs in triage_groups.items():
            items = [
                {"title": new_signals[i].title, "summary": new_signals[i].summary}
                for i in idxs
            ]
            result = await triage.triage(items, source_name, policy_by_source[source_name])
            for kept in result.kept_indices:
                keep_indices.add(idxs[kept])
            if result.fallback_used:
                yield json.dumps({
                    "event": "triage_note",
                    "source": source_name,
                    "note": result.note,
                })
        new_signals = [
            sig for idx, sig in enumerate(new_signals)
            if sig.source not in triageable_names or idx in keep_indices
        ]

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
                f"[{institution_display(getattr(id_to_signal[rid], 'institution_id', 'gs'))}] "
                f"{id_to_signal[rid].source}:{id_to_signal[rid].title}"
                for rid in sc.cross_refs
                if rid in id_to_signal
            ]
            sig.strength = sc.final_strength
            sig.cross_institutional = sc.cross_institutional

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

    # Auto-generate AI analysis for new HIGH-strength signals. Awaited before
    # the complete event so a manual run's view reload shows them right away;
    # failures never block the pipeline (manual click retries later).
    if new_signals:
        try:
            analyzed = await auto_analyze_high_signals(new_signals)
            if analyzed:
                logger.info("Auto-generated AI analysis for %d high-priority signals", analyzed)
        except Exception:
            logger.exception("Auto signal analysis failed")

    # Kick off daily report generation (add-on: never blocks/fails the pipeline;
    # web SSE keeps the loop alive so the task completes). New signals force a
    # regeneration so the hourly job keeps today's summary current; otherwise
    # only generate when no report exists yet.
    try:
        today = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
        if new_signals:
            await refresh_daily_report(today)
        else:
            await ensure_daily_report(today)
    except Exception:
        logger.exception("Failed to schedule daily report generation")

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
    # Scheduler/CLI path: wait for the report so one-shot processes don't exit
    # before it lands (dedupe: the stream already scheduled it above).
    try:
        today = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
        task = await ensure_daily_report(today)
        if task is not None:
            await task
    except Exception:
        logger.exception("Daily report generation wait failed")

    return summary


async def run_pipeline_stream(institution_id: str = "gs"):
    """Async generator: full pipeline with per-step/per-source progress (SSE).

    institution_id selects which institution's 13F/8-K data to pull;
    CIK and display label are resolved from the institutions table.
    """
    ensure_directories()
    init_db()

    from src.storage import get_institutions
    inst_map = {i["id"]: i for i in get_institutions()}
    inst = inst_map.get(institution_id)
    if inst is None:
        raise ValueError(f"未知机构: {institution_id}")
    cik = inst["cik"] or "0000886982"
    inst_label = inst["display_name"]
    inst_label_en = f"{inst['display_name']}({inst['name']})"

    quarter = "2026-Q1"

    source_names = ["13F", "8-K"] + (["news"] if RSS_FEEDS else [])
    yield json.dumps({"event": "start", "sources": source_names})

    def _step(step: str, status: str, label: str, detail: str = "") -> str:
        return json.dumps({
            "event": "step",
            "step": step,
            "status": status,
            "label": label,
            "detail": detail,
        })

    yield _step("holdings", "running", "抓取 13F 持仓")
    filing_info: dict[str, str] = {}
    async with SEC13FFetcher(cik=cik) as fetcher:
        df = await fetcher.fetch_latest_holdings(filing_info)
        if filing_info.get("report_date"):
            quarter = SEC13FFetcher.report_date_to_quarter(filing_info["report_date"])

    save_holdings(cik, quarter, df.to_dict("records"), filing_info)
    yield _step("holdings", "done", "抓取 13F 持仓", f"{quarter} · {len(df)} 条持仓")

    yield _step("analysis", "running", "AI 持仓分析")
    llm_cfg = resolve_llm_config(get_default_llm_model())
    analyzer = GSAnalyzer(
        api_key=llm_cfg["api_key"],
        auth_token=llm_cfg["auth_token"],
        base_url=llm_cfg["base_url"],
        model=llm_cfg["model"],
        institution_label=inst_label_en,
    )
    analysis = await analyzer.analyze_holdings(df)
    yield _step("analysis", "done", "AI 持仓分析")

    summary = None
    previous_quarter = _previous_quarter(quarter)
    if previous_quarter:
        previous_records = get_holdings(cik, previous_quarter)
        if previous_records:
            yield _step("comparison", "running", "季度持仓对比")
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
            yield _step(
                "comparison", "done", "季度持仓对比",
                f"对比 {previous_quarter}：新增 {summary['new_positions']} · 清仓 {summary['sold_positions']}",
            )

    # --- Multi-source signal aggregation ---
    aggregation_signals = []
    aggregation_errors = []
    aggregation_status = {}
    aggregation_ok = False
    aggregator = SignalAggregator(
        news_source=(
            NewsSource(
                rss_urls=RSS_FEEDS,
                source_name="news" if institution_id == "gs" else f"news_{institution_id}",
                filter_policy="gs_only" if institution_id == "gs" else f"{institution_id}_only",
                institution_id=institution_id,
            )
            if RSS_FEEDS else None
        ),
        sec8k_source=Sec8kSource(
            cik=cik,
            company_tag=institution_id.upper(),
            display_name=inst["display_name"],
            institution_id=institution_id,
        ),
    )
    try:
        # Bridge the aggregator's sync progress callback into this async
        # generator: the callback queues events, we drain them while awaiting.
        progress_queue: asyncio.Queue[str] = asyncio.Queue()

        def _progress_cb(event: dict) -> None:
            progress_queue.put_nowait(json.dumps(event))

        agg_task = asyncio.create_task(
            aggregator.aggregate(
                quarter, df.to_dict("records"), summary, progress_cb=_progress_cb,
            )
        )
        while not (agg_task.done() and progress_queue.empty()):
            try:
                yield progress_queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.1)
        aggregation = await agg_task
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

    yield _step("report", "running", "生成季度报告")
    reporter = ReportGenerator()
    report_path = await asyncio.to_thread(
        reporter.generate_report,
        quarter,
        df,
        analysis,
        signals=aggregation_signals,
        signal_errors=aggregation_errors,
        source_status=aggregation_status,
        institution_id=institution_id,
        institution_label=inst_label,
    )
    logger.info("Report generated at %s", report_path)
    yield _step("report", "done", "生成季度报告")

    if FEISHU_WEBHOOK:
        if is_notification_sent(quarter):
            logger.info(
                "Notification already sent for %s; skipping send", quarter
            )
        else:
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

    yield json.dumps({
        "event": "complete",
        "quarter": quarter,
        "signal_count": len(aggregation_signals),
        "source_status": aggregation_status,
        "errors": aggregation_errors,
    })


async def run_pipeline(institution_id: str = "gs") -> None:
    """Run the full fetch-analyze-report pipeline once (non-streaming wrapper)."""
    async for _event_json in run_pipeline_stream(institution_id):
        pass


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
