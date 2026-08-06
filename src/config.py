"""環境変数の読み込み。

`.env` を読み込んだうえで、Bot / Web で参照する値を `settings`
シングルトンとして公開する。pydantic を使わずに最小限の依存で動かす。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    discord_token: str
    database_url: str
    log_level: str
    admin_user: str
    admin_password: str
    web_host: str
    web_port: int
    level_bot_api_url: str
    level_bot_api_token: str


def _normalize_database_url(raw: str) -> str:
    """Heroku / Railway が提供する URL を SQLAlchemy 非同期形式に揃える。

    - ``postgres://``  → ``postgresql+asyncpg://`` (Heroku 旧形式)
    - ``postgresql://`` → ``postgresql+asyncpg://`` (Railway / 一般)
    - 既に ``+asyncpg`` / ``+aiosqlite`` を含むものはそのまま
    """
    if not raw:
        return raw
    if raw.startswith("postgres://"):
        return "postgresql+asyncpg://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://") and "+asyncpg" not in raw:
        return "postgresql+asyncpg://" + raw[len("postgresql://") :]
    return raw


def _load() -> Settings:
    # 既定は手元で `docker compose up -d db` した想定の Postgres 接続。
    # SQLite を使うのはテスト (in-memory) のときだけで、その場合は
    # conftest.py が DATABASE_URL を上書きするので問題ない。
    database_url = _normalize_database_url(
        _get(
            "DATABASE_URL",
            "postgresql+asyncpg://user:password@localhost:5432/itsuka_bot",
        )
    )

    # SQLite ファイル (テスト等) のときは親ディレクトリを掘っておく
    if database_url.startswith("sqlite+aiosqlite:///"):
        path_part = database_url.removeprefix("sqlite+aiosqlite:///")
        if path_part and not path_part.startswith(":memory:"):
            Path(path_part).parent.mkdir(parents=True, exist_ok=True)

    try:
        web_port = int(_get("WEB_PORT", "8000"))
    except ValueError as e:
        raise RuntimeError(f"WEB_PORT must be an integer: {e}") from e

    return Settings(
        discord_token=os.environ.get("DISCORD_TOKEN", "").strip(),
        database_url=database_url,
        log_level=_get("LOG_LEVEL", "INFO").upper(),
        admin_user=_get("ADMIN_USER", "admin"),
        admin_password=os.environ.get("ADMIN_PASSWORD", ""),
        web_host=_get("WEB_HOST", "0.0.0.0"),
        web_port=web_port,
        level_bot_api_url=os.environ.get("LEVEL_BOT_API_URL", "").strip().rstrip("/"),
        level_bot_api_token=os.environ.get("LEVEL_BOT_API_TOKEN", "").strip(),
    )


settings = _load()


def require_bot_settings() -> None:
    """Bot プロセス起動前に必須項目を検証する。"""
    if not settings.discord_token:
        raise RuntimeError(
            "DISCORD_TOKEN environment variable is required to run the bot."
        )


def require_web_settings() -> None:
    """Web プロセス起動前に必須項目を検証する。

    JWT 署名鍵 (``SESSION_SECRET_KEY``) は ``src.web.security`` 側で
    扱う。未設定なら警告ログ＋一時鍵で起動する。
    """
    if not settings.admin_password:
        raise RuntimeError(
            "ADMIN_PASSWORD environment variable is required to run the web admin."
        )
