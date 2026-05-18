"""MessageMilestone の達成判定テスト。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.database.models import (
    Base,
    MessageMilestoneConfig,
    MessageMilestoneProcessedMessage,
    MessageMilestoneProgress,
)
from src.services.message_milestone_service import (
    ChannelMessageMilestone,
    MilestoneTemplateContext,
    delete_message_milestone_state,
    mark_message_milestone_reward_sent,
    normalize_embed_color,
    record_consecutive_message_and_get_reward,
    record_message_and_get_reward,
    render_milestone_template,
    validate_pattern,
)


def _config(*, daily: int = 2, days: int = 2) -> ChannelMessageMilestone:
    return ChannelMessageMilestone(
        id=1,
        channel_id="123",
        condition_type="daily_streak",
        daily_required_count=daily,
        required_days=days,
        pattern=None,
        response_type="plain",
        message_content="done",
        embed_title=None,
        embed_description=None,
        embed_color=None,
        delete_after_seconds=None,
        backfill_completed=True,
    )


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def test_record_message_sends_after_daily_goal_for_required_days(
    session_factory,
) -> None:
    config = _config(daily=2, days=2)
    day1 = datetime(2026, 5, 18, 1, tzinfo=UTC)
    day2 = datetime(2026, 5, 19, 1, tzinfo=UTC)

    async with session_factory() as session:
        first = await record_message_and_get_reward(
            session, config=config, user_id="u1", created_at=day1
        )
        second = await record_message_and_get_reward(
            session, config=config, user_id="u1", created_at=day1
        )
        third = await record_message_and_get_reward(
            session, config=config, user_id="u1", created_at=day2
        )
        fourth = await record_message_and_get_reward(
            session, config=config, user_id="u1", created_at=day2
        )

    assert not first.should_send
    assert not second.should_send
    assert not third.should_send
    assert fourth.should_send
    assert fourth.streak_days == 2


async def test_record_message_only_sends_once_per_streak(session_factory) -> None:
    config = _config(daily=1, days=1)
    day1 = datetime(2026, 5, 18, 1, tzinfo=UTC)
    day2 = datetime(2026, 5, 19, 1, tzinfo=UTC)

    async with session_factory() as session:
        first = await record_message_and_get_reward(
            session, config=config, user_id="u1", created_at=day1
        )
        await mark_message_milestone_reward_sent(
            session, config_id=config.id, user_id="u1"
        )
        second = await record_message_and_get_reward(
            session, config=config, user_id="u1", created_at=day1
        )
        third = await record_message_and_get_reward(
            session, config=config, user_id="u1", created_at=day2
        )

    assert first.should_send
    assert not second.should_send
    assert not third.should_send


async def test_pending_reward_retries_until_marked_sent(session_factory) -> None:
    config = _config(daily=1, days=1)
    day1 = datetime(2026, 5, 18, 1, tzinfo=UTC)

    async with session_factory() as session:
        first = await record_message_and_get_reward(
            session, config=config, user_id="u1", created_at=day1
        )
        retry = await record_message_and_get_reward(
            session, config=config, user_id="u1", created_at=day1
        )
        await mark_message_milestone_reward_sent(
            session, config_id=config.id, user_id="u1"
        )
        after_sent = await record_message_and_get_reward(
            session, config=config, user_id="u1", created_at=day1
        )

    assert first.should_send
    assert retry.should_send
    assert not after_sent.should_send


async def test_record_message_resets_after_missed_day(session_factory) -> None:
    config = _config(daily=1, days=2)
    day1 = datetime(2026, 5, 18, 1, tzinfo=UTC)
    day3 = datetime(2026, 5, 20, 1, tzinfo=UTC)

    async with session_factory() as session:
        await record_message_and_get_reward(
            session, config=config, user_id="u1", created_at=day1
        )
        result = await record_message_and_get_reward(
            session, config=config, user_id="u1", created_at=day3
        )

    assert not result.should_send
    assert result.streak_days == 1


async def test_delete_message_milestone_state_removes_progress_and_processed(
    session_factory,
) -> None:
    config = _config(daily=1, days=1)
    day1 = datetime(2026, 5, 18, 1, tzinfo=UTC)

    async with session_factory() as session:
        await record_message_and_get_reward(
            session,
            config=config,
            user_id="u1",
            created_at=day1,
            message_id="m1",
        )
        await delete_message_milestone_state(session, config_id=config.id)
        await session.commit()

        progress = await session.execute(select(MessageMilestoneProgress))
        processed = await session.execute(select(MessageMilestoneProcessedMessage))

    assert progress.scalars().all() == []
    assert processed.scalars().all() == []


async def test_record_consecutive_message_sends_after_same_user_reaches_goal(
    session_factory,
) -> None:
    config = ChannelMessageMilestone(
        **{**_config(daily=3, days=1).__dict__, "condition_type": "consecutive_posts"}
    )

    async with session_factory() as session:
        session.add(
            MessageMilestoneConfig(
                id=config.id,
                guild_id="g1",
                channel_id=config.channel_id,
                condition_type=config.condition_type,
                daily_required_count=config.daily_required_count,
                required_days=1,
                response_type="plain",
                message_content="done",
                backfill_completed=True,
            )
        )
        await session.commit()
        first = await record_consecutive_message_and_get_reward(
            session, config=config, user_id="u1", message_id="m1"
        )
        second = await record_consecutive_message_and_get_reward(
            session, config=config, user_id="u1", message_id="m2"
        )
        third = await record_consecutive_message_and_get_reward(
            session, config=config, user_id="u1", message_id="m3"
        )
        fourth = await record_consecutive_message_and_get_reward(
            session, config=config, user_id="u1", message_id="m4"
        )

    assert not first.should_send
    assert not second.should_send
    assert third.should_send
    assert third.consecutive_count == 3
    assert fourth.should_send
    assert fourth.consecutive_count == 4


async def test_record_consecutive_message_resets_when_user_changes(
    session_factory,
) -> None:
    config = ChannelMessageMilestone(
        **{**_config(daily=2, days=1).__dict__, "condition_type": "consecutive_posts"}
    )

    async with session_factory() as session:
        session.add(
            MessageMilestoneConfig(
                id=config.id,
                guild_id="g1",
                channel_id=config.channel_id,
                condition_type=config.condition_type,
                daily_required_count=config.daily_required_count,
                required_days=1,
                response_type="plain",
                message_content="done",
                backfill_completed=True,
            )
        )
        await session.commit()
        await record_consecutive_message_and_get_reward(
            session, config=config, user_id="u1", message_id="m1"
        )
        reset = await record_consecutive_message_and_get_reward(
            session, config=config, user_id="u2", message_id="m2"
        )

    assert not reset.should_send
    assert reset.consecutive_count == 1


def test_normalize_embed_color_accepts_hash_hex() -> None:
    assert normalize_embed_color("#22C55E") == 0x22C55E
    assert normalize_embed_color("22c55e") == 0x22C55E


def test_validate_pattern_strips_and_allows_regex() -> None:
    assert validate_pattern("  (?i)done|daily ") == "(?i)done|daily"
    assert validate_pattern("  ") is None


def test_render_milestone_template_replaces_known_variables() -> None:
    context = MilestoneTemplateContext(
        username="Itsuka", daily_required_count=7, current_count=9
    )

    assert (
        render_milestone_template(
            "{username}: {n}/{count}/{current_count}/{current} {unknown}", context
        )
        == "Itsuka: 7/7/9/9 {unknown}"
    )
    assert render_milestone_template(None, context) is None
