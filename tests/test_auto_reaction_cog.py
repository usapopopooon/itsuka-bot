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
from src.database.models import AutoReactionConfig
from src.services.auto_reaction_service import decode_auto_reaction_user_ids


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
    author_id: int = 456,
    is_bot: bool = False,
    webhook_id: int | None = None,
    msg_type: discord.MessageType = discord.MessageType.default,
    reactions: list | None = None,
) -> MagicMock:
    msg = MagicMock()
    msg.id = 999
    msg.guild = MagicMock()
    msg.author = MagicMock()
    msg.author.id = author_id
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


def _interaction(
    *, guild_id: int | None = 123, administrator: bool = True
) -> MagicMock:
    interaction = MagicMock()
    interaction.guild_id = guild_id
    interaction.permissions = MagicMock()
    interaction.permissions.administrator = administrator
    interaction.user = MagicMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


def _member(*, member_id: int = 456, mention: str = "<@456>") -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.mention = mention
    return member


async def test_exclude_command_rejects_non_admin() -> None:
    cog = _cog()
    interaction = _interaction(administrator=False)

    await AutoReactionCog.auto_reaction_exclude.callback(
        cog, interaction, user=_member(), clear=False
    )

    interaction.response.send_message.assert_called_once_with(
        "このコマンドは管理者のみ実行できます。",
        ephemeral=True,
    )


async def test_exclude_command_adds_selected_member(monkeypatch) -> None:
    class _FakeScalars:
        def __init__(self, configs: list[AutoReactionConfig]) -> None:
            self.configs = configs

        def all(self) -> list[AutoReactionConfig]:
            return self.configs

    class _FakeResult:
        def __init__(self, configs: list[AutoReactionConfig]) -> None:
            self.configs = configs

        def scalars(self) -> _FakeScalars:
            return _FakeScalars(self.configs)

    class _FakeSession:
        def __init__(self, configs: list[AutoReactionConfig]) -> None:
            self.configs = configs
            self.committed = False

        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def execute(self, _stmt) -> _FakeResult:
            return _FakeResult(self.configs)

        async def commit(self) -> None:
            self.committed = True

    config_a = AutoReactionConfig(
        id=7,
        guild_id="123",
        channel_id="999",
        emojis="[]",
        excluded_user_ids='["111"]',
    )
    config_b = AutoReactionConfig(
        id=8,
        guild_id="123",
        channel_id="998",
        emojis="[]",
        excluded_user_ids="[]",
    )
    session = _FakeSession([config_a, config_b])
    monkeypatch.setattr("src.cogs.auto_reaction.async_session", lambda: session)

    cog = _cog()
    cog.refresh = AsyncMock()  # type: ignore[method-assign]
    interaction = _interaction(guild_id=123)

    await AutoReactionCog.auto_reaction_exclude.callback(
        cog, interaction, user=_member(member_id=456), clear=False
    )

    assert session.committed
    assert decode_auto_reaction_user_ids(config_a.excluded_user_ids) == ["111", "456"]
    assert decode_auto_reaction_user_ids(config_b.excluded_user_ids) == ["456"]
    cog.refresh.assert_awaited_once()
    interaction.response.send_message.assert_called_once_with(
        "<@456> をこのサーバーの Auto Reaction "
        "除外ユーザーに追加しました。対象設定: 2件",
        ephemeral=True,
    )


