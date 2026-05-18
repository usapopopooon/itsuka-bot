"""MessageMilestone Cog のテンプレート展開テスト。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from src.cogs.message_milestone import MessageMilestoneCog
from src.services.message_milestone_service import ChannelMessageMilestone


def _config() -> ChannelMessageMilestone:
    return ChannelMessageMilestone(
        id=1,
        channel_id="123",
        condition_type="daily_streak",
        daily_required_count=7,
        required_days=3,
        pattern=None,
        response_type="plain",
        message_content="{username} が {n} 回達成",
        embed_title="{username}",
        embed_description="{count} posts",
        embed_color=None,
        delete_after_seconds=None,
        consecutive_notification_limit="none",
        consecutive_notification_daily_limit=1,
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


def test_render_reward_replaces_current_count() -> None:
    author = MagicMock()
    author.display_name = "Itsuka"
    author.name = "fallback"
    cog = MessageMilestoneCog(MagicMock())
    config = ChannelMessageMilestone(
        **{
            **_config().__dict__,
            "message_content": "{username}: {current_count}/{n}",
        }
    )

    rendered = cog._render_reward(config, author, current_count=12)

    assert rendered.content == "Itsuka: 12/7"


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


def test_embed_fallback_content_uses_rendered_embed_fields() -> None:
    author = MagicMock()
    author.display_name = "Itsuka"
    author.name = "fallback"
    cog = MessageMilestoneCog(MagicMock())
    config = ChannelMessageMilestone(
        **{
            **_config().__dict__,
            "response_type": "embed",
            "message_content": None,
            "embed_title": "{username} さん",
            "embed_description": "{n} 回達成",
        }
    )

    rendered = cog._render_reward(config, author)

    assert cog._embed_fallback_content(rendered) == "Itsuka さん\n7 回達成"


def test_countdown_step_updates_every_second() -> None:
    cog = MessageMilestoneCog(MagicMock())

    assert cog._countdown_step_seconds(5) == 1
    assert cog._countdown_step_seconds(30) == 1
    assert cog._countdown_step_seconds(120) == 1


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
