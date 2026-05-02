"""Database engine and session management for Hermes Admin."""
from __future__ import annotations

import logging
import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger("hermes-admin.database")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://hermes:hermes_pg_2024@postgres:5432/hermes_admin",
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
AsyncSessionLocal = async_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """Create tables on startup."""
    from db_models import Base

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized")
    except Exception as e:
        logger.warning("Database init failed (email login will be unavailable): %s", e)
