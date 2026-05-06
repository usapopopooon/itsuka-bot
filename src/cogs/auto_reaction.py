"""Auto Reaction cog.

設定済みチャンネルへの新規メッセージへ、登録済みの絵文字を自動でリアクション
として付与する。以下は対象外:

- Bot 自身および他の Bot の発言 (``author.bot``)
- Webhook 経由の投稿 (GitHub / Zapier 等; ``message.webhook_id``)
- システムメッセージ (参加通知・ピン通知等; ``MessageType.default`` /
  ``MessageType.reply`` 以外)
- 設定に正規表現フィルタが指定されていて、本文がマッチしないもの

ホットパス最適化: on_message は per-message に呼ばれるため DB アクセス・
JSON デコード・絵文字パース・正規表現コンパイルを全て事前計算してキャッシュ
する。キャッシュは 1 分ごと、または明示的な refresh 呼び出しで更新する。
"""

from __future__ import annotations

import logging
import re

import discord
from discord.ext import commands, tasks

from src.database.engine import async_session
from src.services.auto_reaction_service import (
    ChannelAutoReaction,
    get_enabled_auto_reactions,
)

logger = logging.getLogger(__name__)


def _parse_emojis(raws: list[str]) -> list[discord.PartialEmoji]:
    return [discord.PartialEmoji.from_str(r) for r in raws]


# 通常投稿と返信のみリアクション対象とする。スラッシュコマンドの応答や
# 参加通知・ピン通知等のシステムメッセージは弾く。
_REACTABLE_MESSAGE_TYPES: frozenset[discord.MessageType] = frozenset(
    {discord.MessageType.default, discord.MessageType.reply}
)


class _CachedConfig:
    __slots__ = ("emojis", "pattern")

    def __init__(
        self, emojis: list[discord.PartialEmoji], pattern: re.Pattern[str] | None
    ) -> None:
        self.emojis = emojis
        self.pattern = pattern


class AutoReactionCog(commands.Cog):
    """AutoReaction 機能を提供する Cog。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # channel_id → 事前パース済み絵文字 + コンパイル済み正規表現の list。
        # 1 チャンネルに複数設定を持てるためリストで保持する。
        # None は「未初期化」を意味し on_message は何もしない。
        self._configs: dict[str, list[_CachedConfig]] | None = None

    async def cog_load(self) -> None:
        await self.refresh()
        self._refresh_cache.start()
        logger.info("AutoReaction cog loaded, cache refresh loop started")

    async def cog_unload(self) -> None:
        if self._refresh_cache.is_running():
            self._refresh_cache.cancel()

    async def refresh(self) -> None:
        """キャッシュを即時更新する。"""
        async with async_session() as session:
            raw_map: dict[
                str, list[ChannelAutoReaction]
            ] = await get_enabled_auto_reactions(session)
        self._configs = {
            cid: [
                _CachedConfig(
                    emojis=_parse_emojis(record.emojis), pattern=record.pattern
                )
                for record in records
            ]
            for cid, records in raw_map.items()
        }

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

        configs = self._configs.get(str(message.channel.id))
        if not configs:
            return

        # 同一チャンネルに複数設定がある場合、それぞれ独立に pattern を
        # 評価し、マッチした設定の絵文字を集約する。複数設定が同じ絵文字を
        # 含むケースに備えて重複を排除する (Discord は同じ絵文字を 2 回
        # 付けようとすると 4xx を返すため)。
        seen: set[str] = set()
        emojis_to_add: list[discord.PartialEmoji] = []
        for config in configs:
            if not config.emojis:
                continue
            if config.pattern is not None and not config.pattern.search(
                message.content
            ):
                continue
            for emoji in config.emojis:
                key = str(emoji)
                if key in seen:
                    continue
                seen.add(key)
                emojis_to_add.append(emoji)

        for emoji in emojis_to_add:
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException:
                # 権限不足や絵文字未参加など実運用で起こりうる失敗を warning で
                # 出していたが、頻発時にログを汚すので INFO へ落とす。
                logger.info(
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
