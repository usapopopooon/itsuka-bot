"""Auto Reaction cog.

設定済みチャンネルへの新規メッセージへ、登録済みの絵文字を自動でリアクション
として付与する。メッセージ編集時にも再評価し、新たにマッチした分は追加、
マッチしなくなった分は bot が付けたリアクションのみ削除する。以下は対象外:

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

import asyncio
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
        # メッセージ連投時、複数 on_message が並行して add_reaction を発射すると
        # クライアント描画が再び取りこぼすため、リアクション付与処理全体を
        # グローバルに直列化する。順番待ちで反応が遅れるのは許容。
        self._reaction_lock = asyncio.Lock()

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
        await self._reconcile(message)

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        # embed 展開・ピン状態変更などでも on_message_edit は飛ぶので、本文が
        # 変わっていない編集はスキップする。
        if before.content == after.content:
            return
        await self._reconcile(after)

    async def _reconcile(self, message: discord.Message) -> None:
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
        desired_by_key: dict[str, discord.PartialEmoji] = {}
        for config in configs:
            if not config.emojis:
                continue
            if config.pattern is not None and not config.pattern.search(
                message.content
            ):
                continue
            for emoji in config.emojis:
                key = str(emoji)
                if key in desired_by_key:
                    continue
                desired_by_key[key] = emoji

        # 既に bot が付けているリアクションを把握し、足りない分を追加・
        # マッチしなくなった分を削除する (編集で本文がパターン外れたケース)。
        # Reaction.emoji は str | Emoji | PartialEmoji で、いずれも str() で
        # PartialEmoji.from_str と同じ表記に正規化される。
        bot_current_by_key: dict[str, discord.PartialEmoji | discord.Emoji | str] = {
            str(r.emoji): r.emoji for r in message.reactions if r.me
        }

        to_add = [e for k, e in desired_by_key.items() if k not in bot_current_by_key]
        to_remove = [
            e for k, e in bot_current_by_key.items() if k not in desired_by_key
        ]

        if not to_add and not to_remove:
            return

        # サーバ側にはリアクションは正しく永続化されるが、Discord クライアントが
        # ゲートウェイの MESSAGE_REACTION_ADD/REMOVE を短時間に連続受信すると
        # 一部の描画を取りこぼし、リロードするまで自分にだけリアクションが見えない
        # 現象がある。送信間隔を空けてクライアントの描画キューに余裕を持たせる。
        # メッセージ連投時にも並行発射しないよう全体をロックで直列化する。
        async with self._reaction_lock:
            first = True
            for emoji in to_add:
                if not first:
                    await asyncio.sleep(0.5)
                first = False
                try:
                    await message.add_reaction(emoji)
                except discord.HTTPException:
                    # 権限不足や絵文字未参加など実運用で起こりうる失敗を warning
                    # で出していたが、頻発時にログを汚すので INFO へ落とす。
                    logger.info(
                        "AutoReaction: Failed to add %r to message %s in channel %s",
                        emoji,
                        message.id,
                        message.channel.id,
                    )
            for emoji in to_remove:
                if not first:
                    await asyncio.sleep(0.5)
                first = False
                try:
                    await message.remove_reaction(emoji, self.bot.user)
                except discord.HTTPException:
                    logger.info(
                        "AutoReaction: Failed to remove %r from message %s in %s",
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
