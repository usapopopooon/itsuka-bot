from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.cogs.message_milestone import MessageMilestoneCog
from src.database.models import Base
from src.services.level_bot_client import MessageComboXpAward
from src.services.message_combo_xp_service import (
    MESSAGE_COMBO_XP_REWARDS,
    enqueue_message_combo_delivery,
    get_pending_message_combo_deliveries,
    mark_message_combo_notification_delivered,
    mark_message_combo_xp_delivered,
)
from src.services.message_milestone_service import (
    ChannelMessageMilestone,
    record_message_and_get_reward,
)


def _daily_combo_config() -> ChannelMessageMilestone:
    return ChannelMessageMilestone(
        id=1,
        channel_id="20",
        condition_type="daily_streak",
        daily_required_count=1,
        required_days=20,
        pattern=None,
        response_type="plain",
        message_content="done",
        embed_title=None,
        embed_description=None,
        embed_color=None,
        delete_after_seconds=None,
        backfill_completed=True,
        consecutive_notification_limit="none",
        consecutive_notification_daily_limit=1,
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


async def test_enqueues_guide_and_exact_reward_milestones_once(session_factory) -> None:
    assert MESSAGE_COMBO_XP_REWARDS == {2: 20, 3: 50, 5: 100, 10: 250, 20: 500}
    now = datetime(2026, 8, 7, tzinfo=UTC)
    async with session_factory() as session:
        guide = await enqueue_message_combo_delivery(
            session,
            config_id=1,
            guild_id="10",
            channel_id="20",
            user_id="30",
            message_id="100",
            streak_days=1,
            observed_at=now,
        )
        duplicate = await enqueue_message_combo_delivery(
            session,
            config_id=1,
            guild_id="10",
            channel_id="20",
            user_id="30",
            message_id="100",
            streak_days=1,
            observed_at=now,
        )
        ignored = await enqueue_message_combo_delivery(
            session,
            config_id=1,
            guild_id="10",
            channel_id="20",
            user_id="30",
            message_id="101",
            streak_days=4,
            observed_at=now,
        )

        assert guide is not None
        assert duplicate is guide
        assert guide.xp_delivered_at is not None
        assert ignored is None


async def test_reward_remains_pending_until_both_steps_are_delivered(
    session_factory,
) -> None:
    async with session_factory() as session:
        delivery = await enqueue_message_combo_delivery(
            session,
            config_id=1,
            guild_id="10",
            channel_id="20",
            user_id="30",
            message_id="200",
            streak_days=5,
            observed_at=datetime(2026, 8, 7, tzinfo=UTC),
        )
        assert delivery is not None
        assert await get_pending_message_combo_deliveries(session) == [delivery]

        await mark_message_combo_xp_delivered(session, delivery)
        assert await get_pending_message_combo_deliveries(session) == [delivery]

        await mark_message_combo_notification_delivered(session, delivery)
        assert await get_pending_message_combo_deliveries(session) == []


async def test_pseudo_oracle_daily_sequence_and_reset(session_factory) -> None:
    """仕様表をオラクルにして、20日までの全日を逐次照合する。"""
    config = _daily_combo_config()
    start = datetime(2026, 7, 1, 1, tzinfo=UTC)
    expected = {1: 0, **MESSAGE_COMBO_XP_REWARDS}
    observed: dict[int, int] = {}

    async with session_factory() as session:
        for day in range(1, 21):
            at = start + timedelta(days=day - 1)
            # 他ユーザーの投稿はu1の日数コンボに影響しない。
            await record_message_and_get_reward(
                session,
                config=config,
                user_id="other",
                created_at=at,
                message_id=f"other-{day}",
            )
            progress = await record_message_and_get_reward(
                session,
                config=config,
                user_id="u1",
                created_at=at,
                message_id=f"u1-{day}",
            )
            assert progress.streak_days == day
            if progress.streak_days == 1:
                observed[day] = 0
            elif progress.streak_days in MESSAGE_COMBO_XP_REWARDS:
                observed[day] = MESSAGE_COMBO_XP_REWARDS[progress.streak_days]

        assert observed == expected

        reset = await record_message_and_get_reward(
            session,
            config=config,
            user_id="u1",
            created_at=start + timedelta(days=21),
            message_id="u1-after-gap",
        )
        assert reset.streak_days == 1
        assert reset.reset_reason is not None


async def test_delivery_waits_for_xp_then_notifies_once(
    session_factory, monkeypatch
) -> None:
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    bot = MagicMock()
    bot.get_channel.return_value = channel
    cog = MessageMilestoneCog(bot)
    award = AsyncMock(
        return_value=MessageComboXpAward(
            event_id="itsuka:1:300",
            streak_days=5,
            awarded_xp=100,
            duplicate=False,
        )
    )
    monkeypatch.setattr("src.cogs.message_milestone.award_message_combo_xp", award)

    async with session_factory() as session:
        delivery = await enqueue_message_combo_delivery(
            session,
            config_id=1,
            guild_id="10",
            channel_id="20",
            user_id="30",
            message_id="300",
            streak_days=5,
            observed_at=datetime(2026, 8, 7, tzinfo=UTC),
        )
        assert delivery is not None
        await cog._deliver_combo_delivery(session, delivery)
        await cog._deliver_combo_delivery(session, delivery)

        award.assert_awaited_once()
        channel.send.assert_awaited_once()
        assert delivery.xp_delivered_at is not None
        assert delivery.notification_delivered_at is not None


async def test_failed_xp_delivery_does_not_claim_or_announce(
    session_factory, monkeypatch
) -> None:
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    bot = MagicMock()
    bot.get_channel.return_value = channel
    cog = MessageMilestoneCog(bot)
    monkeypatch.setattr(
        "src.cogs.message_milestone.award_message_combo_xp",
        AsyncMock(side_effect=RuntimeError("temporary failure")),
    )

    async with session_factory() as session:
        delivery = await enqueue_message_combo_delivery(
            session,
            config_id=1,
            guild_id="10",
            channel_id="20",
            user_id="30",
            message_id="400",
            streak_days=2,
            observed_at=datetime(2026, 8, 7, tzinfo=UTC),
        )
        assert delivery is not None
        await cog._deliver_combo_delivery(session, delivery)

        channel.send.assert_not_awaited()
        assert delivery.xp_delivered_at is None
        assert delivery.notification_delivered_at is None
