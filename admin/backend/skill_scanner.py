"""Skill scanner — discover installed skills on agent pods by reading SKILL.md frontmatter."""
from __future__ import annotations

import hashlib
import logging

import yaml

from k8s_client import K8sClient

logger = logging.getLogger("hermes-admin.skill_scanner")

SKILL_ROOTS = ["/opt/data/skills"]
MAX_SKILLS = 200
MAX_SKILL_MD_SIZE = 1_000_000  # 1 MB


def _parse_skill_md(content: str, fallback_name: str, skill_dir: str) -> dict | None:
    """Parse YAML frontmatter from a SKILL.md file.

    Returns a dict with keys: name, description, version, tags, skill_dir, content_hash.
    Returns None if frontmatter is missing or cannot be parsed.
    """
    if not content.startswith("---"):
        return None

    # Find the closing --- delimiter
    end = content.find("---", 3)
    if end < 0:
        return None

    raw_frontmatter = content[3:end].strip()
    if not raw_frontmatter:
        return None

    try:
        data = yaml.safe_load(raw_frontmatter)
    except yaml.YAMLError:
        return None

    if not isinstance(data, dict):
        return None

    name = data.get("name") or fallback_name
    description = data.get("description", "")
    version = data.get("version", "")

    # Navigate metadata.hermes.tags
    tags: list[str] = []
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        hermes = metadata.get("hermes")
        if isinstance(hermes, dict):
            raw_tags = hermes.get("tags")
            if isinstance(raw_tags, list):
                tags = [str(t).lower() for t in raw_tags if t is not None]
            elif isinstance(raw_tags, str):
                tags = [raw_tags.lower()]

    content_hash = hashlib.sha256(raw_frontmatter.encode("utf-8")).hexdigest()[:32]

    return {
        "name": str(name),
        "description": str(description or ""),
        "version": str(version or ""),
        "tags": tags,
        "skill_dir": skill_dir,
        "content_hash": content_hash,
    }


async def scan_skills(k8s: K8sClient, pod_name: str) -> list[dict]:
    """Scan skill roots on a pod recursively and return parsed skill metadata."""
    skills: list[dict] = []

    # Use find to locate all SKILL.md files in one shot (much faster than recursive list_dir)
    for root in SKILL_ROOTS:
        try:
            stdout, stderr = await k8s.run_command(
                pod_name,
                ["find", root, "-name", "SKILL.md", "-type", "f"],
            )
            if stderr and not stdout:
                logger.warning("find in %s failed: %s", root, stderr)
                continue
            paths = [p.strip() for p in stdout.strip().splitlines() if p.strip()]
        except Exception:
            logger.warning("Failed to list %s on pod %s", root, pod_name)
            continue

        for skill_md_path in paths:
            if len(skills) >= MAX_SKILLS:
                logger.warning("Reached max skills limit (%d) in %s", MAX_SKILLS, root)
                break

            # skill_dir = parent directory of SKILL.md
            skill_dir = skill_md_path.rsplit("/SKILL.md", 1)[0]
            fallback_name = skill_dir.rsplit("/", 1)[-1]

            try:
                content_bytes, error = await k8s.read_file_from_pod(pod_name, skill_md_path)
            except Exception:
                logger.warning("Skipping %s: read error", skill_md_path)
                continue
            if error or not content_bytes:
                logger.warning("Skipping %s: %s", skill_md_path, error or "empty content")
                continue
            if len(content_bytes) > MAX_SKILL_MD_SIZE:
                logger.warning("Skipping %s: too large (%d bytes)", skill_md_path, len(content_bytes))
                continue

            try:
                text = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                logger.warning("Skipping %s: not valid UTF-8", skill_md_path)
                continue

            parsed = _parse_skill_md(text, fallback_name=fallback_name, skill_dir=skill_dir)
            if parsed is None:
                logger.warning("Skipping %s: failed to parse frontmatter", skill_md_path)
                continue

            skills.append(parsed)

    logger.info("Scanned %d skills from pod %s", len(skills), pod_name)

    # Deduplicate by name (first occurrence wins)
    seen = set()
    unique = []
    for s in skills:
        if s["name"] not in seen:
            seen.add(s["name"])
            unique.append(s)
    if len(unique) < len(skills):
        logger.info("Deduplicated %d -> %d skills", len(skills), len(unique))
    return unique
