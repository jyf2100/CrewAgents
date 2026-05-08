"""ORM models for Hermes Admin user management."""
from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(100), default="")
    agent_id = Column(Integer, unique=True, nullable=True)
    is_active = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # WebUI provisioning
    webui_jwt = Column(Text, nullable=True)
    webui_jwt_expires_at = Column(Float, nullable=True)
    webui_user_id = Column(String(255), nullable=True)
    webui_password = Column(String(255), nullable=True)

    # Provisioning status: not_started | pending | completed | failed
    provisioning_status = Column(String(20), default="not_started")
    provisioning_error = Column(Text, nullable=True)
    provisioning_updated_at = Column(Float, nullable=True)


class AgentMetadata(Base):
    __tablename__ = "agent_metadata"
    __table_args__ = (
        Index("ix_agent_metadata_tags", "tags", postgresql_using="gin"),
        Index("ix_agent_metadata_skills", "skills", postgresql_using="gin"),
    )

    agent_number = Column(Integer, primary_key=True)
    display_name = Column(String(100), default="")
    tags = Column(JSONB, default=list, server_default="[]", nullable=False)
    role = Column(String(50), default="generalist", server_default="generalist", nullable=False)
    # --- Phase 0 new fields ---
    domain = Column(
        String(20),
        default="generalist",
        server_default="generalist",
        nullable=False,
    )
    skills = Column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )
    # --- end Phase 0 ---
    description = Column(Text, default="")
    # Resource specs (persisted from K8s for user-mode viewing)
    cpu_request = Column(String(20), default="250m", server_default="250m")
    cpu_limit = Column(String(20), default="1000m", server_default="1000m")
    memory_request = Column(String(20), default="512Mi", server_default="512Mi")
    memory_limit = Column(String(20), default="1Gi", server_default="1Gi")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AgentSkill(Base):
    """Per-agent skill records, populated by agent startup self-reporting."""
    __tablename__ = "agent_skills"
    __table_args__ = (
        UniqueConstraint("agent_number", "skill_name", name="ix_agent_skills_agent_skill"),
        Index("ix_agent_skills_tags", "tags", postgresql_using="gin"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_number = Column(Integer, nullable=False, index=True)
    skill_name = Column(String(64), nullable=False)
    description = Column(String(1024), default="")
    version = Column(String(32), default="")
    tags = Column(JSONB, default=list, server_default="[]", nullable=False)
    skill_dir = Column(String(512), default="")
    reported_at = Column(DateTime(timezone=True), server_default=func.now())
    content_hash = Column(String(64), default="")


class ReportIdRecord(Base):
    """Idempotency dedup table for skill reports. Cleaned on startup (7-day TTL)."""
    __tablename__ = "skill_report_ids"

    report_id = Column(String(128), primary_key=True)
    agent_number = Column(Integer, nullable=False)
    skills_count = Column(Integer, default=0)
    tags_aggregated = Column(JSONB, default=list)
    processed_at = Column(DateTime(timezone=True), server_default=func.now())
