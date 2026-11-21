"""平台壳装配：认证 / 多租户 / 缓存 / 平台路由。

`build_platform` 返回一个 `Platform`，由 `app.main` 注入 AgentScope 的
`create_app`（resource_access_policy + extra_middlewares），并注册平台路由。
"""

from dataclasses import dataclass
from functools import partial
from typing import Callable

from agentscope.app.storage import StorageBase
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.middleware import Middleware

from ..config import Settings
from .audit import RequestAuditMiddleware
from .auth import AuthService, JwtAuthMiddleware
from .cache import RedisCache
from .routes import create_router
from .security import validate_token_membership
from .tenant import TenantResourceAccessPolicy
from .workspace_manager import IsolatedWorkspaceManager


@dataclass
class Platform:
    resource_access_policy: TenantResourceAccessPolicy
    asgi_middlewares: list
    register_routes: Callable[[FastAPI], None]
    cache: RedisCache
    auth: AuthService


def build_platform(
    settings: Settings,
    storage: StorageBase | None = None,
    workspace_manager: IsolatedWorkspaceManager | None = None,
) -> Platform:
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    auth = AuthService(
        secret=settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
        expire_minutes=settings.JWT_EXPIRE_MINUTES,
    )
    policy = TenantResourceAccessPolicy(session_factory)
    cache = RedisCache(host=settings.REDIS_HOST, port=settings.REDIS_PORT)

    asgi_middlewares = [
        Middleware(
            JwtAuthMiddleware,
            auth_service=auth,
            require_auth=settings.AUTH_ENABLED,
            membership_validator=partial(validate_token_membership, session_factory),
        ),
        Middleware(RequestAuditMiddleware),
    ]

    def register_routes(app: FastAPI) -> None:
        app.include_router(
            create_router(
                session_factory,
                auth,
                storage=storage,
                workspace_manager=workspace_manager,
                cache=cache,
                auth_rate_limit=settings.AUTH_RATE_LIMIT,
                auth_rate_window_seconds=settings.AUTH_RATE_WINDOW_SECONDS,
            )
        )

    return Platform(
        resource_access_policy=policy,
        asgi_middlewares=asgi_middlewares,
        register_routes=register_routes,
        cache=cache,
        auth=auth,
    )
