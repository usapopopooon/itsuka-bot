"""Auto Reaction cog.

設定済みチャンネルへの新規メッセージへ、登録済みの絵文字を自動でリアクション
として付与する。メッセージ編集時にも再評価し、新たにマッチした分は追加、
マッチしなくなった分は bot が付けたリアクションのみ削除する。以下は対象外:

- Bot 自身および他の Bot の発言 (``author.bot``)
- Webhook 経由の投稿 (GitHub / Zapier 等; ``message.webhook_id``)
- システムメッセージ (参加通知・ピン通知等; ``MessageType.default`` /
  ``MessageType.reply`` 以外)
- 設定の除外ユーザー ID に投稿者が含まれるもの
- 設定に正規表現フィルタが指定されていて、本文がマッチしないもの

ホットパス最適化: on_message は per-message に呼ばれるため DB アクセス・
JSON デコード・絵文字パース・正規表現コンパイルを全て事前計算してキャッシュ
する。キャッシュは 1 分ごと、または明示的な refresh 呼び出しで更新する。

セーフティネット: ``on_message`` を取りこぼすケース (Discord 障害復帰直後、
ゲートウェイ切断中の投稿、起動前の投稿等) に備え、キャッシュ更新と同じ周期
で各チャンネルの直近メッセージを ``_reconcile`` で再点検する。
"""

from __future__ import annotations

