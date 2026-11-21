import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.platform.auth import AuthService
from app.platform.models import Base
from app.platform.routes import create_router
from app.platform.security import enforce_auth_rate_limit


class FakeCache:
    def __init__(self):
        self.values = {}
        self.calls = []

    async def incr(self, key, ttl_seconds=None):
        self.calls.append((key, ttl_seconds))
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]


@pytest.mark.asyncio
async def test_auth_rate_limit_uses_hashed_ip_username_and_ttl():
    cache = FakeCache()
    for _ in range(2):
        await enforce_auth_rate_limit(cache, "login", "127.0.0.1", "alice", 2, 60)

    with pytest.raises(HTTPException) as exc_info:
        await enforce_auth_rate_limit(cache, "login", "127.0.0.1", "alice", 2, 60)

    assert exc_info.value.status_code == 429
    key, ttl = cache.calls[0]
    assert "127.0.0.1" not in key
    assert "alice" not in key
    assert ttl == 60


@pytest.mark.asyncio
async def test_login_route_enforces_limit_before_password_check():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    cache = FakeCache()
    app = FastAPI()
    app.include_router(
        create_router(
            session_factory,
            AuthService(secret="x" * 32),
            cache=cache,
            auth_rate_limit=2,
            auth_rate_window_seconds=60,
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        statuses = [
            (
                await client.post(
                    "/api/platform/auth/login",
                    json={"username": "alice", "password": "wrong-password"},
                )
            ).status_code
            for _ in range(3)
        ]

    assert statuses == [401, 401, 429]
    await engine.dispose()
