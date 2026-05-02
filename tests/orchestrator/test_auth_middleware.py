import hmac
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hermes_orchestrator.middleware.auth import create_auth_middleware

def _app(api_key: str = "secret123") -> FastAPI:
    app = FastAPI()
    cls, kwargs = create_auth_middleware(api_key)
    app.add_middleware(cls, **kwargs)
    @app.get("/health")
    async def health():
        return {"status": "ok"}
    @app.get("/api/v1/tasks")
    async def tasks():
        return {"tasks": []}
    return app

def test_health_endpoint_no_auth_required():
    client = TestClient(_app())
    resp = client.get("/health")
    assert resp.status_code == 200

def test_api_endpoint_requires_auth():
    client = TestClient(_app("mykey"))
    resp = client.get("/api/v1/tasks")
    assert resp.status_code == 401

def test_api_endpoint_accepts_valid_key():
    client = TestClient(_app("mykey"))
    resp = client.get("/api/v1/tasks", headers={"Authorization": "Bearer mykey"})
    assert resp.status_code == 200

def test_api_endpoint_rejects_wrong_key():
    client = TestClient(_app("mykey"))
    resp = client.get("/api/v1/tasks", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401

def test_api_endpoint_rejects_malformed_header():
    client = TestClient(_app("mykey"))
    resp = client.get("/api/v1/tasks", headers={"Authorization": "mykey"})
    assert resp.status_code == 401
