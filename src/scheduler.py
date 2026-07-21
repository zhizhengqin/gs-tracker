"""Task scheduler for periodic data fetching and reporting."""

import argparse
import asyncio
import logging
import signal
from typing import Optional

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import ensure_directories

logger = logging.getLogger(__name__)


class GSScheduler:
    """Schedule recurring 13F checks and signal monitoring."""

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    def start(self) -> None:
        """Start the scheduler."""
        self.scheduler.start()
        logger.info("Scheduler started")

    def schedule_quarterly_check(self) -> None:
        """Schedule a job to check for new 13F filings after each deadline."""
        # Run weekly on Monday at 09:00 CST; actual logic checks for new filings.
        self.scheduler.add_job(
            self.run_quarterly_pipeline,
            CronTrigger(day_of_week="mon", hour=9, minute=0),
            id="quarterly_check",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

    def schedule_daily_intel(self) -> None:
        """Schedule the lightweight daily intelligence job (Mon-Fri, 17:00 CST).

        17:00 Beijing ≈ 04:00-05:00 US Eastern — captures overnight
        disclosures and news from the previous US trading day.
        """
        self.scheduler.add_job(
            self.run_daily_intel,
            CronTrigger(day_of_week="mon-fri", hour=17, minute=0),
            id="daily_intel",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )

    async def run_quarterly_pipeline(self) -> None:
        """Run the full quarterly fetch + analyze + report pipeline."""
        from src.main import run_pipeline

        try:
            await run_pipeline()
        except Exception:
            logger.exception("Quarterly pipeline failed")

    async def run_daily_intel(self) -> None:
        """Run the lightweight daily intelligence job."""
        from src.main import run_daily_intel

        try:
            result = await run_daily_intel()
            logger.info(
                "Daily intel: %d new signals, %d total scored, status=%s, errors=%d",
                result["new_signals"],
                result["total_scored"],
                result["source_status"],
                len(result["errors"]),
            )
        except Exception:
            logger.exception("Daily intel job failed")

    def shutdown(self) -> None:
        try:
            self.scheduler.shutdown()
            logger.info("Scheduler stopped")
        except SchedulerNotRunningError:
            logger.debug("Scheduler was not running")


async def main(
    shutdown_event: Optional[asyncio.Event] = None,
    run_now: bool = False,
) -> None:
    """Start the scheduler and keep running until SIGINT or SIGTERM."""
    ensure_directories()

    scheduler = GSScheduler()

    if run_now:
        logger.info("Running pipeline immediately (--run-now)")
        await scheduler.run_quarterly_pipeline()

    scheduler.schedule_quarterly_check()
    scheduler.schedule_daily_intel()
    scheduler.start()

    stop_event = shutdown_event or asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        scheduler.shutdown()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="GS-Tracker periodic scheduler")
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run the full pipeline immediately on startup, then begin scheduling",
    )
    args = parser.parse_args()
    asyncio.run(main(run_now=args.run_now))
