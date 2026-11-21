"""认证与平台授权的数据库校验。"""

import hashlib

from agentscope.app.storage import StorageBase
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .cache import RedisCache
from .models import Membership, User


async def validate_token_membership(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: str,
    tenant_id: str | int | None,
) -> bool:
    """旧 token 只有在用户和当前租户 Membership 仍存在时才有效。"""
    async with session_factory() as session:
        user = await session.scalar(select(User.id).where(User.username == user_id))
        if user is None:
            return False
        if tenant_id is None:
            return True
        try:
            current_tenant_id = int(tenant_id)
        except (TypeError, ValueError):
            return False
        membership_id = await session.scalar(
            select(Membership.id).where(
                Membership.username == user_id,
                Membership.tenant_id == current_tenant_id,
            )
        )
        return membership_id is not None


async def enforce_auth_rate_limit(
    cache: RedisCache,
    action: str,
    client_ip: str,
    username: str,
    limit: int,
    window_seconds: int,
) -> None:
    """按 IP + username 限流，Redis key 不保存原始身份值。"""
    identity = f"{client_ip}:{username.strip().lower()}".encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()
    count = await cache.incr(f"ap:auth:{action}:{digest}", ttl_seconds=window_seconds)
    if count > limit:
        raise HTTPException(status_code=429, detail="尝试过于频繁，请稍后重试")


async def resource_belongs_to_owner(
    storage: StorageBase,
    kind: str,
    owner_id: str,
    resource_id: str,
) -> bool:
    """通过内核 owner-scoped 查询验证资源存在且确属分享者。"""
    getters = {
        "credential": getattr(storage, "get_credential", None),
        "agent": getattr(storage, "get_agent", None),
        "knowledge_base": getattr(storage, "get_knowledge_base", None),
    }
    getter = getters.get(kind)
    if getter is None:
        return False
    return await getter(owner_id, resource_id) is not None
