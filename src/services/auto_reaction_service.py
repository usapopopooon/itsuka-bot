"""AutoReaction の DB 操作。"""

from __future__ import annotations

import json
import re

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import AutoReactionConfig

__all__ = [
    "MAX_AUTO_REACTION_EMOJIS",
    "create_auto_reaction_config",
    "decode_auto_reaction_emojis",
    "delete_auto_reaction_config",
    "encode_auto_reaction_emojis",
    "get_auto_reaction_configs",
    "get_enabled_auto_reaction_emoji_map",
    "normalize_auto_reaction_emojis",
    "parse_emoji_input",
    "set_auto_reaction_config",
    "toggle_auto_reaction_config",
]

# Discord は1メッセージあたり最大20リアクションまで
MAX_AUTO_REACTION_EMOJIS = 20

# カスタム絵文字 <:name:id> / <a:name:id> を抽出する
_CUSTOM_EMOJI_RE = re.compile(r"<a?:[a-zA-Z0-9_]+:\d+>")
# 空白で区切ったトークン
_WHITESPACE_RE = re.compile(r"\s+")


def parse_emoji_input(raw: str) -> list[str]:
    """ユーザーが渡した絵文字文字列を要素リストへ分解する。

    - カスタム絵文字 (``<:name:id>`` / ``<a:name:id>``) を最優先で抽出
    - 残りを空白で分割し、空要素を除去
    - Unicode 絵文字は1要素にまとめて入っていることが多いため
      `空白なし` の塊もそのまま1要素として扱う
    """
    if not raw:
        return []

    result: list[str] = []
    last_end = 0
    for m in _CUSTOM_EMOJI_RE.finditer(raw):
        before = raw[last_end : m.start()]
        for token in _WHITESPACE_RE.split(before):
            if token:
                result.append(token)
        result.append(m.group(0))
        last_end = m.end()
    tail = raw[last_end:]
    for token in _WHITESPACE_RE.split(tail):
        if token:
            result.append(token)
    return result


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


async def set_auto_reaction_config(
    session: AsyncSession,
    guild_id: str,
    channel_id: str,
    emojis: list[str],
) -> AutoReactionConfig:
    """チャンネルの設定を作成 or 更新する (upsert)。"""
    stmt = select(AutoReactionConfig).where(
        AutoReactionConfig.guild_id == guild_id,
        AutoReactionConfig.channel_id == channel_id,
    )
    result = await session.execute(stmt)
    config = result.scalar_one_or_none()

    encoded = encode_auto_reaction_emojis(emojis)
    if config is None:
        config = AutoReactionConfig(
            guild_id=guild_id,
            channel_id=channel_id,
            emojis=encoded,
            enabled=True,
        )
        session.add(config)
    else:
        config.emojis = encoded
        config.enabled = True

    await session.commit()
    await session.refresh(config)
    return config


async def create_auto_reaction_config(
    session: AsyncSession,
    guild_id: str,
    channel_id: str,
    emojis: list[str],
) -> AutoReactionConfig:
    """設定を新規作成する (重複チェックは呼び出し側で)。"""
    config = AutoReactionConfig(
        guild_id=guild_id,
        channel_id=channel_id,
        emojis=encode_auto_reaction_emojis(emojis),
    )
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config


async def get_auto_reaction_configs(
    session: AsyncSession, guild_id: str | None = None
) -> list[AutoReactionConfig]:
    stmt = select(AutoReactionConfig).order_by(AutoReactionConfig.id)
    if guild_id is not None:
        stmt = stmt.where(AutoReactionConfig.guild_id == guild_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


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


async def toggle_auto_reaction_config(
    session: AsyncSession, guild_id: str, channel_id: str
) -> AutoReactionConfig | None:
    stmt = select(AutoReactionConfig).where(
        AutoReactionConfig.guild_id == guild_id,
        AutoReactionConfig.channel_id == channel_id,
    )
    result = await session.execute(stmt)
    config = result.scalar_one_or_none()
    if config is None:
        return None
    config.enabled = not config.enabled
    await session.commit()
    await session.refresh(config)
    return config


async def delete_auto_reaction_config(
    session: AsyncSession, guild_id: str, channel_id: str
) -> bool:
    stmt = delete(AutoReactionConfig).where(
        AutoReactionConfig.guild_id == guild_id,
        AutoReactionConfig.channel_id == channel_id,
    )
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount or 0) > 0  # type: ignore[attr-defined]
