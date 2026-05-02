from __future__ import annotations
import hmac
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

PUBLIC_PATHS = frozenset({"/health", "/metrics"})

class _AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str):
        super().__init__(app)
        self._expected = f"Bearer {api_key}"

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not hmac.compare_digest(auth, self._expected):
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        return await call_next(request)

def create_auth_middleware(api_key: str):
    return _AuthMiddleware, {"api_key": api_key}
