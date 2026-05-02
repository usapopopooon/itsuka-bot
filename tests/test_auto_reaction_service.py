"""auto_reaction_service の純粋ユニットテスト (DB なし)。"""

from __future__ import annotations

from src.services.auto_reaction_service import (
    decode_auto_reaction_emojis,
    encode_auto_reaction_emojis,
    normalize_auto_reaction_emojis,
    parse_emoji_input,
)


def test_parse_emoji_input_unicode_only() -> None:
    assert parse_emoji_input("👍 ❤️ 🎉") == ["👍", "❤️", "🎉"]


def test_parse_emoji_input_custom_emojis_kept_intact() -> None:
    raw = "👍 <:custom:123> <a:animated:456> 🎉"
    assert parse_emoji_input(raw) == [
        "👍",
        "<:custom:123>",
        "<a:animated:456>",
        "🎉",
    ]


def test_parse_emoji_input_empty_returns_empty_list() -> None:
    assert parse_emoji_input("") == []
    assert parse_emoji_input("   ") == []


def test_normalize_strips_and_drops_empty() -> None:
    assert normalize_auto_reaction_emojis(["  👍 ", "", "  ", "❤️"]) == ["👍", "❤️"]


def test_encode_decode_roundtrip() -> None:
    original = ["👍", "<:c:1>", "🎉"]
    encoded = encode_auto_reaction_emojis(original)
    assert decode_auto_reaction_emojis(encoded) == original


def test_decode_invalid_json_returns_empty() -> None:
    assert decode_auto_reaction_emojis("not-json") == []
    assert decode_auto_reaction_emojis("{}") == []


def test_decode_filters_non_strings() -> None:
    # 不正な型が混じっていても落ちず、有効要素のみを返すこと
    assert decode_auto_reaction_emojis('["a", 1, null, "b"]') == ["a", "b"]
