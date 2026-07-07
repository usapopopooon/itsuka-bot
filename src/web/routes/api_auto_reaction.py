"""API v1 auto reaction routes (JSON)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import src.web.db_helpers as _db
import src.web.security as _security
from src.database.models import AutoReactionConfig
from src.services.auto_reaction_service import (
    MAX_AUTO_REACTION_EMOJIS,
    decode_auto_reaction_emojis,
    decode_auto_reaction_user_ids,
    encode_auto_reaction_emojis,
    encode_auto_reaction_user_ids,
    normalize_auto_reaction_emojis,
    normalize_auto_reaction_user_ids,
    validate_pattern,
)
from src.web.jwt_auth import get_current_user_jwt

router = APIRouter(prefix="/api/v1", tags=["api-auto-reaction"])


def _serialize(config: AutoReactionConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "guild_id": config.guild_id,
        "channel_id": config.channel_id,
        "emojis": decode_auto_reaction_emojis(config.emojis),
        "excluded_user_ids": decode_auto_reaction_user_ids(config.excluded_user_ids),
        "pattern": config.pattern,
        "enabled": config.enabled,
    }


class _AutoReactionCreateRequest(BaseModel):
    guild_id: str
    channel_id: str
    emojis: list[str]
    excluded_user_ids: list[str] | None = None
    pattern: str | None = None


class _AutoReactionUpdateRequest(BaseModel):
    emojis: list[str]
    excluded_user_ids: list[str] | None = None
    pattern: str | None = None


@router.get("/auto-reaction", response_model=None)
async def api_auto_reaction_list(
    user: dict[str, Any] | None = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(_db.get_db),
) -> JSONResponse:
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    result = await db.execute(
        select(AutoReactionConfig).order_by(AutoReactionConfig.id)
    )
    configs = list(result.scalars().all())

    guilds_map, channels_map = await _db._get_discord_guilds_and_channels(db)
    emojis_map = await _db._get_discord_emojis_by_guild(db)

    return JSONResponse(
        {
            "configs": [_serialize(c) for c in configs],
            "guilds": guilds_map,
            "channels": {
                gid: [{"id": cid, "name": cname} for cid, cname in clist]
                for gid, clist in channels_map.items()
            },
            "custom_emojis": emojis_map,
        }
    )


@router.post("/auto-reaction", response_model=None)
async def api_auto_reaction_create(
    request: Request,
    body: _AutoReactionCreateRequest,
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
            {"detail": "guild_id and channel_id are required"}, status_code=422
        )

    emojis = normalize_auto_reaction_emojis(body.emojis)
    if not emojis:
        return JSONResponse(
            {"detail": "At least one emoji is required"}, status_code=422
        )
    if len(emojis) > MAX_AUTO_REACTION_EMOJIS:
        return JSONResponse(
            {"detail": f"At most {MAX_AUTO_REACTION_EMOJIS} emojis are allowed"},
            status_code=422,
        )

    try:
        pattern = validate_pattern(body.pattern)
    except re.error as e:
        return JSONResponse({"detail": f"Invalid regex pattern: {e}"}, status_code=422)
    try:
        excluded_user_ids = normalize_auto_reaction_user_ids(
            body.excluded_user_ids or []
        )
    except ValueError as e:
        return JSONResponse(
            {"detail": f"Invalid excluded user ID: {e}"}, status_code=422
        )

    config = AutoReactionConfig(
        guild_id=body.guild_id,
        channel_id=body.channel_id,
        emojis=encode_auto_reaction_emojis(emojis),
        excluded_user_ids=encode_auto_reaction_user_ids(excluded_user_ids),
        pattern=pattern,
    )
    db.add(config)
    await db.commit()

    _security.record_form_submit(user_id, path)
    await db.refresh(config)
    return JSONResponse({"ok": True, "config": _serialize(config)}, status_code=201)


@router.delete("/auto-reaction/{config_id}", response_model=None)
async def api_auto_reaction_delete(
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
        select(AutoReactionConfig).where(AutoReactionConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        return JSONResponse({"detail": "Not found"}, status_code=404)

    await db.delete(config)
    await db.commit()
    _security.record_form_submit(user_id, path)
    return JSONResponse({"ok": True})


@router.patch("/auto-reaction/{config_id}", response_model=None)
async def api_auto_reaction_update(
    request: Request,
    config_id: int,
    body: _AutoReactionUpdateRequest,
    user: dict[str, Any] | None = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(_db.get_db),
) -> JSONResponse:
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    user_id = user.get("sub", "")
    path = request.url.path

    if _security.is_form_cooldown_active(user_id, path):
        return JSONResponse({"detail": "Too many requests"}, status_code=429)

    emojis = normalize_auto_reaction_emojis(body.emojis)
    if not emojis:
        return JSONResponse(
            {"detail": "At least one emoji is required"}, status_code=422
        )
    if len(emojis) > MAX_AUTO_REACTION_EMOJIS:
        return JSONResponse(
            {"detail": f"At most {MAX_AUTO_REACTION_EMOJIS} emojis are allowed"},
            status_code=422,
        )

    try:
        pattern = validate_pattern(body.pattern)
    except re.error as e:
        return JSONResponse({"detail": f"Invalid regex pattern: {e}"}, status_code=422)
    try:
        excluded_user_ids = (
            normalize_auto_reaction_user_ids(body.excluded_user_ids)
            if body.excluded_user_ids is not None
            else None
        )
    except ValueError as e:
        return JSONResponse(
            {"detail": f"Invalid excluded user ID: {e}"}, status_code=422
        )

    result = await db.execute(
        select(AutoReactionConfig).where(AutoReactionConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        return JSONResponse({"detail": "Not found"}, status_code=404)

    config.emojis = encode_auto_reaction_emojis(emojis)
    if excluded_user_ids is not None:
        config.excluded_user_ids = encode_auto_reaction_user_ids(excluded_user_ids)
    config.pattern = pattern
    await db.commit()
    _security.record_form_submit(user_id, path)
    await db.refresh(config)
    return JSONResponse({"ok": True, "config": _serialize(config)})


@router.patch("/auto-reaction/{config_id}/toggle", response_model=None)
async def api_auto_reaction_toggle(
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
        select(AutoReactionConfig).where(AutoReactionConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        return JSONResponse({"detail": "Not found"}, status_code=404)

    config.enabled = not config.enabled
    await db.commit()
    _security.record_form_submit(user_id, path)
    return JSONResponse({"ok": True, "enabled": config.enabled})
