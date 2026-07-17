"""CLI entry point and one-shot pipeline runner."""
import argparse
import asyncio
import logging
import sys

from src.config import ensure_directories

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_pipeline() -> None:
    """Run the full fetch-analyze-report pipeline once."""
    ensure_directories()
    logger.info("Running GS-Tracker pipeline")
    # TODO: wire up fetcher, analyzer, reporter, notifier
    raise NotImplementedError("TODO: implement pipeline wiring")


def main() -> int:
    parser = argparse.ArgumentParser(description="GS-Tracker CLI")
    parser.add_argument("--run-now", action="store_true", help="Run pipeline once immediately")
    parser.add_argument("--serve", action="store_true", help="Start the scheduler and web server")
    args = parser.parse_args()

    if args.run_now:
        asyncio.run(run_pipeline())
        return 0

    if args.serve:
        # TODO: start scheduler + uvicorn
        raise NotImplementedError("TODO: implement serve mode")

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
