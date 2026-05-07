"""Database engine, session management, and startup migrations for Hermes Admin."""
from __future__ import annotations

import logging
import os
from typing import AsyncGenerator

from sqlalchemy import text
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


# ---------------------------------------------------------------------------
# Idempotent migrations — executed on every startup
# ---------------------------------------------------------------------------

_MIGRATION_SQL: list[str] = [
    # Phase 0: agent_metadata — add domain column
    """
    ALTER TABLE agent_metadata
      ADD COLUMN IF NOT EXISTS domain VARCHAR(20)
        NOT NULL DEFAULT 'generalist'
    """,
    # Phase 0: agent_metadata — add skills JSONB column
    """
    ALTER TABLE agent_metadata
      ADD COLUMN IF NOT EXISTS skills JSONB
        NOT NULL DEFAULT '[]'::jsonb
    """,
    # Phase 0: agent_metadata — ensure description column exists
    """
    ALTER TABLE agent_metadata
      ADD COLUMN IF NOT EXISTS description TEXT DEFAULT ''
    """,
    # Phase 0: create agent_skills table
    """
    CREATE TABLE IF NOT EXISTS agent_skills (
        id SERIAL PRIMARY KEY,
        agent_number INTEGER NOT NULL,
        skill_name VARCHAR(64) NOT NULL,
        description VARCHAR(1024) DEFAULT '',
        version VARCHAR(32) DEFAULT '',
        tags JSONB DEFAULT '[]'::jsonb NOT NULL,
        skill_dir VARCHAR(512) DEFAULT '',
        reported_at TIMESTAMPTZ DEFAULT NOW(),
        content_hash VARCHAR(64) DEFAULT ''
    )
    """,
    # Phase 0: agent_skills unique constraint (idempotent via DO NOTHING)
    """
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ix_agent_skills_agent_skill'
      ) THEN
        ALTER TABLE agent_skills
          ADD CONSTRAINT ix_agent_skills_agent_skill
          UNIQUE (agent_number, skill_name);
      END IF;
    END
    $$;
    """,
    # Phase 0: agent_skills index on agent_number
    """
    CREATE INDEX IF NOT EXISTS ix_agent_skills_agent_number
      ON agent_skills (agent_number)
    """,
    # Phase 0: agent_skills GIN index on tags
    """
    CREATE INDEX IF NOT EXISTS ix_agent_skills_tags
      ON agent_skills USING gin (tags)
    """,
    # Phase 0: create skill_report_ids table
    """
    CREATE TABLE IF NOT EXISTS skill_report_ids (
        report_id VARCHAR(128) PRIMARY KEY,
        agent_number INTEGER NOT NULL,
        skills_count INTEGER DEFAULT 0,
        tags_aggregated JSONB DEFAULT '[]'::jsonb,
        processed_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    # Phase 0: agent_metadata GIN index on skills
    """
    CREATE INDEX IF NOT EXISTS ix_agent_metadata_skills
      ON agent_metadata USING gin (skills)
    """,
]

_CLEANUP_SQL = """
    DELETE FROM skill_report_ids
    WHERE processed_at < NOW() - INTERVAL '7 days'
"""


async def _run_migrations() -> None:
    """Run idempotent migration SQL on every startup.

    Uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS so repeated execution is safe.
    """
    async with engine.begin() as conn:
        for sql in _MIGRATION_SQL:
            try:
                await conn.execute(text(sql))
            except Exception as exc:
                # Log but do not crash — individual migration failure should not
                # prevent the service from starting.
                logger.warning("Migration statement skipped: %s", exc)
        logger.info("Database migrations applied successfully")

    # Cleanup stale report-id records
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(_CLEANUP_SQL))
            if result.rowcount:
                logger.info("Cleaned up %d stale skill_report_ids records", result.rowcount)
    except Exception as exc:
        logger.warning("skill_report_ids cleanup skipped: %s", exc)


async def init_db() -> None:
    """Create tables on startup and run migrations."""
    from db_models import Base

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized")
    except Exception as e:
        logger.warning("Database init failed (email login will be unavailable): %s", e)

    # Run idempotent migrations after create_all
    try:
        await _run_migrations()
    except Exception as e:
        logger.warning("Database migrations failed: %s", e)
