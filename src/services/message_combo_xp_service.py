"""投稿の日数コンボXPを確実に配送するためのoutbox操作。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MessageComboXpDelivery

MESSAGE_COMBO_XP_REWARDS: dict[int, int] = {
    2: 20,
    3: 50,
    5: 100,
    10: 250,
    20: 500,
}


async def enqueue_message_combo_delivery(
    session: AsyncSession,
    *,
    config_id: int,
    guild_id: str,
    channel_id: str,
    user_id: str,
    message_id: str,
    streak_days: int,
    observed_at: datetime,
) -> MessageComboXpDelivery | None:
    """案内またはXP対象日だけを、メッセージ単位で冪等に登録する。"""
    if streak_days != 1 and streak_days not in MESSAGE_COMBO_XP_REWARDS:
        return None
    event_id = f"itsuka:{config_id}:{message_id}"
    existing = (
        await session.execute(
            select(MessageComboXpDelivery).where(
                MessageComboXpDelivery.event_id == event_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    delivery = MessageComboXpDelivery(
        event_id=event_id,
        config_id=config_id,
        guild_id=guild_id,
        channel_id=channel_id,
        user_id=user_id,
        streak_days=streak_days,
        observed_at=observed_at,
        # 1日目は案内のみで、level-botへの配送は不要。
        xp_delivered_at=datetime.now(UTC) if streak_days == 1 else None,
    )
    session.add(delivery)
    await session.commit()
    return delivery


async def get_pending_message_combo_deliveries(
    session: AsyncSession, *, limit: int = 100
) -> list[MessageComboXpDelivery]:
    result = await session.execute(
        select(MessageComboXpDelivery)
        .where(
            (MessageComboXpDelivery.xp_delivered_at.is_(None))
            | (MessageComboXpDelivery.notification_delivered_at.is_(None))
        )
        .order_by(MessageComboXpDelivery.id)
        .limit(limit)
    )
    return list(result.scalars())


async def mark_message_combo_xp_delivered(
    session: AsyncSession, delivery: MessageComboXpDelivery
) -> None:
    delivery.xp_delivered_at = datetime.now(UTC)
    await session.commit()


async def mark_message_combo_notification_delivered(
    session: AsyncSession, delivery: MessageComboXpDelivery
) -> None:
    delivery.notification_delivered_at = datetime.now(UTC)
    await session.commit()
