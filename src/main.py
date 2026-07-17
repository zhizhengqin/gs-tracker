"""CLI entry point and one-shot pipeline runner."""
import argparse
import asyncio
import logging
import sys

from src.analyzer import GSAnalyzer
from src.config import REPORT_OUTPUT_DIR, ensure_directories
from src.data_fetcher import SEC13FFetcher
from src.reporter import ReportGenerator
from src.storage import init_db, save_holdings

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

    save_holdings(cik, quarter, df.to_dict("records"))

    analyzer = GSAnalyzer()
    analysis = await analyzer.analyze_holdings(df)

    reporter = ReportGenerator()
    report_path = await asyncio.to_thread(reporter.generate_report, quarter, df, analysis)
    logger.info("Report generated at %s", report_path)


def main(argv=None) -> int:
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
