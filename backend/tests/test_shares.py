import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.platform.auth import AuthService
from app.platform.models import Base, Membership, Tenant, User
from app.platform.routes import ShareCreateReq, _uid, create_router


class FakeStorage:
    async def get_agent(self, user_id, agent_id):
        if user_id == "alice" and agent_id == "agent-1":
            return object()
        return None


@pytest_asyncio.fixture
async def share_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        session.add_all(
            [
                User(id=1, username="alice", password_hash="hash"),
                User(id=2, username="bob", password_hash="hash"),
                Tenant(id=7, name="team", owner_id="bob"),
                Membership(id=1, tenant_id=7, username="bob", role="owner"),
                Membership(id=2, tenant_id=7, username="alice", role="member"),
            ]
        )
        await session.commit()

    app = FastAPI()
    app.include_router(
        create_router(
            session_factory,
            AuthService(secret="x" * 32),
            storage=FakeStorage(),
        )
    )
    app.dependency_overrides[_uid] = lambda: "alice"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    await engine.dispose()


def share_payload(**overrides):
    payload = {
        "kind": "agent",
        "owner_id": "alice",
        "resource_id": "agent-1",
        "permission": "read",
        "grantee_user_id": "bob",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("kind", ["mcp", "skill", "workspace"])
def test_share_kind_is_restricted_to_supported_resources(kind):
    with pytest.raises(ValidationError):
        ShareCreateReq(**share_payload(kind=kind))


def test_share_requires_exactly_one_grantee():
    with pytest.raises(ValidationError):
        ShareCreateReq(**share_payload(grantee_user_id=None))
    with pytest.raises(ValidationError):
        ShareCreateReq(**share_payload(grantee_tenant_id=7))


@pytest.mark.asyncio
async def test_share_rejects_resource_not_owned_by_owner(share_client):
    response = await share_client.post(
        "/api/platform/shares",
        json=share_payload(resource_id="missing"),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_share_rejects_tenant_grant_without_admin_role(share_client):
    response = await share_client.post(
        "/api/platform/shares",
        json=share_payload(grantee_user_id=None, grantee_tenant_id=7),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_share_returns_conflict(share_client):
    first = await share_client.post("/api/platform/shares", json=share_payload())
    second = await share_client.post("/api/platform/shares", json=share_payload())

    assert first.status_code == 200
    assert second.status_code == 409
