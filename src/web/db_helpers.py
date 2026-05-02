"""Web ルートから使う DB ヘルパー。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.engine import async_session
from src.database.models import DiscordChannel, DiscordGuild


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依存: AsyncSession を生成する。"""
    async with async_session() as session:
        yield session


async def _get_discord_guilds_and_channels(
    db: AsyncSession,
) -> tuple[dict[str, str], dict[str, list[tuple[str, str]]]]:
    """キャッシュ済みの guild_id→guild_name と guild_id→[(channel_id, name)]."""
    guilds_result = await db.execute(
        select(DiscordGuild).order_by(DiscordGuild.guild_name)
    )
    guilds_map: dict[str, str] = {
        g.guild_id: g.guild_name for g in guilds_result.scalars()
    }

    channels_result = await db.execute(
        select(DiscordChannel)
        # カテゴリ (4) は対象外。テキスト系のみを返す。
        .where(DiscordChannel.channel_type.in_((0, 5, 15)))
        .order_by(DiscordChannel.guild_id, DiscordChannel.position)
    )
    channels_map: dict[str, list[tuple[str, str]]] = {}
    for channel in channels_result.scalars():
        channels_map.setdefault(channel.guild_id, []).append(
            (channel.channel_id, channel.channel_name)
        )

    return guilds_map, channels_map