import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from src.database.engine import async_session
from src.database.models import AutoReactionConfig
from src.services.auto_reaction_service import (
    ChannelAutoReaction,
    decode_auto_reaction_user_ids,
    encode_auto_reaction_user_ids,
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

# 1 チャンネルあたり何件遡って再点検するか。多すぎても直近以外は実用上付ける
# 必要が無く、API コストが増えるだけなので 50 件に制限する。
_SWEEP_HISTORY_LIMIT = 50


def _interaction_is_admin(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction, "permissions", None)
    if permissions is not None:
        return bool(getattr(permissions, "administrator", False))
    guild_permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(getattr(guild_permissions, "administrator", False))


class _CachedConfig:
    __slots__ = ("emojis", "excluded_user_ids", "pattern")

    def __init__(
        self,
        emojis: list[discord.PartialEmoji],
        pattern: re.Pattern[str] | None,
        excluded_user_ids: frozenset[str] | None = None,
    ) -> None:
        self.emojis = emojis
        self.pattern = pattern
        self.excluded_user_ids = excluded_user_ids or frozenset()


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
        self._refresh_and_sweep.start()
        logger.info("AutoReaction cog loaded, refresh/sweep loop started")

    async def cog_unload(self) -> None:
        if self._refresh_and_sweep.is_running():
            self._refresh_and_sweep.cancel()

    async def refresh(self) -> None:
        """キャッシュを即時更新する。"""
        async with async_session() as session:
            raw_map: dict[
                str, list[ChannelAutoReaction]
            ] = await get_enabled_auto_reactions(session)
        self._configs = {
            cid: [
                _CachedConfig(
                    emojis=_parse_emojis(record.emojis),
                    pattern=record.pattern,
                    excluded_user_ids=record.excluded_user_ids,
                )
                for record in records
            ]
            for cid, records in raw_map.items()
        }

    @app_commands.command(
        name="auto-reaction-exclude",
        description="Auto Reaction の除外ユーザーを設定します",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.describe(
        config_id="管理画面に表示される設定ID",
        user="除外するサーバーメンバー。表示名で検索できます",
        clear="true にすると除外ユーザーを全解除します",
    )
    async def auto_reaction_exclude(
        self,
        interaction: discord.Interaction,
        config_id: int,
        user: discord.Member | None = None,
        clear: bool = False,
    ) -> None:
        """Slash command から除外ユーザーを設定する。"""
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ実行できます。",
                ephemeral=True,
            )
            return
        if not _interaction_is_admin(interaction):
            await interaction.response.send_message(
                "このコマンドは管理者のみ実行できます。",
                ephemeral=True,
            )
            return
        if config_id <= 0:
            await interaction.response.send_message(
                "設定IDは1以上の数値で指定してください。",
                ephemeral=True,
            )
            return

        if clear and user is not None:
            await interaction.response.send_message(
                "ユーザーを追加するか、全解除するかのどちらか一方だけ指定してください。",
                ephemeral=True,
            )
            return
        if not clear and user is None:
            await interaction.response.send_message(
                "除外するユーザーを選択するか、clear を true にしてください。",
                ephemeral=True,
            )
            return

        message: str
        changed = False
        async with async_session() as session:
            result = await session.execute(
                select(AutoReactionConfig).where(AutoReactionConfig.id == config_id)
            )
            config = result.scalar_one_or_none()
            if config is None or config.guild_id != str(interaction.guild_id):
                await interaction.response.send_message(
                    "指定された設定IDがこのサーバーに見つかりません。",
                    ephemeral=True,
                )
                return
            excluded_user_ids = decode_auto_reaction_user_ids(config.excluded_user_ids)
            if clear:
                if excluded_user_ids:
                    config.excluded_user_ids = encode_auto_reaction_user_ids([])
                    await session.commit()
                    changed = True
                message = f"設定ID {config_id} の除外ユーザーを全解除しました。"
            else:
                assert user is not None
                user_id = str(user.id)
                if user_id in excluded_user_ids:
                    message = (
                        f"{user.mention} はすでに設定ID {config_id} "
                        "の除外ユーザーです。"
                    )
                else:
                    excluded_user_ids.append(user_id)
                    config.excluded_user_ids = encode_auto_reaction_user_ids(
                        excluded_user_ids
                    )
                    await session.commit()
                    changed = True
                    message = (
                        f"{user.mention} を設定ID {config_id} "
                        "の除外ユーザーに追加しました。"
                    )

        if changed:
            await self.refresh()
        await interaction.response.send_message(message, ephemeral=True)

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
        author_id = str(message.author.id)
        for config in configs:
            if author_id in config.excluded_user_ids:
                continue
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

        bot_user = self.bot.user
        if bot_user is None:
            # ログイン前は user が None。on_message が来る前に ready するので
            # 通常は到達しないが、型上の None を消して remove_reaction を通す。
            return

        # サーバ側にはリアクションは正しく永続化されるが、Discord クライアントが
        # ゲートウェイの MESSAGE_REACTION_ADD/REMOVE を短時間に連続受信すると
        # 一部の描画を取りこぼし、リロードするまで自分にだけリアクションが見えない
        # 現象がある。送信間隔を空けてクライアントの描画キューに余裕を持たせる。
        # メッセージ連投時にも並行発射しないよう全体をロックで直列化する。
        async with self._reaction_lock:
            first = True
            for add_emoji in to_add:
                if not first:
                    await asyncio.sleep(0.5)
                first = False
                try:
                    await message.add_reaction(add_emoji)
                except discord.HTTPException:
                    # 権限不足や絵文字未参加など実運用で起こりうる失敗を warning
                    # で出していたが、頻発時にログを汚すので INFO へ落とす。
                    logger.info(
                        "AutoReaction: Failed to add %r to message %s in channel %s",
                        add_emoji,
                        message.id,
                        message.channel.id,
                    )
            for rm_emoji in to_remove:
                if not first:
                    await asyncio.sleep(0.5)
                first = False
                try:
                    await message.remove_reaction(rm_emoji, bot_user)
                except discord.HTTPException:
                    logger.info(
                        "AutoReaction: Failed to remove %r from message %s in %s",
                        rm_emoji,
                        message.id,
                        message.channel.id,
                    )

    async def sweep_recent_messages(self) -> None:
        """設定済みチャンネルの直近メッセージを再点検する。

        ``on_message`` を取りこぼすシナリオ (Discord 障害、ゲートウェイ
        瞬断、起動前の投稿等) に備えたセーフティネット。各チャンネルにつき
        ``_SWEEP_HISTORY_LIMIT`` 件分を ``_reconcile`` に通すだけで、新規
        分は付与・取りこぼしは補完される。既に整合済みのメッセージは
        ``_reconcile`` 内の早期 return で API を呼ばない。
        """
        if self._configs is None:
            return
        for channel_id in list(self._configs.keys()):
            try:
                channel_id_int = int(channel_id)
            except ValueError:
                continue
            channel = self.bot.get_channel(channel_id_int)
            if channel is None:
                # キャッシュに無い (削除済み / 未参加 / 部分キャッシュ) は
                # スキップ。次回 sweep で復帰する想定。
                continue
            if not isinstance(channel, discord.abc.Messageable):
                # CategoryChannel / ForumChannel など history() を持たない
                # ものは無視。
                continue
            try:
                async for message in channel.history(limit=_SWEEP_HISTORY_LIMIT):
                    await self._reconcile(message)
            except discord.HTTPException:
                logger.info(
                    "AutoReaction sweep: failed to read history for channel %s",
                    channel_id_int,
                )

    @tasks.loop(minutes=1)
    async def _refresh_and_sweep(self) -> None:
        try:
            await self.refresh()
        except Exception:
            logger.exception("AutoReaction: cache refresh failed")
        try:
            await self.sweep_recent_messages()
        except Exception:
            logger.exception("AutoReaction: sweep failed")

    @_refresh_and_sweep.before_loop
    async def _before_refresh_and_sweep(self) -> None:
        # 起動直後 / 再接続直後にも sweep を走らせるため ready を待つ。
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoReactionCog(bot))
