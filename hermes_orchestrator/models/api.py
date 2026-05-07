from __future__ import annotations

import ipaddress
import re
import socket
from enum import Enum
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

# Module-level compiled pattern for tag validation
_TAG_PATTERN = re.compile(r"^[a-z0-9_-]+$")

_VALID_DOMAINS = frozenset({"generalist", "code", "data", "ops", "creative"})


class RoutingStrategy(str, Enum):
    """Routing strategy names used in RoutingInfo.strategy (shared between backend and frontend)."""

    DOMAIN_TAG_MATCH = "domain_tag_match"
    DOMAIN_FALLBACK_TAG_MATCH = "domain_fallback_tag_match"
    TAG_MATCH = "tag_match"
    LEAST_LOAD = "least_load"
    REQUIRED_TAGS = "required_tags"
    REQUIRED_TAGS_UNSATISFIED = "required_tags_unsatisfied"
    NO_AGENT = "no_agent"


class TaskSubmitRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=50000)
    instructions: str = Field("", max_length=10000)
    model_id: str = "hermes-agent"
    priority: int = Field(1, ge=1, le=10)
    timeout_seconds: float = Field(600.0, ge=10.0, le=3600.0)
    max_retries: int = Field(2, ge=0, le=5)
    callback_url: str | None = None
    metadata: dict = Field(default_factory=dict)
    required_tags: list[str] = Field(
        default_factory=list,
        description="Agent must have ALL these tags (AND). Empty = no constraint.",
    )
    domain: str = Field(
        "generalist",
        description="Target domain for routing: generalist|code|data|ops|creative",
    )
    preferred_tags: list[str] = Field(
        default_factory=list,
        description="Soft-constraint tags merged into Jaccard scoring (optional bonus).",
    )

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        if v not in _VALID_DOMAINS:
            raise ValueError(
                f"domain must be one of {sorted(_VALID_DOMAINS)}, got {v!r}"
            )
        return v

    @field_validator("required_tags")
    @classmethod
    def validate_required_tags(cls, v: list[str]) -> list[str]:
        for tag in v:
            if not tag:
                raise ValueError("required_tags must not contain empty strings")
            if len(tag) > 64:
                raise ValueError(
                    f"required_tags item too long ({len(tag)} chars, max 64): {tag!r}"
                )
            if not _TAG_PATTERN.match(tag):
                raise ValueError(
                    f"required_tags item contains invalid characters (only [a-z0-9_-] allowed): {tag!r}"
                )
        return v

    @field_validator("preferred_tags")
    @classmethod
    def validate_preferred_tags(cls, v: list[str]) -> list[str]:
        for tag in v:
            if not tag:
                raise ValueError("preferred_tags must not contain empty strings")
            if len(tag) > 64:
                raise ValueError(
                    f"preferred_tags item too long ({len(tag)} chars, max 64): {tag!r}"
                )
            if not _TAG_PATTERN.match(tag):
                raise ValueError(
                    f"preferred_tags item contains invalid characters (only [a-z0-9_-] allowed): {tag!r}"
                )
        return v

    @field_validator("callback_url")
    @classmethod
    def validate_callback_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parsed = urlparse(v)
        if parsed.scheme != "https":
            raise ValueError("callback_url must use HTTPS")
        hostname = parsed.hostname
        if not hostname:
            raise ValueError("callback_url must have a hostname")
        try:
            for addr in set(socket.getaddrinfo(hostname, None)):
                ip = ipaddress.ip_address(addr[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    raise ValueError("callback_url must resolve to a public IP")
        except socket.gaierror:
            raise ValueError("callback_url hostname does not resolve")
        return v


class TaskSubmitResponse(BaseModel):
    task_id: str
    status: str = "queued"
    created_at: float
    eta_seconds: int = 30


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    assigned_agent: str | None = None
    run_id: str | None = None
    result: dict | None = None
    error: str | None = None
    retry_count: int = 0
    created_at: float
    updated_at: float
    routing_info: dict | None = None


class AgentListResponse(BaseModel):
    agents: list[dict]


class AgentHealthResponse(BaseModel):
    agent_id: str
    status: str
    circuit_state: str
    current_load: int
    max_concurrent: int
    last_health_check: float
