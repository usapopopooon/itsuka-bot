"""Message milestone cog."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import discord
from discord.ext import commands, tasks
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.engine import async_session
from src.database.models import MessageComboXpDelivery
from src.services.level_bot_client import award_message_combo_xp
from src.services.message_combo_xp_service import (
    MESSAGE_COMBO_XP_REWARDS,
    enqueue_message_combo_delivery,
    get_pending_message_combo_deliveries,
    mark_message_combo_notification_delivered,
    mark_message_combo_xp_delivered,
)
from src.services.message_milestone_service import (
    CONDITION_CONSECUTIVE_POSTS,
    MAX_MILESTONE_MESSAGE_LENGTH,
    MAX_MILESTONE_TEXT_LENGTH,
    BackfillMessage,
    ChannelMessageMilestone,
    MilestoneTemplateContext,
    backfill_message_milestone_messages,
    get_enabled_message_milestones,
    mark_message_milestone_consecutive_reward_sent,
    mark_message_milestone_reward_sent,
    record_consecutive_message_and_get_reward,
    record_message_and_get_reward,
    render_milestone_template,
)

logger = logging.getLogger(__name__)

_TRACKABLE_MESSAGE_TYPES: frozenset[discord.MessageType] = frozenset(
    {discord.MessageType.default, discord.MessageType.reply}
)
_EMBED_TITLE_LIMIT = 256
_CONFIG_MAX_AGE_SECONDS = 2.0
_CONTENT_PREVIEW_LIMIT = 80
_BACKFILL_HISTORY_LIMIT = 1000


@dataclass(frozen=True)
class _RenderedReward:
    content: str | None
    embed_title: str | None
    embed_description: str | None


def _preview_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.replace("\n", "\\n")
    if len(normalized) <= _CONTENT_PREVIEW_LIMIT:
        return normalized
    return f"{normalized[:_CONTENT_PREVIEW_LIMIT]}..."


class MessageMilestoneCog(commands.Cog):
    """投稿回数と継続日数に応じてチャンネルへメッセージを送信する Cog。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._configs: dict[str, list[ChannelMessageMilestone]] | None = None
        self._progress_lock = asyncio.Lock()
        self._refresh_lock = asyncio.Lock()
        self._combo_delivery_lock = asyncio.Lock()
        self._last_refresh_monotonic = 0.0
        self._delete_tasks: set[asyncio.Task[None]] = set()

    async def cog_load(self) -> None:
        await self.refresh()
        await self._backfill_pending_configs()
        await self.refresh()
        self._refresh_configs.start()
        self._retry_combo_deliveries.start()
        logger.info("MessageMilestone cog loaded, refresh loop started")

    async def cog_unload(self) -> None:
        if self._refresh_configs.is_running():
            self._refresh_configs.cancel()
        if self._retry_combo_deliveries.is_running():
            self._retry_combo_deliveries.cancel()
        for task in list(self._delete_tasks):
            task.cancel()

    async def refresh(self) -> None:
        async with async_session() as session:
            self._configs = await get_enabled_message_milestones(session)
        self._last_refresh_monotonic = time.monotonic()
        logger.info(
            "MessageMilestone: loaded %d enabled configs across %d channels",
            sum(len(records) for records in self._configs.values()),
            len(self._configs),
        )
        for channel_id, records in self._configs.items():
            logger.info(
                "MessageMilestone: channel %s enabled config ids=%s",
                channel_id,
                [config.id for config in records],
            )

    async def _backfill_pending_configs(self) -> None:
        if self._configs is None:
            return

        pending = [
            config
            for records in self._configs.values()
            for config in records
            if not config.backfill_completed
        ]
        if not pending:
            return

        logger.info(
            "MessageMilestone: starting history backfill for config ids=%s",
            [config.id for config in pending],
        )
        for config in pending:
            await self._backfill_config_history(config)

    async def _backfill_config_history(self, config: ChannelMessageMilestone) -> None:
        channel = self.bot.get_channel(int(config.channel_id))
        if channel is None or not hasattr(channel, "history"):
            logger.info(
                "MessageMilestone: skipped backfill for config=%s channel=%s "
                "because history is unavailable",
                config.id,
                config.channel_id,
            )
            return

        history: list[BackfillMessage] = []
        try:
            async for message in channel.history(limit=_BACKFILL_HISTORY_LIMIT):
                if not self._message_is_backfillable(message):
                    continue
                history.append(
                    BackfillMessage(
                        user_id=str(message.author.id),
                        message_id=str(message.id),
                        content=message.content,
                        created_at=message.created_at,
                    )
                )
        except discord.HTTPException:
            logger.exception(
                "MessageMilestone: failed to read history for backfill config=%s "
                "channel=%s",
                config.id,
                config.channel_id,
            )
            return

        history.reverse()
        async with self._progress_lock, async_session() as session:
            counted = await backfill_message_milestone_messages(
                session, config=config, messages=history
            )
        logger.info(
            "MessageMilestone: completed history backfill config=%s channel=%s "
            "scanned=%s counted=%s",
            config.id,
            config.channel_id,
            len(history),
            counted,
        )

    def _message_is_backfillable(self, message: discord.Message) -> bool:
        if not message.guild or not message.author:
            return False
        if message.author.bot:
            return False
        if message.webhook_id is not None:
            return False
        return message.type in _TRACKABLE_MESSAGE_TYPES

    async def _ensure_recent_configs(self) -> None:
        if (
            self._configs is not None
            and time.monotonic() - self._last_refresh_monotonic
            < _CONFIG_MAX_AGE_SECONDS
        ):
            return
        async with self._refresh_lock:
            if (
                self._configs is not None
                and time.monotonic() - self._last_refresh_monotonic
                < _CONFIG_MAX_AGE_SECONDS
            ):
                return
            logger.info("MessageMilestone: refreshing config cache before tracking")
            await self.refresh()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self._track(message)

    async def _track(self, message: discord.Message) -> None:
        if not message.guild or not message.author:
            logger.debug(
                "MessageMilestone: ignored message %s because guild/author is missing",
                getattr(message, "id", None),
            )
            return
        if message.author.bot:
            logger.debug(
                "MessageMilestone: ignored bot message %s author=%s",
                message.id,
                getattr(message.author, "id", None),
            )
            return
        if message.webhook_id is not None:
            logger.debug(
                "MessageMilestone: ignored webhook message %s webhook=%s",
                message.id,
                message.webhook_id,
            )
            return
        if message.type not in _TRACKABLE_MESSAGE_TYPES:
            logger.debug(
                "MessageMilestone: ignored message %s unsupported type=%s",
                message.id,
                message.type,
            )
            return
        await self._ensure_recent_configs()
        if self._configs is None:
            logger.info(
                "MessageMilestone: ignored message %s because config cache is empty",
                message.id,
            )
            return

        configs = self._configs_for_message(message)
        if not configs:
            logger.info(
                "MessageMilestone: no cached config for message=%s guild=%s "
                "channel_candidates=%s; refreshing once",
                message.id,
                message.guild.id,
                self._message_channel_ids(message),
            )
            # Web 保存直後の最初の投稿を取りこぼさないため、対象チャンネルが
            # キャッシュに無い場合だけ即時再読込する。
            await self.refresh()
            if self._configs is None:
                return
            configs = self._configs_for_message(message)
            if not configs:
                logger.info(
                    "MessageMilestone: no config after refresh for message=%s "
                    "guild=%s channel_candidates=%s",
                    message.id,
                    message.guild.id,
                    self._message_channel_ids(message),
                )
                return

        logger.info(
            "MessageMilestone: tracking message=%s guild=%s channel=%s "
            "channel_candidates=%s author=%s content_len=%s content_preview=%r "
            "config_ids=%s",
            message.id,
            message.guild.id,
            message.channel.id,
            self._message_channel_ids(message),
            message.author.id,
            len(message.content),
            _preview_text(message.content),
            [config.id for config in configs],
        )

        combo_delivery_enqueued = False
        async with self._progress_lock, async_session() as session:
            for config in configs:
                if config.pattern is not None and not config.pattern.search(
                    message.content
                ):
                    logger.info(
                        "MessageMilestone: message=%s did not match config=%s "
                        "pattern=%r content_len=%d content_preview=%r",
                        message.id,
                        config.id,
                        config.pattern.pattern,
                        len(message.content),
                        _preview_text(message.content),
                    )
                    if not message.content:
                        logger.info(
                            "MessageMilestone: message=%s content is empty; if a "
                            "pattern is set, enable Message Content Intent in the "
                            "Discord Developer Portal and restart the bot",
                            message.id,
                        )
                    continue
                logger.info(
                    "MessageMilestone: message=%s matched config=%s pattern=%r",
                    message.id,
                    config.id,
                    config.pattern.pattern if config.pattern else None,
                )
                try:
                    if config.condition_type == CONDITION_CONSECUTIVE_POSTS:
                        result = await record_consecutive_message_and_get_reward(
                            session,
                            config=config,
                            user_id=str(message.author.id),
                            created_at=message.created_at,
                            message_id=str(message.id),
                        )
                    else:
                        result = await record_message_and_get_reward(
                            session,
                            config=config,
                            user_id=str(message.author.id),
                            created_at=message.created_at,
                            message_id=str(message.id),
                        )
                except Exception:
                    logger.exception(
                        "MessageMilestone: failed to record progress for config %s",
                        config.id,
                    )
                    continue
                logger.info(
                    "MessageMilestone: progress config=%s user=%s message=%s "
                    "condition=%s daily=%s/%s streak=%s/%s consecutive=%s/%s "
                    "crossed_daily_goal=%s "
                    "reward_pending=%s duplicate=%s limited=%s reset_reason=%s "
                    "should_send=%s",
                    config.id,
                    message.author.id,
                    message.id,
                    config.condition_type,
                    result.daily_count,
                    config.daily_required_count,
                    result.streak_days,
                    config.required_days,
                    result.consecutive_count,
                    config.daily_required_count,
                    result.crossed_daily_goal,
                    result.reward_pending,
                    result.duplicate,
                    result.notification_limited,
                    result.reset_reason,
                    result.should_send,
                )
                if result.duplicate:
                    logger.info(
                        "MessageMilestone: message=%s config=%s already processed; "
                        "skipping duplicate count",
                        message.id,
                        config.id,
                    )
                if (
                    settings.level_bot_api_url
                    and settings.level_bot_api_token
                    and config.condition_type != CONDITION_CONSECUTIVE_POSTS
                    and result.crossed_daily_goal
                ):
                    delivery = await enqueue_message_combo_delivery(
                        session,
                        config_id=config.id,
                        guild_id=str(message.guild.id),
                        channel_id=str(message.channel.id),
                        user_id=str(message.author.id),
                        message_id=str(message.id),
                        streak_days=result.streak_days,
                        observed_at=message.created_at,
                    )
                    combo_delivery_enqueued |= delivery is not None
                if result.should_send:
                    logger.info(
                        "MessageMilestone: sending reward config=%s user=%s "
                        "channel=%s response_type=%s delete_after=%s",
                        config.id,
                        message.author.id,
                        message.channel.id,
                        config.response_type,
                        config.delete_after_seconds,
                    )
                    current_count = (
                        result.consecutive_count
                        if config.condition_type == CONDITION_CONSECUTIVE_POSTS
                        else result.streak_days
                    )
                    sent = await self._send_reward(
                        message.channel,
                        config,
                        message.author,
                        current_count=current_count,
                    )
                    if sent:
                        if config.condition_type != CONDITION_CONSECUTIVE_POSTS:
                            await mark_message_milestone_reward_sent(
                                session,
                                config_id=config.id,
                                user_id=str(message.author.id),
                            )
                        else:
                            await mark_message_milestone_consecutive_reward_sent(
                                session,
                                config_id=config.id,
                                user_id=str(message.author.id),
                                created_at=message.created_at,
                            )
                        logger.info(
                            "MessageMilestone: marked reward sent config=%s user=%s",
                            config.id,
                            message.author.id,
                        )
                    else:
                        logger.info(
                            "MessageMilestone: reward send failed config=%s user=%s; "
                            "will retry on the next counted message",
                            config.id,
                            message.author.id,
                        )

        if combo_delivery_enqueued:
            await self._deliver_pending_combo_deliveries()

    async def _deliver_pending_combo_deliveries(self) -> None:
        if not settings.level_bot_api_url or not settings.level_bot_api_token:
            return
        async with self._combo_delivery_lock, async_session() as session:
            deliveries = await get_pending_message_combo_deliveries(session)
            for delivery in deliveries:
                await self._deliver_combo_delivery(session, delivery)

    async def _deliver_combo_delivery(
        self,
        session: AsyncSession,
        delivery: MessageComboXpDelivery,
    ) -> None:
        if delivery.xp_delivered_at is None:
            try:
                award = await award_message_combo_xp(
                    api_url=settings.level_bot_api_url,
                    api_token=settings.level_bot_api_token,
                    event_id=delivery.event_id,
                    guild_id=delivery.guild_id,
                    channel_id=delivery.channel_id,
                    user_id=delivery.user_id,
                    config_id=delivery.config_id,
                    streak_days=delivery.streak_days,
                    observed_at=delivery.observed_at,
                )
                expected_xp = MESSAGE_COMBO_XP_REWARDS[delivery.streak_days]
                if (
                    award.event_id != delivery.event_id
                    or award.streak_days != delivery.streak_days
                    or award.awarded_xp != expected_xp
                ):
                    raise RuntimeError("level-bot returned an inconsistent combo award")
                await mark_message_combo_xp_delivered(session, delivery)
            except Exception:
                logger.exception(
                    "MessageComboXP: XP delivery failed event=%s; will retry",
                    delivery.event_id,
                )
                return

        if delivery.notification_delivered_at is not None:
            return
        channel = self.bot.get_channel(int(delivery.channel_id))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(delivery.channel_id))
            except discord.HTTPException:
                logger.exception(
                    "MessageComboXP: channel fetch failed event=%s; will retry",
                    delivery.event_id,
                )
                return
        if not isinstance(channel, discord.abc.Messageable):
            logger.error(
                "MessageComboXP: channel is not messageable event=%s channel=%s",
                delivery.event_id,
                delivery.channel_id,
            )
            return
        embed = self._build_combo_embed(delivery)
        try:
            await channel.send(content=f"<@{delivery.user_id}>", embed=embed)
        except discord.HTTPException:
            logger.exception(
                "MessageComboXP: notification failed event=%s; will retry",
                delivery.event_id,
            )
            return
        await mark_message_combo_notification_delivered(session, delivery)

    @staticmethod
    def _build_combo_embed(delivery: MessageComboXpDelivery) -> discord.Embed:
        if delivery.streak_days == 1:
            embed = discord.Embed(
                title="🔥 投稿コンボ開始！",
                description=(
                    "毎日1回以上投稿すると、2日・3日・5日・10日・20日コンボで"
                    "サーバーXPボーナスを獲得できます！"
                ),
                color=discord.Color.orange(),
            )
        else:
            xp = MESSAGE_COMBO_XP_REWARDS[delivery.streak_days]
            embed = discord.Embed(
                title=f"🎉 {delivery.streak_days}日コンボ達成！",
                description=(
                    f"投稿コンボを達成したので、サーバーでの {xp} XPを獲得しました！"
                ),
                color=discord.Color.gold(),
            )
        embed.set_footer(text=f"投稿コンボ • {delivery.event_id}")
        return embed

    async def _send_reward(
        self,
        channel: discord.abc.Messageable,
        config: ChannelMessageMilestone,
        author: discord.Member | discord.User,
        *,
        current_count: int | None = None,
    ) -> bool:
        try:
            rendered = self._render_reward(config, author, current_count=current_count)
            if not self._rendered_reward_is_sendable(config, rendered):
                logger.info(
                    "MessageMilestone: rendered reward too long for config %s "
                    "content_len=%s title_len=%s description_len=%s",
                    config.id,
                    len(rendered.content or ""),
                    len(rendered.embed_title or ""),
                    len(rendered.embed_description or ""),
                )
                return False
            if config.response_type == "embed":
                embed = self._build_embed(config, rendered, config.delete_after_seconds)
                try:
                    sent = await channel.send(content=rendered.content, embed=embed)
                except discord.Forbidden as exc:
                    logger.info(
                        "MessageMilestone: failed to send embed reward for config %s "
                        "because Discord rejected it; check the bot's Send Messages "
                        "and Embed Links permissions. Falling back to plain "
                        "message: %s",
                        config.id,
                        exc,
                    )
                    fallback = self._embed_fallback_content(rendered)
                    if len(fallback) > MAX_MILESTONE_MESSAGE_LENGTH:
                        logger.info(
                            "MessageMilestone: embed fallback too long for config %s "
                            "fallback_len=%s",
                            config.id,
                            len(fallback),
                        )
                        return False
                    sent = await channel.send(
                        self._with_countdown_content(
                            fallback, config.delete_after_seconds
                        )
                    )
                    self._schedule_delete_countdown(
                        sent,
                        config,
                        _RenderedReward(
                            content=fallback,
                            embed_title=None,
                            embed_description=None,
                        ),
                        force_plain=True,
                    )
                    logger.info(
                        "MessageMilestone: sent plain fallback for embed config %s "
                        "message=%s",
                        config.id,
                        sent.id,
                    )
                    return True
                self._schedule_delete_countdown(sent, config, rendered)
                logger.info(
                    "MessageMilestone: sent embed reward for config %s message=%s",
                    config.id,
                    sent.id,
                )
                return True
            sent = await channel.send(
                self._with_countdown_content(
                    rendered.content or "", config.delete_after_seconds
                )
            )
            self._schedule_delete_countdown(sent, config, rendered)
            logger.info(
                "MessageMilestone: sent plain reward for config %s message=%s",
                config.id,
                sent.id,
            )
            return True
        except discord.HTTPException as exc:
            logger.info(
                "MessageMilestone: failed to send reward for config %s: %s",
                config.id,
                exc,
            )
            return False

    def _embed_fallback_content(self, rendered: _RenderedReward) -> str:
        parts = [
            part
            for part in (
                rendered.content,
                rendered.embed_title,
                rendered.embed_description,
            )
            if part
        ]
        return "\n".join(parts) or "達成しました"

    def _message_channel_ids(self, message: discord.Message) -> list[str]:
        """設定照合に使う channel id 候補を返す。

        フォーラム投稿やスレッド内投稿は ``message.channel.id`` がスレッドIDに
        なる。Web 管理画面では親のテキスト/フォーラムチャンネルを選ぶため、
        ``parent_id`` も候補に含める。
        """
        ids = [str(message.channel.id)]
        parent_id = getattr(message.channel, "parent_id", None)
        if isinstance(parent_id, int):
            parent = str(parent_id)
            if parent not in ids:
                ids.append(parent)
        return ids

    def _configs_for_message(
        self, message: discord.Message
    ) -> list[ChannelMessageMilestone]:
        if self._configs is None:
            return []
        configs: list[ChannelMessageMilestone] = []
        seen: set[int] = set()
        for channel_id in self._message_channel_ids(message):
            for config in self._configs.get(channel_id, []):
                if config.id in seen:
                    continue
                configs.append(config)
                seen.add(config.id)
        return configs

    def _schedule_delete_countdown(
        self,
        message: discord.Message,
        config: ChannelMessageMilestone,
        rendered: _RenderedReward,
        *,
        force_plain: bool = False,
    ) -> None:
        if config.delete_after_seconds is None:
            return
        logger.info(
            "MessageMilestone: scheduled countdown delete message=%s config=%s "
            "seconds=%s",
            message.id,
            config.id,
            config.delete_after_seconds,
        )
        task = asyncio.create_task(
            self._delete_with_countdown(
                message, config, rendered, force_plain=force_plain
            )
        )
        self._delete_tasks.add(task)
        task.add_done_callback(self._delete_tasks.discard)

    async def _delete_with_countdown(
        self,
        message: discord.Message,
        config: ChannelMessageMilestone,
        rendered: _RenderedReward,
        *,
        force_plain: bool = False,
    ) -> None:
        if config.delete_after_seconds is None:
            return
        try:
            remaining = config.delete_after_seconds
            while remaining > 1:
                step = self._countdown_step_seconds(remaining)
                await asyncio.sleep(step)
                remaining = max(remaining - step, 1)
                if config.response_type == "embed" and not force_plain:
                    await message.edit(
                        content=rendered.content,
                        embed=self._build_embed(config, rendered, remaining),
                    )
                else:
                    await message.edit(
                        content=self._with_countdown_content(
                            rendered.content or "", remaining
                        )
                    )
            await asyncio.sleep(1)
            await message.delete()
            logger.info(
                "MessageMilestone: deleted countdown message=%s config=%s",
                message.id,
                config.id,
            )
        except asyncio.CancelledError:
            raise
        except discord.HTTPException:
            logger.info(
                "MessageMilestone: countdown/delete failed for config %s", config.id
            )

    def _build_embed(
        self,
        config: ChannelMessageMilestone,
        rendered: _RenderedReward,
        remaining: int | None = None,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=rendered.embed_title,
            description=rendered.embed_description,
            color=config.embed_color,
        )
        if remaining is not None:
            embed.set_footer(text=f"削除まで: {remaining}秒")
        return embed

    def _with_countdown_content(self, content: str, remaining: int | None) -> str:
        if remaining is None:
            return content
        return f"{content}\n\n削除まで: {remaining}秒".strip()

    def _countdown_step_seconds(self, remaining: int) -> int:
        return 1

    def _render_reward(
        self,
        config: ChannelMessageMilestone,
        author: discord.Member | discord.User,
        *,
        current_count: int | None = None,
    ) -> _RenderedReward:
        username = (
            getattr(author, "display_name", None)
            or getattr(author, "global_name", None)
            or author.name
        )
        context = MilestoneTemplateContext(
            username=username,
            daily_required_count=config.daily_required_count,
            current_count=current_count,
        )
        return _RenderedReward(
            content=render_milestone_template(config.message_content, context),
            embed_title=render_milestone_template(config.embed_title, context),
            embed_description=render_milestone_template(
                config.embed_description, context
            ),
        )

    def _rendered_reward_is_sendable(
        self, config: ChannelMessageMilestone, rendered: _RenderedReward
    ) -> bool:
        countdown_room = 40 if config.delete_after_seconds is not None else 0
        if config.response_type == "plain":
            return len(rendered.content or "") <= (
                MAX_MILESTONE_MESSAGE_LENGTH - countdown_room
            )
        if rendered.content and len(rendered.content) > MAX_MILESTONE_MESSAGE_LENGTH:
            return False
        if rendered.embed_title and len(rendered.embed_title) > _EMBED_TITLE_LIMIT:
            return False
        return not (
            rendered.embed_description
            and len(rendered.embed_description) > MAX_MILESTONE_TEXT_LENGTH
        )

    @tasks.loop(minutes=1)
    async def _refresh_configs(self) -> None:
        try:
            await self.refresh()
        except Exception:
            logger.exception("MessageMilestone: cache refresh failed")

    @_refresh_configs.before_loop
    async def _before_refresh_configs(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def _retry_combo_deliveries(self) -> None:
        try:
            await self._deliver_pending_combo_deliveries()
        except Exception:
            logger.exception("MessageComboXP: pending delivery loop failed")

    @_retry_combo_deliveries.before_loop
    async def _before_retry_combo_deliveries(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MessageMilestoneCog(bot))
