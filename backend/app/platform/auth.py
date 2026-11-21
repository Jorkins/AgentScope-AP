"""平台认证：bcrypt 密码散列 + JWT 签发/校验 + ASGI 中间件。

中间件在校验通过后，用 token 身份**覆盖注入** `X-User-ID` 请求头，
并剥离客户端伪造头，从而零侵入对接 AgentScope 全部 router
（其 `get_current_user_id` 从 `X-User-ID` 解析用户）。
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import bcrypt
import jwt
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


def hash_password(plain: str) -> str:
    encoded = plain.encode("utf-8")
    if len(encoded) > 72:
        raise ValueError("密码的 UTF-8 编码不能超过 72 字节")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


class AuthService:
    def __init__(self, secret: str, algorithm: str = "HS256", expire_minutes: int = 10080):
        self.secret = secret
        self.algorithm = algorithm
        self.expire_minutes = expire_minutes

    def create_token(self, user_id: str, username: str, tenant_id: str | int | None = None) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "username": username,
            "tenant_id": str(tenant_id) if tenant_id is not None else None,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=self.expire_minutes)).timestamp()),
        }
        return jwt.encode(payload, self.secret, algorithm=self.algorithm)

    def decode_token(self, token: str) -> dict[str, Any] | None:
        try:
            return jwt.decode(token, self.secret, algorithms=[self.algorithm])
        except jwt.PyJWTError:
            return None


# 无需认证的公开路径
PUBLIC_PATHS = {
    "/api/platform/auth/login",
    "/api/platform/auth/register",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}


class JwtAuthMiddleware:
    """纯 ASGI 中间件：校验 Bearer JWT 并注入 X-User-ID。"""

    def __init__(
        self,
        app: ASGIApp,
        auth_service: AuthService,
        require_auth: bool = True,
        public_paths: set[str] | None = None,
        membership_validator: Callable[[str, str | int | None], Awaitable[bool]] | None = None,
    ):
        self.app = app
        self.auth = auth_service
        self.require_auth = require_auth
        self.public_paths = public_paths or PUBLIC_PATHS
        self.membership_validator = membership_validator

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope["path"]
        if scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return
        if path in self.public_paths or path.startswith("/docs") or path.startswith("/openapi"):
            await self.app(scope, receive, send)
            return

        headers = MutableHeaders(scope=scope)
        auth_header = headers.get("Authorization") or headers.get("authorization")
        token: str | None = None
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

        payload = self.auth.decode_token(token) if token else None

        if payload is None:
            if self.require_auth:
                resp = JSONResponse({"detail": "未认证或 token 无效"}, status_code=401)
                await resp(scope, receive, send)
                return
            # 仅显式开发模式接受用户头，并统一写入 scope，路由不再直接信任请求头。
            user_id = headers.get("X-User-ID") or headers.get("x-user-id")
            if user_id:
                scope.setdefault("state", {})
                scope["state"]["user_id"] = user_id
                scope["state"]["username"] = user_id
            await self.app(scope, receive, send)
            return

        user_id = str(payload.get("sub") or payload.get("username") or "")
        if self.membership_validator is not None:
            is_current_member = await self.membership_validator(
                user_id,
                payload.get("tenant_id"),
            )
            if not is_current_member:
                resp = JSONResponse({"detail": "租户成员身份已失效"}, status_code=401)
                await resp(scope, receive, send)
                return

        # 校验通过：覆盖注入 X-User-ID，剥离伪造头
        headers["X-User-ID"] = user_id
        scope.setdefault("state", {})
        scope["state"]["user_id"] = user_id
        scope["state"]["username"] = payload.get("username")
        scope["state"]["tenant_id"] = payload.get("tenant_id")
        await self.app(scope, receive, send)
