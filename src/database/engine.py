"""非同期 SQLAlchemy エンジンとセッションファクトリ。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.database.models import Base

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """テーブルを作成する (CREATE TABLE IF NOT EXISTS 相当)。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
