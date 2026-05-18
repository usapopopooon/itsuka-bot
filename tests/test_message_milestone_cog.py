"""MessageMilestone Cog のテンプレート展開テスト。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import discord

from src.cogs.message_milestone import MessageMilestoneCog
from src.services.message_milestone_service import ChannelMessageMilestone


def _config() -> ChannelMessageMilestone:
    return ChannelMessageMilestone(
        id=1,
        channel_id="123",
        daily_required_count=7,
        required_days=3,
        pattern=None,
        response_type="plain",
        message_content="{username} が {n} 回達成",
        embed_title="{username}",
        embed_description="{count} posts",
        embed_color=None,
        delete_after_seconds=None,
        backfill_completed=True,
    )


def test_render_reward_replaces_username_and_count() -> None:
    author = MagicMock()
    author.display_name = "Itsuka"
    author.name = "fallback"
    cog = MessageMilestoneCog(MagicMock())
    config = _config()

    rendered = cog._render_reward(config, author)

    assert rendered.content == "Itsuka が 7 回達成"
    assert rendered.embed_title == "Itsuka"
    assert rendered.embed_description == "7 posts"


def test_rendered_reward_is_not_sendable_after_template_expands_too_long() -> None:
    author = MagicMock()
    author.display_name = "x" * 300
    author.name = "fallback"
    cog = MessageMilestoneCog(MagicMock())
    config = _config()
    config = ChannelMessageMilestone(
        **{**config.__dict__, "response_type": "embed", "embed_title": "{username}"}
    )

    rendered = cog._render_reward(config, author)

    assert not cog._rendered_reward_is_sendable(config, rendered)


def test_countdown_step_uses_coarser_updates_for_long_durations() -> None:
    cog = MessageMilestoneCog(MagicMock())

    assert cog._countdown_step_seconds(5) == 1
    assert cog._countdown_step_seconds(30) == 5
    assert cog._countdown_step_seconds(120) == 15


def test_configs_for_message_matches_thread_parent_channel() -> None:
    cog = MessageMilestoneCog(MagicMock())
    config = _config()
    cog._configs = {"456": [config]}
    message = MagicMock()
    message.channel.id = 123
    message.channel.parent_id = 456

    assert cog._configs_for_message(message) == [config]


async def test_track_refreshes_stale_configs_before_checking_channel(
    monkeypatch,
) -> None:
    cog = MessageMilestoneCog(MagicMock())
    cog.refresh = AsyncMock()
    cog._configs = {}
    cog._last_refresh_monotonic = 0.0
    monkeypatch.setattr("src.cogs.message_milestone.time.monotonic", lambda: 10.0)
    message = MagicMock()
    message.guild = MagicMock()
    message.author = MagicMock()
    message.author.bot = False
    message.webhook_id = None
    message.type = __import__("discord").MessageType.default
    message.channel.id = 123

    await cog._track(message)

    assert cog.refresh.await_count == 2


async def test_track_refreshes_again_when_channel_missing_from_fresh_cache(
    monkeypatch,
) -> None:
    cog = MessageMilestoneCog(MagicMock())
    cog.refresh = AsyncMock()
    cog._configs = {}
    cog._last_refresh_monotonic = 10.0
    monkeypatch.setattr("src.cogs.message_milestone.time.monotonic", lambda: 10.5)
    message = MagicMock()
    message.guild = MagicMock()
    message.author = MagicMock()
    message.author.bot = False
    message.webhook_id = None
    message.type = __import__("discord").MessageType.default
    message.channel.id = 123

    await cog._track(message)

    cog.refresh.assert_awaited_once()


async def test_backfill_config_tracks_today_history(monkeypatch) -> None:
    cog = MessageMilestoneCog(MagicMock())
    config = ChannelMessageMilestone(
        **{**_config().__dict__, "backfill_completed": False}
    )
    today_message = MagicMock()
    today_message.created_at = datetime.now(UTC)
    old_message = MagicMock()
    old_message.created_at = datetime(2020, 1, 1, tzinfo=UTC)
    channel = MagicMock(spec=discord.abc.Messageable)
    channel.history.return_value = _AsyncIter([today_message, old_message])
    cog.bot.get_channel.return_value = channel
    tracked: list[MagicMock] = []

    async def fake_track(message):
        tracked.append(message)

    monkeypatch.setattr(cog, "_track", fake_track)
    monkeypatch.setattr(
        "src.cogs.message_milestone.mark_message_milestone_backfill_completed",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "src.cogs.message_milestone.async_session",
        lambda: _AsyncContext(MagicMock()),
    )

    await cog._backfill_config(config)

    assert tracked == [today_message]


def test_message_is_before_today_uses_milestone_timezone(monkeypatch) -> None:
    cog = MessageMilestoneCog(MagicMock())
    message = MagicMock()
    message.created_at = datetime(2026, 5, 17, 16, 0, tzinfo=UTC)

    def fake_milestone_date(created_at):
        if created_at is None:
            return date(2026, 5, 18)
        return created_at.astimezone(ZoneInfo("Asia/Tokyo")).date()

    monkeypatch.setattr(
        "src.cogs.message_milestone.message_milestone_date",
        fake_milestone_date,
    )

    assert not cog._message_is_before_today(message)


async def test_backfill_config_tracks_forum_thread_history(monkeypatch) -> None:
    cog = MessageMilestoneCog(MagicMock())
    config = ChannelMessageMilestone(
        **{**_config().__dict__, "channel_id": "999", "backfill_completed": False}
    )
    active_message = MagicMock()
    active_message.created_at = datetime.now(UTC)
    archived_message = MagicMock()
    archived_message.created_at = datetime.now(UTC)
    active_thread = MagicMock(spec=discord.Thread)
    archived_thread = MagicMock(spec=discord.Thread)
    active_thread.history.return_value = _AsyncIter([active_message])
    archived_thread.history.return_value = _AsyncIter([archived_message])
    forum = MagicMock(spec=discord.ForumChannel)
    forum.threads = [active_thread]
    forum.archived_threads.return_value = _AsyncIter([archived_thread])
    cog.bot.get_channel.return_value = forum
    tracked: list[MagicMock] = []

    async def fake_track(message):
        tracked.append(message)

    monkeypatch.setattr(cog, "_track", fake_track)
    monkeypatch.setattr(
        "src.cogs.message_milestone.mark_message_milestone_backfill_completed",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "src.cogs.message_milestone.async_session",
        lambda: _AsyncContext(MagicMock()),
    )

    await cog._backfill_config(config)

    assert tracked == [active_message, archived_message]


class _AsyncIter:
    def __init__(self, items: list) -> None:
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


class _AsyncContext:
    def __init__(self, value) -> None:
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_exc) -> None:
        return None
