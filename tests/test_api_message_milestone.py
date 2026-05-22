"""Message milestone API helpers."""

from __future__ import annotations

from src.database.models import MessageMilestoneConfig
from src.web.routes.api_message_milestone import _should_reset_progress


def _model() -> MessageMilestoneConfig:
    return MessageMilestoneConfig(
        guild_id="g1",
        channel_id="c1",
        condition_type="daily_streak",
        daily_required_count=1,
        required_days=7,
        pattern="done",
        response_type="plain",
        message_content="{current_count} combo",
    )


def test_message_milestone_update_keeps_progress_for_message_only_changes() -> None:
    config = _model()

    assert not _should_reset_progress(
        config,
        {
            "condition_type": "daily_streak",
            "daily_required_count": 1,
            "required_days": 30,
            "pattern": "done",
            "response_type": "plain",
            "message_content": "new text",
            "embed_title": None,
            "embed_description": None,
            "embed_color": None,
            "delete_after_seconds": None,
        },
    )


def test_message_milestone_update_resets_progress_for_counting_changes() -> None:
    config = _model()

    assert _should_reset_progress(
        config,
        {
            "condition_type": "daily_streak",
            "daily_required_count": 2,
            "required_days": 7,
            "pattern": "done",
        },
    )