async def test_exclude_command_clears_config(monkeypatch) -> None:
    class _FakeScalars:
        def __init__(self, configs: list[AutoReactionConfig]) -> None:
            self.configs = configs

        def all(self) -> list[AutoReactionConfig]:
            return self.configs

    class _FakeResult:
        def __init__(self, configs: list[AutoReactionConfig]) -> None:
            self.configs = configs

        def scalars(self) -> _FakeScalars:
            return _FakeScalars(self.configs)

    class _FakeSession:
        def __init__(self, configs: list[AutoReactionConfig]) -> None:
            self.configs = configs
            self.committed = False

        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def execute(self, _stmt) -> _FakeResult:
            return _FakeResult(self.configs)

        async def commit(self) -> None:
            self.committed = True

    config_a = AutoReactionConfig(
        id=7,
        guild_id="123",
        channel_id="999",
        emojis="[]",
        excluded_user_ids='["111", "456"]',
    )
    config_b = AutoReactionConfig(
        id=8,
        guild_id="123",
        channel_id="998",
        emojis="[]",
        excluded_user_ids='["456"]',
    )
    session = _FakeSession([config_a, config_b])
    monkeypatch.setattr("src.cogs.auto_reaction.async_session", lambda: session)

    cog = _cog()
    cog.refresh = AsyncMock()  # type: ignore[method-assign]
    interaction = _interaction(guild_id=123)

    await AutoReactionCog.auto_reaction_exclude.callback(
        cog, interaction, user=None, clear=True
    )

    assert session.committed
    assert decode_auto_reaction_user_ids(config_a.excluded_user_ids) == []
    assert decode_auto_reaction_user_ids(config_b.excluded_user_ids) == []
    cog.refresh.assert_awaited_once()
    interaction.response.send_message.assert_called_once_with(
        "このサーバーの Auto Reaction 除外ユーザーを全解除しました。",
        ephemeral=True,
    )


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


async def test_reconcile_skips_excluded_author() -> None:
    cog = _cog()
    cog._configs = {
        "123": [
            _CachedConfig(
                emojis=[_emoji("👍")],
                pattern=None,
                excluded_user_ids=frozenset({"456"}),
            )
        ]
    }
    msg = _message(content="hi", author_id=456)

    await cog._reconcile(msg)

    msg.add_reaction.assert_not_called()
    msg.remove_reaction.assert_not_called()


async def test_reconcile_removes_bot_reaction_when_author_becomes_excluded() -> None:
    cog = _cog()
    cog._configs = {
        "123": [
            _CachedConfig(
                emojis=[_emoji("👍")],
                pattern=None,
                excluded_user_ids=frozenset({"456"}),
            )
        ]
    }
    msg = _message(content="hi", author_id=456, reactions=[_reaction("👍", me=True)])

    await cog._reconcile(msg)

    msg.add_reaction.assert_not_called()
    msg.remove_reaction.assert_called_once()


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


# ---- sweep_recent_messages: ``on_message`` 取りこぼし用セーフティネット ----


class _AsyncIter:
    """``async for`` で消費できる単純な list ベースの非同期イテレータ。"""

    def __init__(self, items: list) -> None:
        self._items = list(items)

    def __aiter__(self) -> _AsyncIter:
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


def _channel_with_history(messages: list) -> MagicMock:
    # spec で discord.abc.Messageable を渡すと isinstance チェックを通る。
    ch = MagicMock(spec=discord.abc.Messageable)
    ch.history = MagicMock(return_value=_AsyncIter(messages))
    return ch


async def test_sweep_adds_missing_reactions_from_recent_history() -> None:
    cog = _cog()
    cog._configs = {"123": [_CachedConfig(emojis=[_emoji("👍")], pattern=None)]}
    # 取りこぼしたメッセージ: bot のリアクションがまだ無い。
    missed = _message(channel_id=123, content="hello")
    # 既に同期済み: 二重付与しない。
    already = _message(
        channel_id=123, content="hi", reactions=[_reaction("👍", me=True)]
    )
    cog.bot.get_channel.return_value = _channel_with_history([missed, already])

    await cog.sweep_recent_messages()

    missed.add_reaction.assert_called_once()
    already.add_reaction.assert_not_called()
    already.remove_reaction.assert_not_called()


async def test_sweep_uses_configured_history_limit() -> None:
    from src.cogs.auto_reaction import _SWEEP_HISTORY_LIMIT

    cog = _cog()
    cog._configs = {"123": [_CachedConfig(emojis=[_emoji("👍")], pattern=None)]}
    channel = _channel_with_history([])
    cog.bot.get_channel.return_value = channel

    await cog.sweep_recent_messages()

    channel.history.assert_called_once_with(limit=_SWEEP_HISTORY_LIMIT)


