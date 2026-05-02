"""Auto Reaction cog.

設定済みチャンネルへの新規メッセージへ、登録済みの絵文字を自動でリアクション
として付与する。以下は対象外:

- Bot 自身および他の Bot の発言 (``author.bot``)
- Webhook 経由の投稿 (GitHub / Zapier 等; ``message.webhook_id``)
- システムメッセージ (参加通知・ピン通知等; ``MessageType.default`` /
  ``MessageType.reply`` 以外)

ホットパス最適化: on_message は per-message に呼ばれるため DB アクセス・
JSON デコード・絵文字パースを全て事前計算してキャッシュする。
キャッシュは 1 分ごと、または明示的な refresh 呼び出しで更新する。
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from src.database.engine import async_session
from src.services.auto_reaction_service import get_enabled_auto_reaction_emoji_map

logger = logging.getLogger(__name__)


def _parse_emojis(raws: list[str]) -> list[discord.PartialEmoji]:
    return [discord.PartialEmoji.from_str(r) for r in raws]


# 通常投稿と返信のみリアクション対象とする。スラッシュコマンドの応答や
# 参加通知・ピン通知等のシステムメッセージは弾く。
_REACTABLE_MESSAGE_TYPES: frozenset[discord.MessageType] = frozenset(
    {discord.MessageType.default, discord.MessageType.reply}
)


class AutoReactionCog(commands.Cog):
    """AutoReaction 機能を提供する Cog。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # channel_id → 事前パース済み PartialEmoji リスト。
        # None は「未初期化」を意味し on_message は何もしない。
        self._configs: dict[str, list[discord.PartialEmoji]] | None = None

    async def cog_load(self) -> None:
        await self.refresh()
        self._refresh_cache.start()
        logger.info("AutoReaction cog loaded, cache refresh loop started")

    async def cog_unload(self) -> None:
        if self._refresh_cache.is_running():
            self._refresh_cache.cancel()

    async def refresh(self) -> None:
        """キャッシュを即時更新する。スラッシュコマンドから呼び出す。"""
        async with async_session() as session:
            raw_map = await get_enabled_auto_reaction_emoji_map(session)
        self._configs = {cid: _parse_emojis(raws) for cid, raws in raw_map.items()}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or not message.author:
            return
        if message.author.bot:
            return
        if message.webhook_id is not None:
            return
        if message.type not in _REACTABLE_MESSAGE_TYPES:
            return
        if self._configs is None:
            return

        emojis = self._configs.get(str(message.channel.id))
        if not emojis:
            return

        for emoji in emojis:
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException:
                logger.warning(
                    "AutoReaction: Failed to add %r to message %s in channel %s",
                    emoji,
                    message.id,
                    message.channel.id,
                )

    @tasks.loop(minutes=1)
    async def _refresh_cache(self) -> None:
        try:
            await self.refresh()
        except Exception:
            logger.exception("AutoReaction: cache refresh failed")

    @_refresh_cache.before_loop
    async def _before_refresh_cache(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoReactionCog(bot))
