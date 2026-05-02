"""api_auth ルートを ASGI 経由でテストする。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.web.app import app


@pytest.mark.asyncio
async def test_login_invalid_credentials_returns_401() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/auth/login",
            json={"user": "admin", "password": "WRONG"},
        )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_login_success_sets_cookie_and_me_returns_user() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/auth/login",
            json={"user": "admin", "password": "test_password"},
        )
        assert res.status_code == 200, res.text
        # session クッキーが付与されていること
        assert "session" in res.cookies

        me = await ac.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json() == {"user": "admin"}


@pytest.mark.asyncio
async def test_me_without_cookie_returns_401() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/auth/me")
    assert res.status_code == 401
