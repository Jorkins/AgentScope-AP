import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.platform.auth import AuthService, JwtAuthMiddleware, hash_password
from app.platform.routes import _uid


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


@pytest.mark.asyncio
async def test_options_bypasses_jwt_for_cors_preflight():
    app = JwtAuthMiddleware(
        _ok_app,
        auth_service=AuthService(secret="x" * 32),
        require_auth=True,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.options(
            "/api/agents/",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_development_mode_maps_header_into_verified_scope_state():
    observed = {}

    async def capture_app(scope, receive, send):
        observed.update(scope.get("state", {}))
        await _ok_app(scope, receive, send)

    app = JwtAuthMiddleware(
        capture_app,
        auth_service=AuthService(secret="x" * 32),
        require_auth=False,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/platform/auth/me",
            headers={"X-User-ID": "development-user"},
        )

    assert response.status_code == 200
    assert observed["user_id"] == "development-user"


def test_platform_uid_does_not_trust_spoofed_header():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/platform/auth/me",
            "headers": [(b"x-user-id", b"attacker")],
            "state": {},
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        _uid(request)

    assert exc_info.value.status_code == 401


def test_hash_password_rejects_more_than_72_utf8_bytes():
    with pytest.raises(ValueError, match="72"):
        hash_password("a" * 73)


@pytest.mark.asyncio
async def test_removed_membership_invalidates_existing_tenant_token():
    auth = AuthService(secret="x" * 32)
    token = auth.create_token("alice", "alice", tenant_id=7)

    async def removed_membership(_user_id, _tenant_id):
        return False

    app = JwtAuthMiddleware(
        _ok_app,
        auth_service=auth,
        require_auth=True,
        membership_validator=removed_membership,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/agents/",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 401
