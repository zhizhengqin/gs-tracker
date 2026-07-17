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
    logger.info("Pipeline wiring placeholder")


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
