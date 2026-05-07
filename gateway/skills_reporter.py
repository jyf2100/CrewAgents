"""Gateway startup skill scanner and reporter.

Scans all skills directories for SKILL.md files, extracts metadata from
YAML frontmatter, and reports the aggregate to the Admin backend via an
internal HTTP endpoint.  The report is fire-and-forget -- failure never
blocks gateway startup.
"""

import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_skills_dir

logger = logging.getLogger(__name__)

# Default Admin internal URL inside the K8s cluster.
_DEFAULT_ADMIN_URL = "http://hermes-admin:48082"

# Directories to skip when walking skill trees (VCS and meta dirs).
_EXCLUDED_DIRS = frozenset({".git", ".github", ".hub"})


# ---------------------------------------------------------------------------
# Skill scanning
# ---------------------------------------------------------------------------


def scan_skills_metadata() -> List[Dict[str, Any]]:
    """Scan all skills directories and return metadata for every SKILL.md found.

    Walks both the local ``~/.hermes/skills/`` directory and any configured
    external skills directories.  For each SKILL.md, parses the YAML
    frontmatter and extracts ``name``, ``description``, ``version``,
    ``metadata.hermes.tags``, computes a ``content_hash`` (SHA-256 of the
    raw frontmatter, truncated to 32 hex chars), and stores the skill's
    path relative to its skills root.

    Returns:
        A list of dicts, each with keys: ``name``, ``description``,
        ``version``, ``tags``, ``skill_dir``, ``content_hash``.
    """
    # Lazy import to avoid heavy dependency at module level.
    from agent.skill_utils import (
        get_external_skills_dirs,
        parse_frontmatter,
    )

    skills_dirs = [get_skills_dir()]
    try:
        skills_dirs.extend(get_external_skills_dirs())
    except Exception:
        logger.debug("Failed to read external skills dirs", exc_info=True)

    results: List[Dict[str, Any]] = []

    for skills_root in skills_dirs:
        if not skills_root.is_dir():
            continue
        for skill_file in _iter_skill_files(skills_root):
            try:
                raw = skill_file.read_text(encoding="utf-8")
            except Exception:
                logger.debug("Cannot read %s, skipping", skill_file, exc_info=True)
                continue

            frontmatter, _ = parse_frontmatter(raw)
            if not frontmatter:
                continue

            name = str(frontmatter.get("name") or skill_file.parent.name).strip()
            if not name:
                continue

            description = str(frontmatter.get("description", "")).strip()
            version = str(frontmatter.get("version", "")).strip()

            # Extract metadata.hermes.tags
            tags = _extract_tags(frontmatter)

            # content_hash: SHA-256 of raw frontmatter block, truncated.
            content_hash = _compute_content_hash(raw)

            # skill_dir: relative path from the skills root.
            try:
                skill_dir = str(skill_file.parent.relative_to(skills_root))
            except ValueError:
                skill_dir = skill_file.parent.name

            results.append({
                "name": name,
                "description": description[:1024] if description else "",
                "version": version[:32] if version else "",
                "tags": tags,
                "skill_dir": skill_dir,
                "content_hash": content_hash,
            })

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def report_skills_sync(skills: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """Synchronously scan and POST skills to the Admin backend.

    This is a fire-and-forget call meant to run in the gateway startup path.
    It silently returns ``None`` when:

    * ``HERMES_AGENT_NUMBER`` is not set (non-K8s / local dev).
    * ``ADMIN_INTERNAL_TOKEN`` is not set.
    * The Admin backend is unreachable (``httpx.ConnectError``).

    Args:
        skills: Pre-scanned skills list.  When ``None``,
            :func:`scan_skills_metadata` is called automatically.

    Returns:
        The parsed JSON response dict on success, or ``None`` on any failure.
    """
    agent_number = os.getenv("HERMES_AGENT_NUMBER", "").strip()
    if not agent_number:
        logger.debug("HERMES_AGENT_NUMBER not set, skipping skills report")
        return None

    token = os.getenv("ADMIN_INTERNAL_TOKEN", "").strip()
    if not token:
        logger.debug("ADMIN_INTERNAL_TOKEN not set, skipping skills report")
        return None

    if skills is None:
        try:
            skills = scan_skills_metadata()
        except Exception:
            logger.debug("Skills scan failed", exc_info=True)
            return None

    report_id = _build_report_id(agent_number, skills)
    admin_url = os.getenv("ADMIN_INTERNAL_URL", _DEFAULT_ADMIN_URL).rstrip("/")
    endpoint = f"{admin_url}/internal/agents/{agent_number}/skills/report"

    payload = {
        "skills": skills,
        "report_id": report_id,
    }
    headers = {
        "X-Internal-Token": token,
        "Content-Type": "application/json",
    }

    try:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                "Skills report accepted: %d skill(s), %d tag(s)",
                data.get("skills_count", 0),
                len(data.get("tags_aggregated", [])),
            )
            return data
    except ImportError:
        logger.debug("httpx not installed, skipping skills report")
    except Exception:
        # ConnectError, TimeoutException, HTTPStatusError, etc.
        logger.debug("Skills report POST failed (non-critical)", exc_info=True)

    return None


def _build_report_id(agent_number: str, skills: list[dict] | None = None) -> str:
    """Build an idempotent report identifier.

    Format: ``{agent_number}-{unix_epoch}-{content_hash16}``

    The content hash is derived from the sorted skill names, so the report_id
    stays stable across restarts as long as the skill set does not change.
    """
    if skills:
        content = "-".join(sorted(s.get("name", "") for s in skills))
    else:
        content = ""
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    ts = int(time.time())
    return f"{agent_number}-{ts}-{content_hash}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iter_skill_files(skills_dir: Path):
    """Yield SKILL.md paths under *skills_dir*, skipping VCS directories."""
    for root, dirs, files in os.walk(skills_dir):
        dirs[:] = [d for d in dirs if d not in _EXCLUDED_DIRS]
        if "SKILL.md" in files:
            yield Path(root) / "SKILL.md"


def _extract_tags(frontmatter: Dict[str, Any]) -> List[str]:
    """Pull ``metadata.hermes.tags`` from parsed frontmatter."""
    metadata = frontmatter.get("metadata")
    if not isinstance(metadata, dict):
        return []
    hermes = metadata.get("hermes")
    if not isinstance(hermes, dict):
        return []
    tags = hermes.get("tags")
    if not tags:
        return []
    if isinstance(tags, str):
        tags = [tags]
    return [str(t).strip() for t in tags if str(t).strip()]


def _compute_content_hash(raw_content: str) -> str:
    """SHA-256 of the raw content between the first two ``---`` markers.

    Falls back to hashing the full string when no frontmatter delimiters
    are found.  Returns the first 32 hex characters.
    """
    fm_text = raw_content
    if raw_content.startswith("---"):
        end = raw_content.find("\n---", 3)
        if end != -1:
            fm_text = raw_content[3:end]

    digest = hashlib.sha256(fm_text.encode("utf-8")).hexdigest()
    return digest[:32]
