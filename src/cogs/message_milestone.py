"""Message milestone cog."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import discord
from discord.ext import commands, tasks

from src.database.engine import async_session
from src.services.message_milestone_service import (
    MAX_MILESTONE_MESSAGE_LENGTH,
    MAX_MILESTONE_TEXT_LENGTH,
    ChannelMessageMilestone,
    MilestoneTemplateContext,
    get_enabled_message_milestones,
    mark_message_milestone_backfill_completed,
    mark_message_milestone_reward_sent,
    message_milestone_date,
    record_message_and_get_reward,
    render_milestone_template,
)

logger = logging.getLogger(__name__)

_TRACKABLE_MESSAGE_TYPES: frozenset[discord.MessageType] = frozenset(
    {discord.MessageType.default, discord.MessageType.reply}
)
_EMBED_TITLE_LIMIT = 256
_CONFIG_MAX_AGE_SECONDS = 2.0
_BACKFILL_HISTORY_LIMIT = 200
_CONTENT_PREVIEW_LIMIT = 80


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
        self._last_refresh_monotonic = 0.0
        self._is_backfilling = False
        self._delete_tasks: set[asyncio.Task[None]] = set()

    async def cog_load(self) -> None:
        await self.refresh()
        self._refresh_configs.start()
        logger.info("MessageMilestone cog loaded, refresh loop started")

    async def cog_unload(self) -> None:
        if self._refresh_configs.is_running():
            self._refresh_configs.cancel()
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
        if not self._is_backfilling:
            await self._backfill_pending_configs()

    async def _backfill_pending_configs(self) -> None:
        if self._configs is None:
            return
        pending = [
            config
            for records in self._configs.values()
            for config in records
            if not config.backfill_completed
        ]
        if pending:
            logger.info(
                "MessageMilestone: %d configs need backfill: ids=%s",
                len(pending),
                [config.id for config in pending],
            )
        self._is_backfilling = True
        try:
            for config in pending:
                await self._backfill_config(config)
        finally:
            self._is_backfilling = False

    async def _backfill_config(self, config: ChannelMessageMilestone) -> None:
        logger.info(
            "MessageMilestone: starting backfill config=%s channel=%s required=%s/day "
            "days=%s pattern=%r",
            config.id,
            config.channel_id,
            config.daily_required_count,
            config.required_days,
            config.pattern.pattern if config.pattern else None,
        )
        channel = self.bot.get_channel(int(config.channel_id))
        if channel is None:
            logger.info(
                "MessageMilestone: cannot backfill config %s; channel %s not cached",
                config.id,
                config.channel_id,
            )
            return
        try:
            sources = await self._backfill_sources(channel)
        except discord.HTTPException as exc:
            logger.info(
                "MessageMilestone: failed to list backfill sources for config %s: %s",
                config.id,
                exc,
            )
            return
        if not sources:
            logger.info(
                "MessageMilestone: cannot backfill config %s; "
                "channel %s has no readable history",
                config.id,
                config.channel_id,
            )
            return
        processed = 0
        try:
            remaining = _BACKFILL_HISTORY_LIMIT
            for source in sources:
                logger.info(
                    "MessageMilestone: reading backfill source config=%s source=%s "
                    "remaining_limit=%s",
                    config.id,
                    getattr(source, "id", type(source).__name__),
                    remaining,
                )
                if remaining <= 0:
                    break
                async for message in source.history(limit=remaining):
                    if self._message_is_before_today(message):
                        break
                    await self._track(message)
                    processed += 1
                    remaining -= 1
                    if remaining <= 0:
                        break
        except discord.HTTPException as exc:
            logger.info(
                "MessageMilestone: failed to backfill config %s: %s", config.id, exc
            )
            return
        async with async_session() as session:
            await mark_message_milestone_backfill_completed(
                session, config_id=config.id
            )
        logger.info(
            "MessageMilestone: backfilled config %s with %d recent messages",
            config.id,
            processed,
        )

    def _message_is_before_today(self, message: discord.Message) -> bool:
        return message_milestone_date(message.created_at) < message_milestone_date(None)

    async def _backfill_sources(self, channel: object) -> list[discord.abc.Messageable]:
        sources: list[discord.abc.Messageable] = []
        if isinstance(channel, discord.abc.Messageable):
            sources.append(channel)

        threads = getattr(channel, "threads", None)
        if threads:
            sources.extend(
                thread
                for thread in threads
                if isinstance(thread, discord.abc.Messageable)
            )

        archived_threads = getattr(channel, "archived_threads", None)
        if callable(archived_threads):
            async for thread in archived_threads(limit=_BACKFILL_HISTORY_LIMIT):
                if isinstance(thread, discord.abc.Messageable):
                    sources.append(thread)

        return sources

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
        if not self._is_backfilling:
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
            "config_ids=%s backfill=%s",
            message.id,
            message.guild.id,
            message.channel.id,
            self._message_channel_ids(message),
            message.author.id,
            len(message.content),
            _preview_text(message.content),
            [config.id for config in configs],
            self._is_backfilling,
        )

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
                    "daily=%s/%s streak=%s/%s crossed_daily_goal=%s "
                    "reward_pending=%s duplicate=%s should_send=%s",
                    config.id,
                    message.author.id,
                    message.id,
                    result.daily_count,
                    config.daily_required_count,
                    result.streak_days,
                    config.required_days,
                    result.crossed_daily_goal,
                    result.reward_pending,
                    result.duplicate,
                    result.should_send,
                )
                if result.duplicate:
                    logger.info(
                        "MessageMilestone: message=%s config=%s already processed; "
                        "skipping duplicate count",
                        message.id,
                        config.id,
                    )
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
                    sent = await self._send_reward(
                        message.channel, config, message.author
                    )
                    if sent:
                        await mark_message_milestone_reward_sent(
                            session,
                            config_id=config.id,
                            user_id=str(message.author.id),
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

    async def _send_reward(
        self,
        channel: discord.abc.Messageable,
        config: ChannelMessageMilestone,
        author: discord.Member | discord.User,
    ) -> bool:
        try:
            rendered = self._render_reward(config, author)
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
                sent = await channel.send(content=rendered.content, embed=embed)
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
            self._delete_with_countdown(message, config, rendered)
        )
        self._delete_tasks.add(task)
        task.add_done_callback(self._delete_tasks.discard)

    async def _delete_with_countdown(
        self,
        message: discord.Message,
        config: ChannelMessageMilestone,
        rendered: _RenderedReward,
    ) -> None:
        if config.delete_after_seconds is None:
            return
        try:
            remaining = config.delete_after_seconds
            while remaining > 1:
                step = self._countdown_step_seconds(remaining)
                await asyncio.sleep(step)
                remaining = max(remaining - step, 1)
                if config.response_type == "embed":
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
        if remaining <= 10:
            return 1
        if remaining <= 60:
            return 5
        return 15

    def _render_reward(
        self,
        config: ChannelMessageMilestone,
        author: discord.Member | discord.User,
    ) -> _RenderedReward:
        username = (
            getattr(author, "display_name", None)
            or getattr(author, "global_name", None)
            or author.name
        )
        context = MilestoneTemplateContext(
            username=username,
            daily_required_count=config.daily_required_count,
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MessageMilestoneCog(bot))
