"""セキュリティユーティリティ。

責務:
    - ``SecurityHeadersMiddleware``: レスポンスヘッダ追加
    - ``SECRET_KEY``: JWT 署名鍵 (環境変数 SESSION_SECRET_KEY または乱数)
    - パスワード照合 (bcrypt) ※将来の AdminUser DB 化に備える
    - ログインのレート制限とフォーム連投クールタイム
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import secrets
import time
from typing import Any

import bcrypt
from fastapi import Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.config import settings
from src.constants import (
    BCRYPT_MAX_PASSWORD_BYTES,
    FORM_COOLDOWN_CLEANUP_INTERVAL_SECONDS,
    FORM_SUBMIT_COOLDOWN_SECONDS,
    LOGIN_MAX_ATTEMPTS,
    LOGIN_WINDOW_SECONDS,
    RATE_LIMIT_CLEANUP_INTERVAL_SECONDS,
    TOKEN_BYTE_LENGTH,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# セキュリティヘッダミドルウェア
# ---------------------------------------------------------------------------

_CSP_HEADER = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self' https:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = _CSP_HEADER
        if request.url.path not in ("/health", "/favicon.ico"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


# ---------------------------------------------------------------------------
# モジュールレベル設定
# ---------------------------------------------------------------------------

_session_secret_from_env = os.environ.get("SESSION_SECRET_KEY", "").strip()
if not _session_secret_from_env:
    logger.warning(
        "SESSION_SECRET_KEY is not set. Using a random key. "
        "Sessions will be invalidated on restart."
    )
    SECRET_KEY: str = secrets.token_hex(TOKEN_BYTE_LENGTH)
else:
    SECRET_KEY = _session_secret_from_env

ADMIN_USER: str = (settings.admin_user or "admin").strip()
ADMIN_PASSWORD: str = settings.admin_password
SECURE_COOKIE: bool = os.environ.get("SECURE_COOKIE", "false").lower() == "true"


# ---------------------------------------------------------------------------
# 単一管理者の認証
# ---------------------------------------------------------------------------


def verify_admin_credentials(user: str, password: str) -> bool:
    """環境変数の単一管理者と入力を定数時間比較する。"""
    if not ADMIN_USER or not ADMIN_PASSWORD:
        return False
    user_ok = hmac.compare_digest(user, ADMIN_USER)
    pw_ok = hmac.compare_digest(password, ADMIN_PASSWORD)
    return user_ok and pw_ok


# ---------------------------------------------------------------------------
# bcrypt (将来 AdminUser を DB 化するときのため温存)
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > BCRYPT_MAX_PASSWORD_BYTES:
        logger.warning(
            "Password exceeds %d bytes, truncating", BCRYPT_MAX_PASSWORD_BYTES
        )
        password_bytes = password_bytes[:BCRYPT_MAX_PASSWORD_BYTES]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    return await asyncio.to_thread(verify_password, password, password_hash)


# ---------------------------------------------------------------------------
# レート制限
# ---------------------------------------------------------------------------

LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_last_cleanup_time: float = 0.0


def _cleanup_old_rate_limit_entries() -> None:
    global _last_cleanup_time
    now = time.time()
    if (
        _last_cleanup_time > 0
        and now - _last_cleanup_time < RATE_LIMIT_CLEANUP_INTERVAL_SECONDS
    ):
        return
    _last_cleanup_time = now
    for ip in list(LOGIN_ATTEMPTS):
        valid = [t for t in LOGIN_ATTEMPTS[ip] if now - t < LOGIN_WINDOW_SECONDS]
        if valid:
            LOGIN_ATTEMPTS[ip] = valid
        else:
            del LOGIN_ATTEMPTS[ip]


def is_rate_limited(ip: str) -> bool:
    _cleanup_old_rate_limit_entries()
    attempts = LOGIN_ATTEMPTS.get(ip)
    if not attempts:
        return False
    now = time.time()
    valid = [t for t in attempts if now - t < LOGIN_WINDOW_SECONDS]
    if len(valid) != len(attempts):
        if valid:
            LOGIN_ATTEMPTS[ip] = valid
        else:
            del LOGIN_ATTEMPTS[ip]
    return len(valid) >= LOGIN_MAX_ATTEMPTS


def record_failed_attempt(ip: str) -> None:
    if not ip:
        return
    LOGIN_ATTEMPTS.setdefault(ip, []).append(time.time())


# ---------------------------------------------------------------------------
# フォーム送信クールタイム
# ---------------------------------------------------------------------------

FORM_SUBMIT_TIMES: dict[str, float] = {}
_form_cooldown_last_cleanup_time: float = 0.0


def _cleanup_form_cooldown_entries() -> None:
    global _form_cooldown_last_cleanup_time
    now = time.time()
    if (
        _form_cooldown_last_cleanup_time > 0
        and now - _form_cooldown_last_cleanup_time
        < FORM_COOLDOWN_CLEANUP_INTERVAL_SECONDS
    ):
        return
    _form_cooldown_last_cleanup_time = now
    threshold = FORM_SUBMIT_COOLDOWN_SECONDS * 5
    for key in list(FORM_SUBMIT_TIMES):
        if now - FORM_SUBMIT_TIMES[key] > threshold:
            del FORM_SUBMIT_TIMES[key]


def is_form_cooldown_active(user: str, path: str) -> bool:
    _cleanup_form_cooldown_entries()
    key = f"{user}:{path}"
    last = FORM_SUBMIT_TIMES.get(key)
    if last is None:
        return False
    return time.time() - last < FORM_SUBMIT_COOLDOWN_SECONDS


def record_form_submit(user: str, path: str) -> None:
    if not user:
        return
    FORM_SUBMIT_TIMES[f"{user}:{path}"] = time.time()
