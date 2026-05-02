"""AutoReaction の DB 操作。"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import AutoReactionConfig

__all__ = [
    "MAX_AUTO_REACTION_EMOJIS",
    "decode_auto_reaction_emojis",
    "encode_auto_reaction_emojis",
    "get_enabled_auto_reaction_emoji_map",
    "normalize_auto_reaction_emojis",
]

# Discord は1メッセージあたり最大20リアクションまで
MAX_AUTO_REACTION_EMOJIS = 20


def normalize_auto_reaction_emojis(emojis: list[str]) -> list[str]:
    """前後空白除去と空要素除外。"""
    return [e.strip() for e in emojis if isinstance(e, str) and e.strip()]


def encode_auto_reaction_emojis(emojis: list[str]) -> str:
    return json.dumps(emojis, ensure_ascii=False)


def decode_auto_reaction_emojis(encoded: str) -> list[str]:
    """壊れた JSON や型不一致は空リストにフォールバック。"""
    try:
        value = json.loads(encoded)
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [s for s in value if isinstance(s, str) and s]


async def get_enabled_auto_reaction_emoji_map(
    session: AsyncSession,
) -> dict[str, list[str]]:
    """有効な設定の channel_id → 絵文字リスト辞書。

    Cog の on_message ホットパスで参照するキャッシュの元データ。
    """
    stmt = select(AutoReactionConfig.channel_id, AutoReactionConfig.emojis).where(
        AutoReactionConfig.enabled.is_(True)
    )
    result = await session.execute(stmt)
    return {
        channel_id: decode_auto_reaction_emojis(emojis)
        for channel_id, emojis in result.all()
    }
