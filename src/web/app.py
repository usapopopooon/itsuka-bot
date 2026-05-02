"""FastAPI web admin application.

リファレンスの ``src/web/app.py`` と同じ thin facade パターン。
ミドルウェア / ルータ登録のみを行い、実装は各サブモジュールに委譲する。
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import require_web_settings, settings
from src.database.engine import init_db

# 起動時に SESSION_SECRET / ADMIN_PASSWORD の存在を検証する。
# ここで例外を投げれば uvicorn のワーカ起動時点で気づける。
require_web_settings()

from src.web.routes.api_auth import router as api_auth_router  # noqa: E402
from src.web.routes.api_auto_reaction import (  # noqa: E402
    router as api_auto_reaction_router,
)
from src.web.security import SecurityHeadersMiddleware  # noqa: E402

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting web admin application...")
    await init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down web admin application...")


app = FastAPI(
    title="Itsuka Bot Admin",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(SecurityHeadersMiddleware)

_cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_auth_router)
app.include_router(api_auto_reaction_router)


def run() -> None:
    """`python -m src.web` 用の同期エントリーポイント。"""
    import uvicorn

    log_level = settings.log_level.lower()
    if log_level not in {"critical", "error", "warning", "info", "debug", "trace"}:
        log_level = "info"
    uvicorn.run(
        "src.web.app:app",
        host=settings.web_host,
        port=settings.web_port,
        log_level=log_level,
    )
