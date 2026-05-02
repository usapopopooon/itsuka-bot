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

    AutoReaction の正規表現フィルタが本文を参照するため、``message_content``
    (privileged intent) を要求する。Discord Developer Portal の Bot 設定で
    "Message Content Intent" を ON にしておくこと。

    - ``guilds``: ギルド / チャンネル変更イベント
    - ``guild_messages``: ``on_message`` を発火させる
    - ``message_content``: 正規表現マッチ用にメッセージ本文を読む (privileged)
    """

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True

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
