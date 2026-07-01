"""One-shot database migration entry point for Compose deployments."""

from __future__ import annotations

import asyncio
import logging
import sys

from src.config import settings
from src.database.engine import init_db


def _setup_logging() -> None:
    log_level = getattr(logging, settings.log_level, logging.INFO)
    if not isinstance(log_level, int):
        log_level = logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )


async def main() -> None:
    await init_db()
    logging.getLogger(__name__).info("Database migration completed")


def run() -> None:
    _setup_logging()
    asyncio.run(main())


if __name__ == "__main__":
    run()
