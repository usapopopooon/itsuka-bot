"""Bot 本体クラス。

主な設定は Web 管理画面 (src.web) から行う。Discord 側には管理者向けの
補助スラッシュコマンドを少数持ち、Cog 側は 1 分ごとに DB をポーリングして
キャッシュを更新する。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

_COMMAND_SYNC_RETRY_SECONDS = 60.0


class ItsukaBot(commands.Bot):
    """Itsuka Bot 本体。

    AutoReaction の正規表現フィルタと MessageMilestone の投稿検知が本文を
    参照するため、``message_content`` (privileged intent) を要求する。
    Discord Developer Portal の Bot 設定で "Message Content Intent" を
    ON にしておくこと。

    - ``guilds``: ギルド / チャンネル変更イベント
    - ``guild_messages``: ``on_message`` を発火させる
    - ``message_content``: 正規表現マッチ用にメッセージ本文を読む (privileged)
    """

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True

        # command_prefix はテキストコマンドを使わない本 Bot では実質未使用
        super().__init__(
            command_prefix="!",
            intents=intents,
            activity=discord.Game(name="投稿を見守り中"),
        )
        self._command_sync_retry_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        for ext in (
            "src.cogs.discord_cache",
            "src.cogs.auto_reaction",
            "src.cogs.message_milestone",
        ):
            await self.load_extension(ext)
            logger.info("Loaded extension: %s", ext)
        if not await self._sync_application_commands():
            self._start_command_sync_retry()

    async def close(self) -> None:
        if self._command_sync_retry_task is not None:
            self._command_sync_retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._command_sync_retry_task
            self._command_sync_retry_task = None
        await super().close()

    async def on_ready(self) -> None:
        if self.user:
            logger.info("Logged in as %s (ID: %d)", self.user, self.user.id)

    async def _sync_application_commands(self) -> bool:
        try:
            synced = await self.tree.sync()
        except discord.HTTPException as e:
            logger.exception("Failed to sync slash commands: %s", e)
            return False
        logger.info("Synced %d slash commands", len(synced))
        return True

    def _start_command_sync_retry(self) -> None:
        if self._command_sync_retry_task is not None:
            return
        self._command_sync_retry_task = asyncio.create_task(
            self._retry_application_command_sync()
        )

    async def _retry_application_command_sync(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(_COMMAND_SYNC_RETRY_SECONDS)
            if await self._sync_application_commands():
                self._command_sync_retry_task = None
                return
