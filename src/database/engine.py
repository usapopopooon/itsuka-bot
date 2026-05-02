"""非同期 SQLAlchemy エンジンとセッションファクトリ。"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.database.models import Base

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# 既存 DB に後付けで足したカラム (alembic を使わない簡易マイグレーション)。
# キー = (table_name, column_name)、値 = SQL 型。create_all で新規テーブルは
# 作られるが、既存テーブルへの ADD COLUMN は手動で当てる必要がある。
_LATE_ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("auto_reaction_configs", "pattern", "TEXT"),
]


async def _migrate_late_added_columns() -> None:
    """``_LATE_ADDED_COLUMNS`` を冪等に追加する。

    Postgres は ``ADD COLUMN IF NOT EXISTS``、SQLite は PRAGMA で存在確認 →
    無ければ ALTER TABLE を発行。両方で動かせる範囲で済ます。
    """
    dialect = engine.dialect.name
    async with engine.begin() as conn:
        for table, column, col_type in _LATE_ADDED_COLUMNS:
            if dialect == "postgresql":
                stmt = (
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}"
                )
                await conn.execute(text(stmt))
            elif dialect == "sqlite":
                result = await conn.execute(text(f"PRAGMA table_info({table})"))
                cols = {row[1] for row in result.fetchall()}
                if column not in cols:
                    stmt = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                    await conn.execute(text(stmt))
            else:
                logger.warning(
                    "Skipping late-added column migration on dialect %r", dialect
                )


async def init_db() -> None:
    """テーブルを作成 + 既存テーブルに新規カラムを追加する。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _migrate_late_added_columns()
