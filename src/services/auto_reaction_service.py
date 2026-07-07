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
    "MAX_AUTO_REACTION_EXCLUDED_USERS",
    "MAX_PATTERN_LENGTH",
    "ChannelAutoReaction",
    "compile_pattern",
    "decode_auto_reaction_emojis",
    "decode_auto_reaction_user_ids",
    "encode_auto_reaction_emojis",
    "encode_auto_reaction_user_ids",
    "get_enabled_auto_reactions",
    "normalize_auto_reaction_emojis",
    "normalize_auto_reaction_user_ids",
    "validate_pattern",
]

# Discord は1メッセージあたり最大20リアクションまで
MAX_AUTO_REACTION_EMOJIS = 20

# 1設定あたりの除外ユーザー数。管理画面/コマンドの誤入力で巨大化させない。
MAX_AUTO_REACTION_EXCLUDED_USERS = 100

# 正規表現フィルタの最大文字数 (DoS 対策)
MAX_PATTERN_LENGTH = 500

_USER_ID_PATTERN = re.compile(r"^\d{1,32}$")
_USER_MENTION_PATTERN = re.compile(r"^<@!?(\d{1,32})>$")
_USER_ID_SPLIT_PATTERN = re.compile(r"[\s,、]+")


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


def normalize_auto_reaction_user_ids(user_ids: list[str]) -> list[str]:
    """Discord ユーザー ID 入力を保存用リストに正規化する。

    管理画面と slash command のどちらでも扱いやすいよう、各要素内の
    空白 / カンマ / 読点区切りも分割する。ID は数字のみを正とし、
    Discord のユーザーメンション表記 (``<@123>`` / ``<@!123>``) は
    ID 部分へ正規化する。
    """
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in user_ids:
        if not isinstance(raw, str):
            continue
        for token in _USER_ID_SPLIT_PATTERN.split(raw.strip()):
            if not token:
                continue
            mention = _USER_MENTION_PATTERN.fullmatch(token)
            if mention:
                token = mention.group(1)
            if not _USER_ID_PATTERN.fullmatch(token):
                raise ValueError(f"invalid Discord user ID: {token}")
            if token in seen:
                continue
            normalized.append(token)
            seen.add(token)
            if len(normalized) > MAX_AUTO_REACTION_EXCLUDED_USERS:
                raise ValueError(
                    "too many excluded users "
                    f"(max {MAX_AUTO_REACTION_EXCLUDED_USERS})"
                )
    return normalized


def encode_auto_reaction_user_ids(user_ids: list[str]) -> str:
    return json.dumps(user_ids, ensure_ascii=False)


def decode_auto_reaction_user_ids(encoded: str) -> list[str]:
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
    excluded_user_ids: frozenset[str]


async def get_enabled_auto_reactions(
    session: AsyncSession,
) -> dict[str, list[ChannelAutoReaction]]:
    """有効な設定の channel_id → list[(emojis, compiled pattern)] の辞書。

    Cog の on_message ホットパスで参照する事前計算済みキャッシュ。
    1 チャンネルに複数の設定 (例: pattern 違いで別の絵文字) を持てるため、
    同一 channel_id のレコードはリストに集約する。
    """
    stmt = select(
        AutoReactionConfig.channel_id,
        AutoReactionConfig.emojis,
        AutoReactionConfig.pattern,
        AutoReactionConfig.excluded_user_ids,
    ).where(AutoReactionConfig.enabled.is_(True))
    result = await session.execute(stmt)
    grouped: dict[str, list[ChannelAutoReaction]] = {}
    for channel_id, emojis, pattern, excluded_user_ids in result.all():
        grouped.setdefault(channel_id, []).append(
            ChannelAutoReaction(
                emojis=decode_auto_reaction_emojis(emojis),
                pattern=compile_pattern(pattern),
                excluded_user_ids=frozenset(
                    decode_auto_reaction_user_ids(excluded_user_ids)
                ),
            )
        )
    return grouped
