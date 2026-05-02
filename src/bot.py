"""Bot 本体クラス。

スラッシュコマンドは持たない。設定はすべて Web 管理画面 (src.web) から行い、
Cog 側は 1 分ごとに DB をポーリングしてキャッシュを更新する。
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


class ItsukaBot(commands.Bot):
    """Itsuka Bot 本体。

    Intents:
        - guilds: サーバー情報
        - guild_messages: チャンネルへの投稿イベント
        - message_content: メッセージ内容 (将来拡張用)
        - reactions: リアクション関連イベント
    """

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        intents.reactions = True

        # command_prefix はスラッシュコマンドを使わない本 Bot では実質未使用
        super().__init__(
            command_prefix="!",
            intents=intents,
            activity=discord.Game(name="リアクション係"),
        )

    async def setup_hook(self) -> None:
        for ext in ("src.cogs.discord_cache", "src.cogs.auto_reaction"):
            await self.load_extension(ext)
            logger.info("Loaded extension: %s", ext)

    async def on_ready(self) -> None:
        if self.user:
            logger.info("Logged in as %s (ID: %d)", self.user, self.user.id)
