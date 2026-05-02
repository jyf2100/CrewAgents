"""ORM models for Hermes Admin user management."""
from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, func
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
