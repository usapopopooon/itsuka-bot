"""API v1 message milestone routes (JSON)."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import src.web.db_helpers as _db
import src.web.security as _security
from src.database.models import MessageMilestoneConfig
from src.services.message_milestone_service import (
    MAX_MILESTONE_DELETE_AFTER_SECONDS,
    MAX_MILESTONE_MESSAGE_LENGTH,
    MAX_MILESTONE_TEXT_LENGTH,
    delete_message_milestone_state,
    normalize_embed_color,
    normalize_milestone_text,
    validate_pattern,
)
from src.web.jwt_auth import get_current_user_jwt

router = APIRouter(prefix="/api/v1", tags=["api-message-milestone"])
logger = logging.getLogger(__name__)


def _serialize(config: MessageMilestoneConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "guild_id": config.guild_id,
        "channel_id": config.channel_id,
        "condition_type": config.condition_type,
        "daily_required_count": config.daily_required_count,
        "required_days": config.required_days,
        "pattern": config.pattern,
        "response_type": config.response_type,
        "message_content": config.message_content,
        "embed_title": config.embed_title,
        "embed_description": config.embed_description,
        "embed_color": f"#{config.embed_color:06X}"
        if config.embed_color is not None
        else None,
        "delete_after_seconds": config.delete_after_seconds,
        "backfill_completed": config.backfill_completed,
        "enabled": config.enabled,
    }


class _MessageMilestoneRequest(BaseModel):
    guild_id: str | None = None
    channel_id: str | None = None
    condition_type: str = "daily_streak"
    daily_required_count: int
    required_days: int
    pattern: str | None = None
    response_type: str
    message_content: str | None = None
    embed_title: str | None = None
    embed_description: str | None = None
    embed_color: str | None = None
    delete_after_seconds: int | None = None


async def _normalize_body(
    body: _MessageMilestoneRequest,
) -> tuple[dict[str, Any], str | None]:
    if body.condition_type not in {"daily_streak", "consecutive_posts"}:
        return {}, "達成条件を選択してください"
    if body.daily_required_count < 1 or body.daily_required_count > 999:
        return {}, "投稿数は 1〜999 で指定してください"
    if body.condition_type == "daily_streak" and (
        body.required_days < 1 or body.required_days > 365
    ):
        return {}, "継続日数は 1〜365 で指定してください"
    if body.response_type not in {"plain", "embed"}:
        return {}, "送信形式は通常メッセージまたは埋め込みを選んでください"
    if body.delete_after_seconds is not None and (
        body.delete_after_seconds < 1
        or body.delete_after_seconds > MAX_MILESTONE_DELETE_AFTER_SECONDS
    ):
        return (
            {},
            f"自動削除は 1〜{MAX_MILESTONE_DELETE_AFTER_SECONDS} 秒で指定してください",
        )

    try:
        content_max = (
            MAX_MILESTONE_MESSAGE_LENGTH - 40
            if body.delete_after_seconds is not None
            else MAX_MILESTONE_MESSAGE_LENGTH
        )
        message_content = normalize_milestone_text(
            body.message_content, max_length=content_max
        )
        embed_title = normalize_milestone_text(body.embed_title, max_length=256)
        embed_description = normalize_milestone_text(
            body.embed_description, max_length=MAX_MILESTONE_TEXT_LENGTH
        )
        embed_color = normalize_embed_color(body.embed_color)
        pattern = validate_pattern(body.pattern)
    except re.error as exc:
        return {}, f"正規表現フィルタが不正です: {exc}"
    except ValueError as exc:
        return {}, str(exc)

    if body.response_type == "plain" and not message_content:
        return {}, "通常メッセージの本文を入力してください"
    if body.response_type == "embed" and not (embed_title or embed_description):
        return {}, "埋め込みはタイトルか説明のどちらかを入力してください"

    return {
        "condition_type": body.condition_type,
        "daily_required_count": body.daily_required_count,
        "required_days": body.required_days
        if body.condition_type == "daily_streak"
        else 1,
        "pattern": pattern,
        "response_type": body.response_type,
        "message_content": message_content,
        "embed_title": embed_title,
        "embed_description": embed_description,
        "embed_color": embed_color,
        "delete_after_seconds": body.delete_after_seconds,
    }, None


@router.get("/message-milestone", response_model=None)
async def api_message_milestone_list(
    user: dict[str, Any] | None = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(_db.get_db),
) -> JSONResponse:
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    result = await db.execute(
        select(MessageMilestoneConfig).order_by(MessageMilestoneConfig.id)
    )
    configs = list(result.scalars().all())
    guilds_map, channels_map = await _db._get_discord_guilds_and_channels(db)
    logger.info(
        "MessageMilestone API: list requested by user=%s configs=%s",
        user.get("sub", ""),
        [
            {
                "id": config.id,
                "guild_id": config.guild_id,
                "channel_id": config.channel_id,
                "condition_type": config.condition_type,
                "enabled": config.enabled,
                "pattern": config.pattern,
                "backfill_completed": config.backfill_completed,
            }
            for config in configs
        ],
    )

    return JSONResponse(
        {
            "configs": [_serialize(c) for c in configs],
            "guilds": guilds_map,
            "channels": {
                gid: [{"id": cid, "name": cname} for cid, cname in clist]
                for gid, clist in channels_map.items()
            },
        }
    )


@router.post("/message-milestone", response_model=None)
async def api_message_milestone_create(
    request: Request,
    body: _MessageMilestoneRequest,
    user: dict[str, Any] | None = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(_db.get_db),
) -> JSONResponse:
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    user_id = user.get("sub", "")
    path = request.url.path
    if _security.is_form_cooldown_active(user_id, path):
        return JSONResponse({"detail": "Too many requests"}, status_code=429)
    if not body.guild_id or not body.channel_id:
        return JSONResponse(
            {"detail": "サーバーとチャンネルを選択してください"}, status_code=422
        )

    values, error = await _normalize_body(body)
    if error:
        logger.info(
            "MessageMilestone API: create rejected user=%s guild=%s channel=%s "
            "error=%s",
            user_id,
            body.guild_id,
            body.channel_id,
            error,
        )
        return JSONResponse({"detail": error}, status_code=422)

    config = MessageMilestoneConfig(
        guild_id=body.guild_id,
        channel_id=body.channel_id,
        **values,
    )
    config.backfill_completed = values["condition_type"] == "consecutive_posts"
    db.add(config)
    await db.commit()
    _security.record_form_submit(user_id, path)
    await db.refresh(config)
    logger.info(
        "MessageMilestone API: created config=%s user=%s guild=%s channel=%s "
        "condition=%s required=%s days=%s pattern=%r response_type=%s "
        "delete_after=%s",
        config.id,
        user_id,
        config.guild_id,
        config.channel_id,
        config.condition_type,
        config.daily_required_count,
        config.required_days,
        config.pattern,
        config.response_type,
        config.delete_after_seconds,
    )
    return JSONResponse({"ok": True, "config": _serialize(config)}, status_code=201)


@router.patch("/message-milestone/{config_id}", response_model=None)
async def api_message_milestone_update(
    request: Request,
    config_id: int,
    body: _MessageMilestoneRequest,
    user: dict[str, Any] | None = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(_db.get_db),
) -> JSONResponse:
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    user_id = user.get("sub", "")
    path = request.url.path
    if _security.is_form_cooldown_active(user_id, path):
        return JSONResponse({"detail": "Too many requests"}, status_code=429)

    result = await db.execute(
        select(MessageMilestoneConfig).where(MessageMilestoneConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        return JSONResponse({"detail": "Not found"}, status_code=404)

    values, error = await _normalize_body(body)
    if error:
        logger.info(
            "MessageMilestone API: update rejected config=%s user=%s error=%s",
            config_id,
            user_id,
            error,
        )
        return JSONResponse({"detail": error}, status_code=422)

    await delete_message_milestone_state(db, config_id=config_id)
    logger.info(
        "MessageMilestone API: reset progress/processed state for config=%s "
        "before update",
        config_id,
    )
    for key, value in values.items():
        setattr(config, key, value)
    config.backfill_completed = values["condition_type"] == "consecutive_posts"
    await db.commit()
    _security.record_form_submit(user_id, path)
    await db.refresh(config)
    logger.info(
        "MessageMilestone API: updated config=%s user=%s guild=%s channel=%s "
        "condition=%s required=%s days=%s pattern=%r response_type=%s "
        "delete_after=%s backfill_completed=%s",
        config.id,
        user_id,
        config.guild_id,
        config.channel_id,
        config.condition_type,
        config.daily_required_count,
        config.required_days,
        config.pattern,
        config.response_type,
        config.delete_after_seconds,
        config.backfill_completed,
    )
    return JSONResponse({"ok": True, "config": _serialize(config)})


@router.patch("/message-milestone/{config_id}/toggle", response_model=None)
async def api_message_milestone_toggle(
    request: Request,
    config_id: int,
    user: dict[str, Any] | None = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(_db.get_db),
) -> JSONResponse:
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    user_id = user.get("sub", "")
    path = request.url.path
    if _security.is_form_cooldown_active(user_id, path):
        return JSONResponse({"detail": "Too many requests"}, status_code=429)

    result = await db.execute(
        select(MessageMilestoneConfig).where(MessageMilestoneConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        return JSONResponse({"detail": "Not found"}, status_code=404)

    config.enabled = not config.enabled
    await db.commit()
    _security.record_form_submit(user_id, path)
    logger.info(
        "MessageMilestone API: toggled config=%s user=%s enabled=%s",
        config.id,
        user_id,
        config.enabled,
    )
    return JSONResponse({"ok": True, "enabled": config.enabled})


@router.delete("/message-milestone/{config_id}", response_model=None)
async def api_message_milestone_delete(
    request: Request,
    config_id: int,
    user: dict[str, Any] | None = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(_db.get_db),
) -> JSONResponse:
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    user_id = user.get("sub", "")
    path = request.url.path
    if _security.is_form_cooldown_active(user_id, path):
        return JSONResponse({"detail": "Too many requests"}, status_code=429)

    result = await db.execute(
        select(MessageMilestoneConfig).where(MessageMilestoneConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        return JSONResponse({"detail": "Not found"}, status_code=404)

    await delete_message_milestone_state(db, config_id=config_id)
    await db.delete(config)
    await db.commit()
    _security.record_form_submit(user_id, path)
    logger.info(
        "MessageMilestone API: deleted config=%s user=%s",
        config_id,
        user_id,
    )
    return JSONResponse({"ok": True})
