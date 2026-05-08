"""Lightweight asyncpg pool for orchestrator metadata queries."""
from __future__ import annotations

import logging
from typing import Any

import asyncpg

from hermes_orchestrator.services.agent_selector import ROLE_TO_DOMAIN

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


def _resolve_domain(domain: str | None, role: str | None) -> str:
    if domain:
        return domain
    return ROLE_TO_DOMAIN.get(role or "generalist", "generalist")


async def init_pool(dsn: str) -> asyncpg.Pool | None:
    global _pool
    if not dsn:
        return None
    try:
        _pool = await asyncpg.create_pool(
            dsn,
            min_size=1,
            max_size=3,
            command_timeout=5,
            server_settings={"default_transaction_read_only": "on"},
        )
        logger.info("asyncpg pool created (max_size=3, read_only=true)")
        return _pool
    except Exception as exc:
        logger.warning("Failed to create asyncpg pool: %s", type(exc).__name__)
        return None


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def fetch_agent_metadata() -> dict[int, dict[str, Any]]:
    if _pool is None:
        return {}
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT agent_number, tags, role, domain, skills "
                "FROM agent_metadata"
            )
        result: dict[int, dict[str, Any]] = {}
        for row in rows:
            role = row["role"]
            domain = row["domain"]
            result[row["agent_number"]] = {
                "tags": list(row["tags"]),
                "role": role,
                "domain": _resolve_domain(domain, role),
                "skills": list(row["skills"]),
            }
        return result
    except Exception:
        logger.warning("PostgreSQL metadata query failed", exc_info=True)
        return {}
