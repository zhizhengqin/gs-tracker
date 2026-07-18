"""CLI entry point and one-shot pipeline runner."""
import argparse
import asyncio
import logging
import sys
from typing import Optional

import pandas as pd

from src.analyzer import GSAnalyzer
from src.config import (  # noqa: F401  (REPORT_OUTPUT_DIR kept as a patchable name for tests)
    FEISHU_WEBHOOK,
    PUBLIC_BASE_URL,
    REPORT_OUTPUT_DIR,
    ensure_directories,
)
from src.data_fetcher import SEC13FFetcher
from src.notifier import Notification, Notifier, _format_summary
from src.quarter_compare import QuarterComparator
from src.reporter import ReportGenerator
from src.storage import get_holdings, init_db, mark_notification_sent, save_holdings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


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

    reporter = ReportGenerator()
    report_path = await asyncio.to_thread(reporter.generate_report, quarter, df, analysis)
    logger.info("Report generated at %s", report_path)

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

    if FEISHU_WEBHOOK:
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
            mark_notification_sent(quarter)
        except Exception:
            logger.exception("Failed to send notification for %s", quarter)
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
