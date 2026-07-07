"""AutoReaction API routes."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

import src.web.security as _security
from src.database.engine import async_session, init_db
from src.database.models import AutoReactionConfig
from src.web.app import app


async def _reset_auto_reaction_configs() -> None:
    await init_db()
    async with async_session() as session:
        await session.execute(delete(AutoReactionConfig))
        await session.commit()
    _security.FORM_SUBMIT_TIMES.clear()


async def _login(ac: AsyncClient) -> None:
    res = await ac.post(
        "/api/v1/auth/login",
        json={"user": "admin", "password": "test_password"},
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_auto_reaction_create_serializes_excluded_user_ids() -> None:
    await _reset_auto_reaction_configs()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _login(ac)
        res = await ac.post(
            "/api/v1/auto-reaction",
            json={
                "guild_id": "g1",
                "channel_id": "c1",
                "emojis": ["👍"],
                "excluded_user_ids": ["111, <@222> 111"],
                "pattern": "hello",
            },
        )
        assert res.status_code == 201, res.text
        assert res.json()["config"]["excluded_user_ids"] == ["111", "222"]

        listed = await ac.get("/api/v1/auto-reaction")
        assert listed.status_code == 200, listed.text
        assert listed.json()["configs"][0]["excluded_user_ids"] == ["111", "222"]


@pytest.mark.asyncio
async def test_auto_reaction_update_replaces_excluded_user_ids() -> None:
    await _reset_auto_reaction_configs()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _login(ac)
        created = await ac.post(
            "/api/v1/auto-reaction",
            json={
                "guild_id": "g1",
                "channel_id": "c1",
                "emojis": ["👍"],
                "excluded_user_ids": ["111"],
            },
        )
        config_id = created.json()["config"]["id"]

        updated = await ac.patch(
            f"/api/v1/auto-reaction/{config_id}",
            json={
                "emojis": ["❤️"],
                "excluded_user_ids": ["333 <@!444>"],
                "pattern": None,
            },
        )

        assert updated.status_code == 200, updated.text
        body = updated.json()["config"]
        assert body["emojis"] == ["❤️"]
        assert body["excluded_user_ids"] == ["333", "444"]


@pytest.mark.asyncio
async def test_auto_reaction_create_rejects_invalid_excluded_user_id() -> None:
    await _reset_auto_reaction_configs()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _login(ac)
        res = await ac.post(
            "/api/v1/auto-reaction",
            json={
                "guild_id": "g1",
                "channel_id": "c1",
                "emojis": ["👍"],
                "excluded_user_ids": ["not-a-user-id"],
            },
        )

    assert res.status_code == 422
    assert "Invalid excluded user ID" in res.json()["detail"]
