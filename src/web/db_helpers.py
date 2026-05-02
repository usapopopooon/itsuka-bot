"""Web ルートから使う DB ヘルパー。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.engine import async_session
from src.database.models import DiscordChannel, DiscordEmoji, DiscordGuild


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


async def _get_discord_emojis_by_guild(
    db: AsyncSession,
) -> dict[str, list[dict[str, object]]]:
    """guild_id → [{id, name, animated, format}] の辞書。

    ``format`` はメッセージに付与可能な discord 文字列表現
    (``<:name:id>`` または ``<a:name:id>``) で、Web で選択した値を
    そのまま AutoReactionConfig.emojis に格納できる。
    """
    result = await db.execute(
        select(DiscordEmoji)
        .where(DiscordEmoji.available.is_(True))
        .order_by(DiscordEmoji.guild_id, DiscordEmoji.name)
    )
    emojis_map: dict[str, list[dict[str, object]]] = {}
    for emoji in result.scalars():
        prefix = "<a:" if emoji.animated else "<:"
        formatted = f"{prefix}{emoji.name}:{emoji.emoji_id}>"
        emojis_map.setdefault(emoji.guild_id, []).append(
            {
                "id": emoji.emoji_id,
                "name": emoji.name,
                "animated": emoji.animated,
                "format": formatted,
            }
        )
    return emojis_map
