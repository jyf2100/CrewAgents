"""User management routes — email/password registration, login, admin CRUD, WebUI provisioning."""
from __future__ import annotations

import asyncio
import hmac
import logging
import re
import time
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import (
    AuthContext,
    auth,
    check_login_rate,
    get_current_user,
    mint_email_token,
    verify_email_token,
)
from database import get_db
from db_models import User
from models import (
    ActivateUserRequest,
    EmailLoginRequest,
    MessageResponse,
    RebindAgentRequest,
    UpdateUserRequest,
    UserListResponse,
    UserRegisterRequest,
    UserResponse,
    WebUILoginResponse,
)

logger = logging.getLogger("hermes-admin.user_routes")

router = APIRouter(prefix="/user", tags=["user-auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _admin_only(ctx: AuthContext) -> None:
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _user_to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name or "",
        agent_id=user.agent_id,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else None,
        provisioning_status=user.provisioning_status or "not_started",
        provisioning_error=user.provisioning_error,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
@router.post("/register", response_model=MessageResponse)
async def register(body: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    if not _EMAIL_RE.match(body.email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email,
        password_hash=_hash_password(body.password),
        display_name=body.display_name,
        is_active=False,
    )
    db.add(user)
    await db.commit()
    logger.info("User registered: %s (pending activation)", body.email)
    return MessageResponse(message="Registration successful, pending admin activation")


# ---------------------------------------------------------------------------
# Email login
# ---------------------------------------------------------------------------
@router.post("/login")
async def email_login(
    request: Request,
    body: EmailLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    if check_login_rate(client_ip):
        raise HTTPException(status_code=429, detail="Too many attempts, please try again later")

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not _verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account not yet activated")

    token = mint_email_token(user.id, user.email, user.agent_id)
    return {
        "token": token,
        "user_id": user.id,
        "email": user.email,
        "agent_id": user.agent_id,
        "display_name": user.display_name or user.email.split("@")[0],
    }


# ---------------------------------------------------------------------------
# Current user info
# ---------------------------------------------------------------------------
@router.get("/me")
async def get_current_user_info(
    request: Request,
    ctx: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    email_user_id = getattr(request.state, "email_user_id", None)
    if email_user_id is None:
        raise HTTPException(status_code=400, detail="Not an email-authenticated session")

    result = await db.execute(select(User).where(User.id == email_user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return _user_to_response(user)


# ---------------------------------------------------------------------------
# Admin: list users
# ---------------------------------------------------------------------------
@router.get("/list", response_model=UserListResponse)
async def list_users(
    ctx: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _admin_only(ctx)
    result = await db.execute(select(User).order_by(User.id))
    users = result.scalars().all()
    return UserListResponse(users=[_user_to_response(u) for u in users])


# ---------------------------------------------------------------------------
# Admin: activate user + bind agent + trigger WebUI provisioning
# ---------------------------------------------------------------------------
@router.post("/{user_id}/activate", response_model=UserResponse)
async def activate_user(
    user_id: int,
    body: ActivateUserRequest,
    ctx: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _admin_only(ctx)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.agent_id is not None:
        existing = await db.execute(
            select(User).where(User.agent_id == body.agent_id, User.id != user_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Agent already bound to another user")

    user.is_active = True
    user.agent_id = body.agent_id
    user.provisioning_status = "pending"
    user.provisioning_error = None
    await db.commit()
    await db.refresh(user)
    logger.info("User %s activated, bound to agent %s", user.email, body.agent_id)

    # Async provisioning (fire-and-forget)
    _trigger_provisioning(user_id, body.agent_id)

    return _user_to_response(user)


# ---------------------------------------------------------------------------
# Admin: rebind agent (update Direct Connection)
# ---------------------------------------------------------------------------
@router.post("/{user_id}/rebind-agent")
async def rebind_agent(
    user_id: int,
    body: RebindAgentRequest,
    ctx: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _admin_only(ctx)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await db.execute(
        select(User).where(User.agent_id == body.agent_id, User.id != user_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Agent already bound to another user")

    user.agent_id = body.agent_id
    user.provisioning_status = "pending"
    user.provisioning_error = None
    await db.commit()

    _trigger_provisioning(user_id, body.agent_id)

    return {"status": "rebound", "provisioning": "pending"}


# ---------------------------------------------------------------------------
# Admin: retry provisioning
# ---------------------------------------------------------------------------
@router.post("/{user_id}/retry-provision")
async def retry_provision(
    user_id: int,
    ctx: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _admin_only(ctx)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active or not user.agent_id:
        raise HTTPException(status_code=400, detail="User must be active with an agent")

    user.provisioning_status = "pending"
    user.provisioning_error = None
    await db.commit()

    _trigger_provisioning(user_id, user.agent_id)

    return {"provisioning_status": "pending"}


# ---------------------------------------------------------------------------
# User: get WebUI login URL
# ---------------------------------------------------------------------------
@router.get("/webui-url", response_model=WebUILoginResponse)
async def get_webui_url(
    request: Request,
    ctx: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    email_user_id = getattr(request.state, "email_user_id", None)
    if email_user_id is None:
        raise HTTPException(status_code=400, detail="Not an email-authenticated session")

    result = await db.execute(select(User).where(User.id == email_user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.provisioning_status != "completed":
        raise HTTPException(status_code=400, detail="WebUI not provisioned yet")

    if not user.webui_password:
        raise HTTPException(status_code=400, detail="WebUI credentials expired, retry provision")

    from webui_provision import EXTERNAL_WEBUI_URL

    return WebUILoginResponse(
        url=f"{EXTERNAL_WEBUI_URL}/api/v1/auths/signin",
        email=user.email,
        password=user.webui_password,
        provisioning_status=user.provisioning_status,
    )


# ---------------------------------------------------------------------------
# Admin: update user
# ---------------------------------------------------------------------------
@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    ctx: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _admin_only(ctx)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.display_name is not None:
        user.display_name = body.display_name
    if body.is_active is not None:
        user.is_active = body.is_active
    await db.commit()
    await db.refresh(user)
    return _user_to_response(user)


# ---------------------------------------------------------------------------
# Admin: delete user
# ---------------------------------------------------------------------------
@router.delete("/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: int,
    ctx: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _admin_only(ctx)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(user)
    await db.commit()

    # Clean up WebUI side
    try:
        from webui_provision import delete_webui_user
        await delete_webui_user(user.email)
    except Exception as e:
        logger.warning("WebUI cleanup failed for %s: %s", user.email, e)

    logger.info("User deleted: %s", user.email)
    return MessageResponse(message="User deleted")


# ---------------------------------------------------------------------------
# Background provisioning helper
# ---------------------------------------------------------------------------
def _trigger_provisioning(user_id: int, agent_id: int) -> None:
    async def _do_provision():
        from database import AsyncSessionLocal
        from webui_provision import provision_user

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return
            try:
                await provision_user(user, agent_id)
                await session.commit()
                logger.info("Provisioning completed for user %s", user.email)
            except Exception as e:
                user.provisioning_status = "failed"
                user.provisioning_error = str(e)[:500]
                user.provisioning_updated_at = time.time()
                await session.commit()
                logger.warning("Provisioning failed for user %s: %s", user.email, e)

    asyncio.create_task(_do_provision())
