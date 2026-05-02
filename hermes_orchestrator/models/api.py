from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class TaskSubmitRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=50000)
    instructions: str = Field("", max_length=10000)
    model_id: str = "hermes-agent"
    priority: int = Field(1, ge=1, le=10)
    timeout_seconds: float = Field(600.0, ge=10.0, le=3600.0)
    max_retries: int = Field(2, ge=0, le=5)
    callback_url: str | None = None
    metadata: dict = Field(default_factory=dict)

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


class AgentListResponse(BaseModel):
    agents: list[dict]


class AgentHealthResponse(BaseModel):
    agent_id: str
    status: str
    circuit_state: str
    current_load: int
    max_concurrent: int
    last_health_check: float
