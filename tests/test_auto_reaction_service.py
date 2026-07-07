"""auto_reaction_service の純粋ユニットテスト (DB なし)。"""

from __future__ import annotations

from src.services.auto_reaction_service import (
    decode_auto_reaction_emojis,
    decode_auto_reaction_user_ids,
    encode_auto_reaction_emojis,
    encode_auto_reaction_user_ids,
    normalize_auto_reaction_emojis,
    normalize_auto_reaction_user_ids,
)


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


def test_normalize_user_ids_splits_mentions_and_deduplicates() -> None:
    assert normalize_auto_reaction_user_ids(
        [" 123, <@456>\n<@!789> 123 "]
    ) == ["123", "456", "789"]


def test_normalize_user_ids_rejects_invalid_tokens() -> None:
    try:
        normalize_auto_reaction_user_ids(["123 abc"])
    except ValueError as e:
        assert "invalid Discord user ID" in str(e)
    else:
        raise AssertionError("invalid user ID was accepted")


def test_user_id_encode_decode_roundtrip() -> None:
    original = ["123", "456"]
    encoded = encode_auto_reaction_user_ids(original)
    assert decode_auto_reaction_user_ids(encoded) == original


def test_decode_invalid_user_ids_json_returns_empty() -> None:
    assert decode_auto_reaction_user_ids("not-json") == []
    assert decode_auto_reaction_user_ids("{}") == []
