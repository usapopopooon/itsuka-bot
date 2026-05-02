"""API v1 authentication routes (JWT-based)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import src.web.security as _security
from src.constants import SESSION_MAX_AGE_SECONDS
from src.web.jwt_auth import create_jwt_token, get_current_user_jwt

router = APIRouter(prefix="/api/v1/auth", tags=["api-auth"])


class _LoginRequest(BaseModel):
    user: str
    password: str


@router.post("/login", response_model=None)
async def api_login(body: _LoginRequest, request: Request) -> JSONResponse:
    """JSON で送られた資格情報を検証し、JWT クッキーを発行する。"""
    client_ip = request.client.host if request.client else "unknown"

    user = body.user.strip() if body.user else ""
    password = body.password

    if _security.is_rate_limited(client_ip):
        return JSONResponse(
            {"detail": "Too many attempts. Try again later."},
            status_code=429,
        )

    if not _security.verify_admin_credentials(user, password):
        _security.record_failed_attempt(client_ip)
        return JSONResponse({"detail": "Invalid user or password"}, status_code=401)

    token = create_jwt_token(user)
    response = JSONResponse({"ok": True})
    response.set_cookie(
        key="session",
        value=token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=_security.SECURE_COOKIE,
        samesite="strict",
        path="/",
    )
    return response


@router.post("/logout", response_model=None)
async def api_logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    response.delete_cookie(key="session", path="/")
    return response


@router.get("/me", response_model=None)
async def api_me(
    user: dict[str, Any] | None = Depends(get_current_user_jwt),
) -> JSONResponse:
    if not user or not user.get("sub"):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return JSONResponse({"user": user["sub"]})