async def test_sweep_iterates_every_configured_channel() -> None:
    cog = _cog()
    cog._configs = {
        "100": [_CachedConfig(emojis=[_emoji("👍")], pattern=None)],
        "200": [_CachedConfig(emojis=[_emoji("❤️")], pattern=None)],
    }
    msg_a = _message(channel_id=100, content="a")
    msg_b = _message(channel_id=200, content="b")

    def get_channel(cid: int) -> MagicMock | None:
        if cid == 100:
            return _channel_with_history([msg_a])
        if cid == 200:
            return _channel_with_history([msg_b])
        return None

    cog.bot.get_channel.side_effect = get_channel

    await cog.sweep_recent_messages()

    msg_a.add_reaction.assert_called_once()
    msg_b.add_reaction.assert_called_once()


async def test_sweep_skips_when_channel_not_in_cache() -> None:
    cog = _cog()
    cog._configs = {"123": [_CachedConfig(emojis=[_emoji("👍")], pattern=None)]}
    cog.bot.get_channel.return_value = None

    # 削除済み / 未参加チャンネルでも例外を投げない。
    await cog.sweep_recent_messages()


async def test_sweep_skips_non_messageable_channel() -> None:
    cog = _cog()
    cog._configs = {"123": [_CachedConfig(emojis=[_emoji("👍")], pattern=None)]}
    # CategoryChannel など Messageable で無いチャンネルは history() を
    # 持たないのでスキップする。
    channel = MagicMock(spec=discord.CategoryChannel)
    cog.bot.get_channel.return_value = channel

    await cog.sweep_recent_messages()

    # history も呼ばずスキップ。
    if hasattr(channel, "history"):
        channel.history.assert_not_called()


async def test_sweep_swallows_http_errors_per_channel() -> None:
    cog = _cog()
    cog._configs = {
        "100": [_CachedConfig(emojis=[_emoji("👍")], pattern=None)],
        "200": [_CachedConfig(emojis=[_emoji("❤️")], pattern=None)],
    }
    response = MagicMock(status=500, reason="Internal Server Error")
    failing = MagicMock(spec=discord.abc.Messageable)
    failing.history = MagicMock(side_effect=discord.HTTPException(response, "boom"))
    msg = _message(channel_id=200, content="ok")
    healthy = _channel_with_history([msg])

    def get_channel(cid: int) -> MagicMock:
        return failing if cid == 100 else healthy

    cog.bot.get_channel.side_effect = get_channel

    # 片方が落ちても他方の sweep は継続する。
    await cog.sweep_recent_messages()
    msg.add_reaction.assert_called_once()


async def test_sweep_does_nothing_when_configs_uninitialized() -> None:
    cog = _cog()
    cog._configs = None

    await cog.sweep_recent_messages()

    cog.bot.get_channel.assert_not_called()


async def test_sweep_respects_reconcile_filters() -> None:
    """sweep は ``_reconcile`` 経由なので bot 投稿 / webhook / 非マッチも弾く。"""
    cog = _cog()
    cog._configs = {
        "123": [_CachedConfig(emojis=[_emoji("👍")], pattern=re.compile(r"foo"))]
    }
    bot_msg = _message(channel_id=123, content="foo", is_bot=True)
    webhook_msg = _message(channel_id=123, content="foo", webhook_id=42)
    nonmatch_msg = _message(channel_id=123, content="bar")
    match_msg = _message(channel_id=123, content="foo")
    cog.bot.get_channel.return_value = _channel_with_history(
        [bot_msg, webhook_msg, nonmatch_msg, match_msg]
    )

    await cog.sweep_recent_messages()

    bot_msg.add_reaction.assert_not_called()
    webhook_msg.add_reaction.assert_not_called()
    nonmatch_msg.add_reaction.assert_not_called()
    match_msg.add_reaction.assert_called_once()
