"""エントリーポイント。

`python -m src.main` で起動する。テーブル初期化 → シグナルハンドラ登録 →
Bot 起動の順で実行する。
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from types import FrameType

from src.bot import ItsukaBot
from src.config import require_bot_settings, settings
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


_setup_logging()
logger = logging.getLogger(__name__)

_bot: ItsukaBot | None = None


def _handle_shutdown_signal(signum: int, _frame: FrameType | None) -> None:
    try:
        sig_name = signal.Signals(signum).name
    except ValueError:
        sig_name = str(signum)
    logger.info("Received %s, shutting down...", sig_name)
    if _bot is not None:
        try:
            asyncio.create_task(_bot.close())
        except RuntimeError:
            sys.exit(0)


async def main() -> None:
    global _bot

    require_bot_settings()
    await init_db()
    logger.info("Database initialized")

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handle_shutdown_signal)
        except (ValueError, OSError) as e:
            logger.warning("Could not register %s handler: %s", sig.name, e)

    _bot = ItsukaBot()
    async with _bot:
        await _bot.start(settings.discord_token)


def run() -> None:
    """同期エントリーポイント (pyproject の console_scripts 用)。"""
    asyncio.run(main())


if __name__ == "__main__":
    run()
