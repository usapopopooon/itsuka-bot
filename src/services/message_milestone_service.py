"""Message milestone の DB 操作と達成判定。"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    MessageMilestoneConfig,
    MessageMilestoneProcessedMessage,
    MessageMilestoneProgress,
)

__all__ = [
    "MAX_MILESTONE_MESSAGE_LENGTH",
    "MAX_MILESTONE_TEXT_LENGTH",
    "MAX_MILESTONE_DELETE_AFTER_SECONDS",
    "MAX_MILESTONE_PATTERN_LENGTH",
    "ChannelMessageMilestone",
    "compile_pattern",
    "delete_message_milestone_state",
    "MilestoneProgressResult",
    "MilestoneTemplateContext",
    "get_enabled_message_milestones",
    "is_message_milestone_message_processed",
    "normalize_embed_color",
    "normalize_milestone_text",
    "mark_message_milestone_reward_sent",
    "mark_message_milestone_backfill_completed",
    "mark_message_milestone_message_processed",
    "message_milestone_date",
    "record_message_and_get_reward",
    "render_milestone_template",
    "validate_pattern",
]

MAX_MILESTONE_TEXT_LENGTH = 4096
MAX_MILESTONE_MESSAGE_LENGTH = 2000
MAX_MILESTONE_DELETE_AFTER_SECONDS = 300
MAX_MILESTONE_PATTERN_LENGTH = 500
_TOKYO = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class ChannelMessageMilestone:
    id: int
    channel_id: str
    daily_required_count: int
    required_days: int
    pattern: re.Pattern[str] | None
    response_type: str
    message_content: str | None
    embed_title: str | None
    embed_description: str | None
    embed_color: int | None
    delete_after_seconds: int | None
    backfill_completed: bool


@dataclass(frozen=True)
class MilestoneProgressResult:
    should_send: bool
    streak_days: int
    daily_count: int
    duplicate: bool = False
    crossed_daily_goal: bool = False
    reward_pending: bool = False


@dataclass(frozen=True)
class MilestoneTemplateContext:
    username: str
    daily_required_count: int


_TemplateValueFactory = Callable[[MilestoneTemplateContext], str]

_TEMPLATE_VARIABLES: dict[str, _TemplateValueFactory] = {
    "username": lambda context: context.username,
    "n": lambda context: str(context.daily_required_count),
    "count": lambda context: str(context.daily_required_count),
}


def render_milestone_template(
    template: str | None, context: MilestoneTemplateContext
) -> str | None:
    """MessageMilestone の送信テンプレートを展開する。

    未知の ``{variable}`` はそのまま残す。変数を追加する場合は
    ``_TEMPLATE_VARIABLES`` に factory を足すだけでよい。
    """
    if template is None:
        return None
    rendered = template
    for name, factory in _TEMPLATE_VARIABLES.items():
        rendered = rendered.replace(f"{{{name}}}", factory(context))
    return rendered


def normalize_milestone_text(raw: str | None, *, max_length: int) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if len(value) > max_length:
        raise ValueError(f"text too long (max {max_length} chars)")
    return value


def validate_pattern(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if len(value) > MAX_MILESTONE_PATTERN_LENGTH:
        raise re.error(f"pattern too long (max {MAX_MILESTONE_PATTERN_LENGTH} chars)")
    re.compile(value)
    return value


def compile_pattern(raw: str | None) -> re.Pattern[str] | None:
    if not raw:
        return None
    try:
        return re.compile(raw)
    except re.error:
        return None


def normalize_embed_color(raw: str | None) -> int | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if value.startswith("#"):
        value = value[1:]
    if len(value) != 6:
        raise ValueError("color must be a 6-digit hex value")
    try:
        color = int(value, 16)
    except ValueError as exc:
        raise ValueError("color must be a 6-digit hex value") from exc
    if not 0 <= color <= 0xFFFFFF:
        raise ValueError("color must be between #000000 and #FFFFFF")
    return color


def message_milestone_date(created_at: datetime | None) -> date:
    source = created_at or datetime.now(UTC)
    if source.tzinfo is None:
        source = source.replace(tzinfo=UTC)
    return source.astimezone(_TOKYO).date()


async def get_enabled_message_milestones(
    session: AsyncSession,
) -> dict[str, list[ChannelMessageMilestone]]:
    stmt = (
        select(MessageMilestoneConfig)
        .where(MessageMilestoneConfig.enabled.is_(True))
        .order_by(MessageMilestoneConfig.id)
    )
    result = await session.execute(stmt)
    grouped: dict[str, list[ChannelMessageMilestone]] = {}
    for config in result.scalars():
        grouped.setdefault(config.channel_id, []).append(
            ChannelMessageMilestone(
                id=config.id,
                channel_id=config.channel_id,
                daily_required_count=config.daily_required_count,
                required_days=config.required_days,
                pattern=compile_pattern(config.pattern),
                response_type=config.response_type,
                message_content=config.message_content,
                embed_title=config.embed_title,
                embed_description=config.embed_description,
                embed_color=config.embed_color,
                delete_after_seconds=config.delete_after_seconds,
                backfill_completed=config.backfill_completed,
            )
        )
    return grouped


async def is_message_milestone_message_processed(
    session: AsyncSession, *, config_id: int, message_id: str
) -> bool:
    result = await session.execute(
        select(MessageMilestoneProcessedMessage.id).where(
            MessageMilestoneProcessedMessage.config_id == config_id,
            MessageMilestoneProcessedMessage.message_id == message_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def mark_message_milestone_message_processed(
    session: AsyncSession, *, config_id: int, message_id: str
) -> bool:
    if await is_message_milestone_message_processed(
        session, config_id=config_id, message_id=message_id
    ):
        return False
    session.add(
        MessageMilestoneProcessedMessage(config_id=config_id, message_id=message_id)
    )
    await session.flush()
    return True


async def record_message_and_get_reward(
    session: AsyncSession,
    *,
    config: ChannelMessageMilestone,
    user_id: str,
    created_at: datetime | None,
    message_id: str | None = None,
) -> MilestoneProgressResult:
    if message_id is not None:
        was_new = await mark_message_milestone_message_processed(
            session, config_id=config.id, message_id=message_id
        )
        if not was_new:
            await session.commit()
            return MilestoneProgressResult(
                should_send=False,
                streak_days=0,
                daily_count=0,
                duplicate=True,
            )

    today = message_milestone_date(created_at)
    yesterday = today - timedelta(days=1)

    result = await session.execute(
        select(MessageMilestoneProgress).where(
            MessageMilestoneProgress.config_id == config.id,
            MessageMilestoneProgress.user_id == user_id,
        )
    )
    progress = result.scalar_one_or_none()
    if progress is None:
        progress = MessageMilestoneProgress(
            config_id=config.id,
            user_id=user_id,
            last_counted_date=today,
            daily_count=0,
            streak_days=0,
            reward_pending=False,
            reward_sent=False,
        )
        session.add(progress)

    if progress.last_counted_date == today:
        previous_count = progress.daily_count
    else:
        continues = (
            progress.last_counted_date == yesterday
            and progress.daily_count >= config.daily_required_count
        )
        progress.streak_days = progress.streak_days if continues else 0
        progress.reward_pending = progress.reward_pending if continues else False
        progress.reward_sent = progress.reward_sent if continues else False
        progress.last_counted_date = today
        progress.daily_count = 0
        previous_count = 0

    progress.daily_count += 1
    crossed_daily_goal = (
        previous_count < config.daily_required_count
        and progress.daily_count >= config.daily_required_count
    )
    if crossed_daily_goal:
        progress.streak_days += 1

    if (
        crossed_daily_goal
        and progress.streak_days >= config.required_days
        and not progress.reward_sent
    ):
        progress.reward_pending = True

    should_send = progress.reward_pending and not progress.reward_sent

    await session.commit()
    return MilestoneProgressResult(
        should_send=should_send,
        streak_days=progress.streak_days,
        daily_count=progress.daily_count,
        crossed_daily_goal=crossed_daily_goal,
        reward_pending=progress.reward_pending,
    )


async def mark_message_milestone_backfill_completed(
    session: AsyncSession, *, config_id: int
) -> None:
    result = await session.execute(
        select(MessageMilestoneConfig).where(MessageMilestoneConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        return
    config.backfill_completed = True
    await session.commit()


async def delete_message_milestone_state(
    session: AsyncSession, *, config_id: int
) -> None:
    """設定変更/削除時に達成状況と処理済みメッセージをまとめて消す。"""
    await session.execute(
        delete(MessageMilestoneProgress).where(
            MessageMilestoneProgress.config_id == config_id
        )
    )
    await session.execute(
        delete(MessageMilestoneProcessedMessage).where(
            MessageMilestoneProcessedMessage.config_id == config_id
        )
    )


async def mark_message_milestone_reward_sent(
    session: AsyncSession, *, config_id: int, user_id: str
) -> None:
    result = await session.execute(
        select(MessageMilestoneProgress).where(
            MessageMilestoneProgress.config_id == config_id,
            MessageMilestoneProgress.user_id == user_id,
        )
    )
    progress = result.scalar_one_or_none()
    if progress is None:
        return
    progress.reward_pending = False
    progress.reward_sent = True
    await session.commit()
