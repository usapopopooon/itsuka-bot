"""Message milestone cog."""

from __future__ import annotations

import asyncio
import logging
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
    mark_message_milestone_reward_sent,
    record_message_and_get_reward,
    render_milestone_template,
)

logger = logging.getLogger(__name__)

_TRACKABLE_MESSAGE_TYPES: frozenset[discord.MessageType] = frozenset(
    {discord.MessageType.default, discord.MessageType.reply}
)
_EMBED_TITLE_LIMIT = 256


@dataclass(frozen=True)
class _RenderedReward:
    content: str | None
    embed_title: str | None
    embed_description: str | None


class MessageMilestoneCog(commands.Cog):
    """投稿回数と継続日数に応じてチャンネルへメッセージを送信する Cog。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._configs: dict[str, list[ChannelMessageMilestone]] | None = None
        self._progress_lock = asyncio.Lock()
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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self._track(message)

    async def _track(self, message: discord.Message) -> None:
        if not message.guild or not message.author:
            return
        if message.author.bot:
            return
        if message.webhook_id is not None:
            return
        if message.type not in _TRACKABLE_MESSAGE_TYPES:
            return
        if self._configs is None:
            return

        configs = self._configs.get(str(message.channel.id))
        if not configs:
            return

        async with self._progress_lock, async_session() as session:
            for config in configs:
                if config.pattern is not None and not config.pattern.search(
                    message.content
                ):
                    continue
                try:
                    result = await record_message_and_get_reward(
                        session,
                        config=config,
                        user_id=str(message.author.id),
                        created_at=message.created_at,
                    )
                except Exception:
                    logger.exception(
                        "MessageMilestone: failed to record progress for config %s",
                        config.id,
                    )
                    continue
                if result.should_send:
                    sent = await self._send_reward(
                        message.channel, config, message.author
                    )
                    if sent:
                        await mark_message_milestone_reward_sent(
                            session,
                            config_id=config.id,
                            user_id=str(message.author.id),
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
                    "MessageMilestone: rendered reward too long for config %s",
                    config.id,
                )
                return False
            if config.response_type == "embed":
                embed = self._build_embed(config, rendered, config.delete_after_seconds)
                sent = await channel.send(content=rendered.content, embed=embed)
                self._schedule_delete_countdown(sent, config, rendered)
                return True
            sent = await channel.send(
                self._with_countdown_content(
                    rendered.content or "", config.delete_after_seconds
                )
            )
            self._schedule_delete_countdown(sent, config, rendered)
            return True
        except discord.HTTPException:
            logger.info(
                "MessageMilestone: failed to send reward for config %s", config.id
            )
            return False

    def _schedule_delete_countdown(
        self,
        message: discord.Message,
        config: ChannelMessageMilestone,
        rendered: _RenderedReward,
    ) -> None:
        if config.delete_after_seconds is None:
            return
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
