"""AutoReaction Cog の単体テスト。

`_reconcile` と `on_message_edit` の差分追加・削除ロジックを検証する。
discord.Message などはモック化し、実際の Discord API は叩かない。
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.cogs.auto_reaction import AutoReactionCog, _CachedConfig


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """500ms スリープでテストが遅くなるのを避ける。"""

    async def _instant(_):
        return None

    monkeypatch.setattr("src.cogs.auto_reaction.asyncio.sleep", _instant)


def _emoji(raw: str) -> discord.PartialEmoji:
    return discord.PartialEmoji.from_str(raw)


def _reaction(emoji_str: str, *, me: bool) -> MagicMock:
    r = MagicMock()
    r.emoji = emoji_str
    r.me = me
    return r


def _message(
    *,
    channel_id: int = 123,
    content: str = "",
    is_bot: bool = False,
    webhook_id: int | None = None,
    msg_type: discord.MessageType = discord.MessageType.default,
    reactions: list | None = None,
) -> MagicMock:
    msg = MagicMock()
    msg.id = 999
    msg.guild = MagicMock()
    msg.author = MagicMock()
    msg.author.bot = is_bot
    msg.webhook_id = webhook_id
    msg.type = msg_type
    msg.channel = MagicMock()
    msg.channel.id = channel_id
    msg.content = content
    msg.reactions = reactions or []
    msg.add_reaction = AsyncMock()
    msg.remove_reaction = AsyncMock()
    return msg


def _cog() -> AutoReactionCog:
    bot = MagicMock()
    bot.user = MagicMock()
    return AutoReactionCog(bot)


async def test_reconcile_adds_desired_on_fresh_message() -> None:
    cog = _cog()
    cog._configs = {
        "123": [_CachedConfig(emojis=[_emoji("👍"), _emoji("❤️")], pattern=None)]
    }
    msg = _message(content="hi")

    await cog._reconcile(msg)

    assert msg.add_reaction.await_count == 2
    msg.remove_reaction.assert_not_called()


async def test_reconcile_skips_when_pattern_does_not_match() -> None:
    cog = _cog()
    cog._configs = {
        "123": [_CachedConfig(emojis=[_emoji("👍")], pattern=re.compile(r"foo"))]
    }
    msg = _message(content="bar")

    await cog._reconcile(msg)

    msg.add_reaction.assert_not_called()
    msg.remove_reaction.assert_not_called()


async def test_reconcile_is_idempotent_when_already_in_sync() -> None:
    cog = _cog()
    cog._configs = {"123": [_CachedConfig(emojis=[_emoji("👍")], pattern=None)]}
    msg = _message(content="x", reactions=[_reaction("👍", me=True)])

    await cog._reconcile(msg)

    msg.add_reaction.assert_not_called()
    msg.remove_reaction.assert_not_called()


async def test_reconcile_removes_bot_reaction_when_pattern_no_longer_matches() -> None:
    cog = _cog()
    cog._configs = {
        "123": [_CachedConfig(emojis=[_emoji("👍")], pattern=re.compile(r"foo"))]
    }
    msg = _message(content="bar", reactions=[_reaction("👍", me=True)])

    await cog._reconcile(msg)

    msg.add_reaction.assert_not_called()
    msg.remove_reaction.assert_called_once()
    args = msg.remove_reaction.call_args.args
    assert str(args[0]) == "👍"
    assert args[1] is cog.bot.user


async def test_reconcile_does_not_remove_user_reactions() -> None:
    cog = _cog()
    cog._configs = {
        "123": [_CachedConfig(emojis=[_emoji("👍")], pattern=re.compile(r"foo"))]
    }
    # 同じ絵文字でも他人が付けたものは Reaction.me=False、bot は手を出さない。
    msg = _message(content="bar", reactions=[_reaction("👍", me=False)])

    await cog._reconcile(msg)

    msg.remove_reaction.assert_not_called()


async def test_reconcile_dedups_across_multiple_configs() -> None:
    cog = _cog()
    cog._configs = {
        "123": [
            _CachedConfig(emojis=[_emoji("👍")], pattern=None),
            _CachedConfig(emojis=[_emoji("👍"), _emoji("❤️")], pattern=None),
        ]
    }
    msg = _message(content="x")

    await cog._reconcile(msg)

    assert msg.add_reaction.await_count == 2


async def test_reconcile_skips_bot_authors() -> None:
    cog = _cog()
    cog._configs = {"123": [_CachedConfig(emojis=[_emoji("👍")], pattern=None)]}
    msg = _message(is_bot=True)

    await cog._reconcile(msg)

    msg.add_reaction.assert_not_called()


async def test_reconcile_skips_webhooks() -> None:
    cog = _cog()
    cog._configs = {"123": [_CachedConfig(emojis=[_emoji("👍")], pattern=None)]}
    msg = _message(webhook_id=111)

    await cog._reconcile(msg)

    msg.add_reaction.assert_not_called()


async def test_reconcile_skips_non_reactable_message_types() -> None:
    cog = _cog()
    cog._configs = {"123": [_CachedConfig(emojis=[_emoji("👍")], pattern=None)]}
    msg = _message(msg_type=discord.MessageType.pins_add)

    await cog._reconcile(msg)

    msg.add_reaction.assert_not_called()


async def test_on_message_edit_skips_when_content_unchanged() -> None:
    cog = _cog()
    cog._configs = {"123": [_CachedConfig(emojis=[_emoji("👍")], pattern=None)]}
    before = _message(content="same")
    after = _message(content="same")

    await cog.on_message_edit(before, after)

    after.add_reaction.assert_not_called()
    after.remove_reaction.assert_not_called()


async def test_on_message_edit_adds_when_new_content_matches() -> None:
    cog = _cog()
    cog._configs = {
        "123": [_CachedConfig(emojis=[_emoji("👍")], pattern=re.compile(r"foo"))]
    }
    before = _message(content="bar")
    after = _message(content="foo")

    await cog.on_message_edit(before, after)

    after.add_reaction.assert_called_once()


async def test_on_message_edit_removes_when_new_content_no_longer_matches() -> None:
    cog = _cog()
    cog._configs = {
        "123": [_CachedConfig(emojis=[_emoji("👍")], pattern=re.compile(r"foo"))]
    }
    before = _message(content="foo")
    after = _message(content="bar", reactions=[_reaction("👍", me=True)])

    await cog.on_message_edit(before, after)

    after.remove_reaction.assert_called_once()
