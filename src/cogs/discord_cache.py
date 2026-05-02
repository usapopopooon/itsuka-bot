"""Discord ギルド / チャンネル情報を DB にキャッシュする Cog。

Web 管理画面のサーバー / チャンネル選択肢に使う。
on_ready で全件同期し、以後は guild_join / guild_remove / channel_*** /
guild_update イベントで差分更新する。
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from src.database.engine import async_session
from src.services.discord_cache_service import (
    delete_discord_channel,
    delete_discord_channels_by_guild,
    delete_discord_guild,
    upsert_discord_channel,
    upsert_discord_guild,
)

logger = logging.getLogger(__name__)


SYNC_CHANNEL_TYPES: set[discord.ChannelType] = {
    discord.ChannelType.text,
    discord.ChannelType.voice,
    discord.ChannelType.category,
    discord.ChannelType.news,
    discord.ChannelType.forum,
}


class DiscordCacheCog(commands.Cog):
    """Discord 情報を DB に書き出す Cog。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ---- 同期ヘルパー -------------------------------------------------

    async def _sync_guild_info(self, guild: discord.Guild) -> None:
        async with async_session() as db_session:
            await upsert_discord_guild(
                db_session,
                guild_id=str(guild.id),
                guild_name=guild.name,
                icon_hash=guild.icon.key if guild.icon else None,
                member_count=guild.member_count or 0,
            )

    async def _sync_guild_channels(self, guild: discord.Guild) -> int:
        count = 0
        async with async_session() as db_session:
            for channel in guild.channels:
                if channel.type not in SYNC_CHANNEL_TYPES:
                    continue
                if not channel.permissions_for(guild.me).view_channel:
                    continue
                await upsert_discord_channel(
                    db_session,
                    guild_id=str(guild.id),
                    channel_id=str(channel.id),
                    channel_name=channel.name,
                    channel_type=channel.type.value,
                    position=channel.position,
                    category_id=(
                        str(channel.category_id) if channel.category_id else None
                    ),
                )
                count += 1
        return count

    # ---- イベント -----------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        total_channels = 0
        for guild in self.bot.guilds:
            await self._sync_guild_info(guild)
            total_channels += await self._sync_guild_channels(guild)
        logger.info(
            "Synced %d guilds, %d channels", len(self.bot.guilds), total_channels
        )

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self._sync_guild_info(guild)
        channel_count = await self._sync_guild_channels(guild)
        logger.info("Synced %d channels for new guild %s", channel_count, guild.name)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        async with async_session() as db_session:
            channel_count = await delete_discord_channels_by_guild(
                db_session, str(guild.id)
            )
            await delete_discord_guild(db_session, str(guild.id))
        logger.info(
            "Removed cache for guild %s (%d channels)", guild.name, channel_count
        )

    @commands.Cog.listener()
    async def on_guild_update(
        self, before: discord.Guild, after: discord.Guild
    ) -> None:
        if before.name != after.name or before.icon != after.icon:
            await self._sync_guild_info(after)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        if channel.type not in SYNC_CHANNEL_TYPES:
            return
        if not channel.permissions_for(channel.guild.me).view_channel:
            return
        async with async_session() as db_session:
            await upsert_discord_channel(
                db_session,
                guild_id=str(channel.guild.id),
                channel_id=str(channel.id),
                channel_name=channel.name,
                channel_type=channel.type.value,
                position=channel.position,
                category_id=(str(channel.category_id) if channel.category_id else None),
            )

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        _before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ) -> None:
        if after.type not in SYNC_CHANNEL_TYPES:
            return
        async with async_session() as db_session:
            await upsert_discord_channel(
                db_session,
                guild_id=str(after.guild.id),
                channel_id=str(after.id),
                channel_name=after.name,
                channel_type=after.type.value,
                position=after.position,
                category_id=(str(after.category_id) if after.category_id else None),
            )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        async with async_session() as db_session:
            await delete_discord_channel(
                db_session, str(channel.guild.id), str(channel.id)
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DiscordCacheCog(bot))
