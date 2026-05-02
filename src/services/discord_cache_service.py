"""DiscordGuild, DiscordChannel の DB 操作。

Bot 側はギルド参加 / チャンネル変更などのイベントで upsert/delete を呼び、
Web 側は読み出して管理画面のセレクタに使う。
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DiscordChannel, DiscordEmoji, DiscordGuild

__all__ = [
    "delete_discord_channel",
    "delete_discord_channels_by_guild",
    "delete_discord_emojis_by_guild",
    "delete_discord_guild",
    "get_all_discord_emojis",
    "get_all_discord_guilds",
    "get_discord_channels_by_guild",
    "get_discord_emojis_by_guild",
    "upsert_discord_channel",
    "upsert_discord_emoji",
    "upsert_discord_guild",
]


# ---------------------------------------------------------------------------
# DiscordGuild
# ---------------------------------------------------------------------------


async def upsert_discord_guild(
    session: AsyncSession,
    guild_id: str,
    guild_name: str,
    icon_hash: str | None = None,
    member_count: int = 0,
) -> DiscordGuild:
    """ギルド情報を作成または更新する。"""
    result = await session.execute(
        select(DiscordGuild).where(DiscordGuild.guild_id == guild_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.guild_name = guild_name
        existing.icon_hash = icon_hash
        existing.member_count = member_count
        await session.commit()
        return existing

    guild = DiscordGuild(
        guild_id=guild_id,
        guild_name=guild_name,
        icon_hash=icon_hash,
        member_count=member_count,
    )
    session.add(guild)
    await session.commit()
    await session.refresh(guild)
    return guild


async def delete_discord_guild(session: AsyncSession, guild_id: str) -> bool:
    result = await session.execute(
        delete(DiscordGuild).where(DiscordGuild.guild_id == guild_id)
    )
    await session.commit()
    return int(result.rowcount or 0) > 0  # type: ignore[attr-defined]


async def get_all_discord_guilds(session: AsyncSession) -> list[DiscordGuild]:
    result = await session.execute(
        select(DiscordGuild).order_by(DiscordGuild.guild_name)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# DiscordChannel
# ---------------------------------------------------------------------------


async def upsert_discord_channel(
    session: AsyncSession,
    guild_id: str,
    channel_id: str,
    channel_name: str,
    channel_type: int = 0,
    position: int = 0,
    category_id: str | None = None,
) -> DiscordChannel:
    """チャンネル情報を作成または更新する。"""
    result = await session.execute(
        select(DiscordChannel).where(
            DiscordChannel.guild_id == guild_id,
            DiscordChannel.channel_id == channel_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.channel_name = channel_name
        existing.channel_type = channel_type
        existing.position = position
        existing.category_id = category_id
        await session.commit()
        return existing

    channel = DiscordChannel(
        guild_id=guild_id,
        channel_id=channel_id,
        channel_name=channel_name,
        channel_type=channel_type,
        position=position,
        category_id=category_id,
    )
    session.add(channel)
    await session.commit()
    await session.refresh(channel)
    return channel


async def delete_discord_channel(
    session: AsyncSession, guild_id: str, channel_id: str
) -> bool:
    result = await session.execute(
        delete(DiscordChannel).where(
            DiscordChannel.guild_id == guild_id,
            DiscordChannel.channel_id == channel_id,
        )
    )
    await session.commit()
    return int(result.rowcount or 0) > 0  # type: ignore[attr-defined]


async def delete_discord_channels_by_guild(session: AsyncSession, guild_id: str) -> int:
    result = await session.execute(
        delete(DiscordChannel).where(DiscordChannel.guild_id == guild_id)
    )
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def get_discord_channels_by_guild(
    session: AsyncSession, guild_id: str
) -> list[DiscordChannel]:
    result = await session.execute(
        select(DiscordChannel)
        .where(DiscordChannel.guild_id == guild_id)
        .order_by(DiscordChannel.position)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# DiscordEmoji
# ---------------------------------------------------------------------------


async def upsert_discord_emoji(
    session: AsyncSession,
    guild_id: str,
    emoji_id: str,
    name: str,
    animated: bool = False,
    available: bool = True,
) -> DiscordEmoji:
    """カスタム絵文字を作成または更新する。"""
    result = await session.execute(
        select(DiscordEmoji).where(
            DiscordEmoji.guild_id == guild_id,
            DiscordEmoji.emoji_id == emoji_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.name = name
        existing.animated = animated
        existing.available = available
        await session.commit()
        return existing

    emoji = DiscordEmoji(
        guild_id=guild_id,
        emoji_id=emoji_id,
        name=name,
        animated=animated,
        available=available,
    )
    session.add(emoji)
    await session.commit()
    await session.refresh(emoji)
    return emoji


async def delete_discord_emojis_by_guild(session: AsyncSession, guild_id: str) -> int:
    result = await session.execute(
        delete(DiscordEmoji).where(DiscordEmoji.guild_id == guild_id)
    )
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def get_discord_emojis_by_guild(
    session: AsyncSession, guild_id: str
) -> list[DiscordEmoji]:
    result = await session.execute(
        select(DiscordEmoji)
        .where(DiscordEmoji.guild_id == guild_id, DiscordEmoji.available.is_(True))
        .order_by(DiscordEmoji.name)
    )
    return list(result.scalars().all())


async def get_all_discord_emojis(session: AsyncSession) -> list[DiscordEmoji]:
    result = await session.execute(
        select(DiscordEmoji)
        .where(DiscordEmoji.available.is_(True))
        .order_by(DiscordEmoji.guild_id, DiscordEmoji.name)
    )
    return list(result.scalars().all())
