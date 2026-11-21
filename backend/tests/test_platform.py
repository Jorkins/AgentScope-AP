from contextlib import asynccontextmanager

import pytest
from fastapi import APIRouter, FastAPI

from app.config import Settings
from app import platform as platform_module
from app.platform.models import Base


@pytest.mark.asyncio
async def test_platform_lifespan_never_creates_tables(monkeypatch):
    settings = Settings(
        _env_file=None,
        JWT_SECRET="test-secret-0123456789abcdef0123456789abcdef",
    )
    platform = platform_module.build_platform(settings)
    assert platform.asgi_middlewares[0].kwargs["membership_validator"] is not None
    app = FastAPI()

    def fail_create_all(*args, **kwargs):
        raise AssertionError("请求 lifespan 不应调用 create_all")

    monkeypatch.setattr(Base.metadata, "create_all", fail_create_all)

    @asynccontextmanager
    async def original_lifespan(_app):
        yield

    app.router.lifespan_context = original_lifespan
    platform.register_routes(app)

    async with app.router.lifespan_context(app):
        pass


def test_platform_forwards_shared_workspace_manager_to_routes(monkeypatch):
    settings = Settings(
        _env_file=None,
        JWT_SECRET="test-secret-0123456789abcdef0123456789abcdef",
    )
    workspace_manager = object()
    captured = {}

    def fake_create_router(*args, **kwargs):
        captured.update(kwargs)
        return APIRouter()

    monkeypatch.setattr(platform_module, "create_router", fake_create_router)
    platform = platform_module.build_platform(
        settings,
        workspace_manager=workspace_manager,
    )

    platform.register_routes(FastAPI())

    assert captured["workspace_manager"] is workspace_manager
