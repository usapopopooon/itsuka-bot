"""エントリーポイント。

`python -m src.main` で起動する。テーブル初期化 → シグナルハンドラ登録 →
Bot 起動の順で実行する。

Discord 側の障害 (login の 429 や 5xx、一時的な接続エラー) でプロセスが
落ちないよう、`bot.start()` を指数バックオフで再試行する。Railway の
`restartPolicyMaxRetries` に頼ると Discord の長時間障害で枯渇するため、
プロセス内で持ちこたえる方針。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys

import discord

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

_INITIAL_BACKOFF_SECONDS = 30.0
_MAX_BACKOFF_SECONDS = 600.0


async def main() -> None:
    require_bot_settings()
    await init_db()
    logger.info("Database initialized")

    loop = asyncio.get_running_loop()
    shutdown = asyncio.Event()

    def _request_shutdown(sig_name: str) -> None:
        if not shutdown.is_set():
            logger.info("Received %s, shutting down...", sig_name)
            shutdown.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_shutdown, sig.name)
        except (NotImplementedError, RuntimeError) as e:
            logger.warning("Could not register %s handler: %s", sig.name, e)

    delay = _INITIAL_BACKOFF_SECONDS
    while not shutdown.is_set():
        bot = ItsukaBot()
        try:
            await _run_bot(bot, shutdown)
        except discord.LoginFailure:
            logger.exception("Discord login failed (invalid token?); aborting")
            raise
        except Exception as exc:
            if shutdown.is_set():
                return
            status = getattr(exc, "status", None)
            if status in (401, 403):
                # 認証系エラーはリトライしても無駄。設定見直しが必要。
                raise
            logger.warning(
                "Discord connection error (%s: %s); reconnecting in %.0fs",
                type(exc).__name__,
                exc,
                delay,
            )
            if await _wait_or_shutdown(shutdown, delay):
                return
            delay = min(delay * 2, _MAX_BACKOFF_SECONDS)
            continue
        # bot.start() が例外なしでリターン = close() 経由の正常終了
        return


async def _run_bot(bot: ItsukaBot, shutdown: asyncio.Event) -> None:
    """bot.start() を実行する。shutdown が set されたら bot.close() で抜ける。"""

    async def _close_on_shutdown() -> None:
        await shutdown.wait()
        if not bot.is_closed():
            await bot.close()

    closer = asyncio.create_task(_close_on_shutdown())
    try:
        async with bot:
            await bot.start(settings.discord_token)
    finally:
        closer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await closer


async def _wait_or_shutdown(shutdown: asyncio.Event, delay: float) -> bool:
    """delay 秒待つ。途中で shutdown が来たら True を返す。"""
    try:
        await asyncio.wait_for(shutdown.wait(), timeout=delay)
        return True
    except TimeoutError:
        return False


def run() -> None:
    """同期エントリーポイント (pyproject の console_scripts 用)。"""
    asyncio.run(main())


if __name__ == "__main__":
    run()
