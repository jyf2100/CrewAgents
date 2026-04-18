"""
Hermes Admin API - FastAPI application for managing Hermes Agent instances on Kubernetes.
"""
from __future__ import annotations

import logging
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
API_PREFIX = "/admin/api"
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "hermes-agent")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")

logger = logging.getLogger("hermes-admin")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Hermes Admin API", openapi_url=None, docs_url=None)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------
async def verify_admin_key(x_admin_key: str = Header(..., alias="X-Admin-Key")):
    """Verify the request carries the correct admin key."""
    if not ADMIN_KEY:
        # No key configured – allow all requests (dev mode).
        return True
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")
    return True


auth = Depends(verify_admin_key)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------
@app.get(f"{API_PREFIX}/health", tags=["health"])
async def health():
    return {"status": "ok"}
