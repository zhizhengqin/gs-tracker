"""Task scheduler for periodic data fetching and reporting."""
import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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
        )

    async def run_quarterly_pipeline(self) -> None:
        """Run the full quarterly fetch + analyze + report pipeline."""
        raise NotImplementedError("TODO: implement pipeline")

    def shutdown(self) -> None:
        self.scheduler.shutdown()
