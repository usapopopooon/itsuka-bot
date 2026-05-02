"""AutoReaction の DB 操作。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import AutoReactionConfig

__all__ = [
    "MAX_AUTO_REACTION_EMOJIS",
    "MAX_PATTERN_LENGTH",
    "ChannelAutoReaction",
    "compile_pattern",
    "decode_auto_reaction_emojis",
    "encode_auto_reaction_emojis",
    "get_enabled_auto_reactions",
    "normalize_auto_reaction_emojis",
    "validate_pattern",
]

# Discord は1メッセージあたり最大20リアクションまで
MAX_AUTO_REACTION_EMOJIS = 20

# 正規表現フィルタの最大文字数 (DoS 対策)
MAX_PATTERN_LENGTH = 500


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


def validate_pattern(raw: str | None) -> str | None:
    """正規表現を検証し、保存用の文字列を返す。

    None / 空文字 / ホワイトスペースのみ → ``None`` (フィルタなし)。
    コンパイル失敗時は ``re.error`` を投げる (呼び出し側で 422 にする)。
    過大な長さも弾く。
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if len(s) > MAX_PATTERN_LENGTH:
        raise re.error(f"pattern too long (max {MAX_PATTERN_LENGTH} chars)")
    re.compile(s)
    return s


def compile_pattern(raw: str | None) -> re.Pattern[str] | None:
    """保存済みの pattern を ``re.Pattern`` に変換する。

    破損した値は警告ではなく ``None`` 扱いにして on_message を
    クラッシュさせない (validate_pattern 通過済みのはずだが防御的に)。
    """
    if not raw:
        return None
    try:
        return re.compile(raw)
    except re.error:
        return None


@dataclass(frozen=True)
class ChannelAutoReaction:
    """on_message ホットパスで参照する事前計算済みレコード。"""

    emojis: list[str]
    pattern: re.Pattern[str] | None


async def get_enabled_auto_reactions(
    session: AsyncSession,
) -> dict[str, ChannelAutoReaction]:
    """有効な設定の channel_id → (emojis, compiled pattern) の辞書。

    Cog の on_message ホットパスで参照する事前計算済みキャッシュ。
    """
    stmt = select(
        AutoReactionConfig.channel_id,
        AutoReactionConfig.emojis,
        AutoReactionConfig.pattern,
    ).where(AutoReactionConfig.enabled.is_(True))
    result = await session.execute(stmt)
    return {
        channel_id: ChannelAutoReaction(
            emojis=decode_auto_reaction_emojis(emojis),
            pattern=compile_pattern(pattern),
        )
        for channel_id, emojis, pattern in result.all()
    }
