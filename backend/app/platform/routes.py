"""平台路由：`/api/platform/*`（认证 / 租户 / 资源共享）。"""

from typing import Literal

from agentscope.app._service import ResourceAccessService
from agentscope.app.storage import StorageBase
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .auth import AuthService, hash_password, verify_password
from .cache import RedisCache
from .models import Membership, ResourceShare, Tenant, User
from .security import enforce_auth_rate_limit, resource_belongs_to_owner
from .tenant import TenantResourceAccessPolicy
from .tool_bindings import ToolBindingStore
from .workspace_manager import IsolatedWorkspaceManager


class RegisterReq(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    display_name: str = ""


class LoginReq(BaseModel):
    username: str
    password: str


class TokenResp(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    tenant_id: str | None = None


class TenantCreateReq(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class ShareCreateReq(BaseModel):
    kind: Literal["credential", "agent", "knowledge_base"]
    owner_id: str
    resource_id: str
    permission: Literal["read", "edit"] = "read"
    grantee_tenant_id: int | None = None
    grantee_user_id: str | None = None

    @model_validator(mode="after")
    def validate_single_grantee(self):
        if (self.grantee_tenant_id is None) == (self.grantee_user_id is None):
            raise ValueError("必须且只能指定一个授权对象")
        return self


class ToolBindingView(BaseModel):
    name: str
    display_name: str | None = None
    installed_enabled: bool
    enabled: bool


class ToolBindingListResp(BaseModel):
    skills: list[ToolBindingView]
    mcps: list[ToolBindingView]


class ToolBindingUpdateReq(BaseModel):
    kind: Literal["skill", "mcp"]
    resource_name: str = Field(min_length=1, max_length=255)
    enabled: bool


def _uid(request: Request) -> str:
    uid = request.scope.get("state", {}).get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="未认证")
    return uid


def create_router(
    session_factory: async_sessionmaker[AsyncSession],
    auth: AuthService,
    storage: StorageBase | None = None,
    workspace_manager: IsolatedWorkspaceManager | None = None,
    cache: RedisCache | None = None,
    auth_rate_limit: int = 10,
    auth_rate_window_seconds: int = 60,
) -> APIRouter:
    router = APIRouter(prefix="/api/platform", tags=["platform"])
    tool_bindings = ToolBindingStore(session_factory)
    resource_access = (
        ResourceAccessService(storage, TenantResourceAccessPolicy(session_factory))
        if storage is not None
        else None
    )

    @router.post("/auth/register", response_model=TokenResp)
    async def register(req: RegisterReq, request: Request):
        if cache is not None:
            await enforce_auth_rate_limit(
                cache,
                "register",
                request.client.host if request.client else "unknown",
                req.username,
                auth_rate_limit,
                auth_rate_window_seconds,
            )
        async with session_factory() as session:
            exists = await session.execute(select(User).where(User.username == req.username))
            if exists.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="用户名已存在")

            user = User(
                username=req.username,
                password_hash=hash_password(req.password),
                display_name=req.display_name or req.username,
            )
            tenant = Tenant(name=f"{req.username} 个人空间", owner_id=req.username, is_personal=True)
            session.add_all([user, tenant])
            await session.flush()
            session.add(Membership(tenant_id=tenant.id, username=req.username, role="owner"))
            await session.commit()
            token = auth.create_token(user_id=req.username, username=req.username, tenant_id=tenant.id)
            return TokenResp(access_token=token, username=req.username, tenant_id=str(tenant.id))

    @router.post("/auth/login", response_model=TokenResp)
    async def login(req: LoginReq, request: Request):
        if cache is not None:
            await enforce_auth_rate_limit(
                cache,
                "login",
                request.client.host if request.client else "unknown",
                req.username,
                auth_rate_limit,
                auth_rate_window_seconds,
            )
        async with session_factory() as session:
            row = await session.execute(select(User).where(User.username == req.username))
            user = row.scalar_one_or_none()
            if not user or not verify_password(req.password, user.password_hash):
                raise HTTPException(status_code=401, detail="用户名或密码错误")

            trow = await session.execute(
                select(Membership.tenant_id).where(Membership.username == req.username).limit(1)
            )
            t = trow.first()
            tenant_id = str(t[0]) if t else None
            token = auth.create_token(user_id=req.username, username=req.username, tenant_id=tenant_id)
            return TokenResp(access_token=token, username=req.username, tenant_id=tenant_id)

    @router.get("/auth/me")
    async def me(request: Request, uid: str = Depends(_uid)):
        async with session_factory() as session:
            rows = await session.execute(
                select(Tenant).join(Membership, Membership.tenant_id == Tenant.id).where(
                    Membership.username == uid
                )
            )
            tenants = [{"id": t.id, "name": t.name, "is_personal": t.is_personal} for t in rows.scalars().all()]
        return {"username": uid, "tenants": tenants}

    @router.post("/tenants")
    async def create_tenant(req: TenantCreateReq, uid: str = Depends(_uid)):
        async with session_factory() as session:
            tenant = Tenant(name=req.name, owner_id=uid, is_personal=False)
            session.add(tenant)
            await session.flush()
            session.add(Membership(tenant_id=tenant.id, username=uid, role="owner"))
            await session.commit()
            return {"id": tenant.id, "name": tenant.name}

    @router.get("/tenants")
    async def my_tenants(uid: str = Depends(_uid)):
        async with session_factory() as session:
            rows = await session.execute(
                select(Tenant).join(Membership, Membership.tenant_id == Tenant.id).where(
                    Membership.username == uid
                )
            )
            return [{"id": t.id, "name": t.name, "is_personal": t.is_personal} for t in rows.scalars().all()]

    @router.post("/shares")
    async def create_share(req: ShareCreateReq, uid: str = Depends(_uid)):
        if req.owner_id != uid:
            raise HTTPException(status_code=403, detail="只能分享自己的资源")
        if storage is None or not await resource_belongs_to_owner(
            storage,
            req.kind,
            req.owner_id,
            req.resource_id,
        ):
            raise HTTPException(status_code=404, detail="资源不存在或不属于分享者")
        async with session_factory() as session:
            if req.grantee_tenant_id is not None:
                role = await session.scalar(
                    select(Membership.role).where(
                        Membership.tenant_id == req.grantee_tenant_id,
                        Membership.username == uid,
                    )
                )
                if role not in {"owner", "admin"}:
                    raise HTTPException(status_code=403, detail="仅租户 owner/admin 可分享")
            share = ResourceShare(**req.model_dump())
            session.add(share)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise HTTPException(status_code=409, detail="重复的资源分享") from exc
            return {"id": share.id}

    @router.get("/shares/accessible")
    async def accessible(uid: str = Depends(_uid)):
        async with session_factory() as session:
            trows = await session.execute(select(Membership.tenant_id).where(Membership.username == uid))
            tenant_ids = [t for (t,) in trows.all()]
            from sqlalchemy import or_

            conds = [ResourceShare.grantee_user_id == uid]
            if tenant_ids:
                conds.append(ResourceShare.grantee_tenant_id.in_(tenant_ids))
            rows = await session.execute(select(ResourceShare).where(or_(*conds)))
            return [
                {
                    "kind": s.kind,
                    "owner_id": s.owner_id,
                    "resource_id": s.resource_id,
                    "permission": s.permission,
                }
                for s in rows.scalars().all()
                if s.owner_id != uid
            ]

    async def resolve_visible_agent(user_id: str, agent_id: str) -> None:
        if resource_access is None:
            raise HTTPException(status_code=404, detail="Agent 不存在或不可见")
        await resource_access.resolve_agent(user_id, agent_id)

    @router.get(
        "/agents/{agent_id}/tool-bindings",
        response_model=ToolBindingListResp,
    )
    async def list_tool_bindings(agent_id: str, uid: str = Depends(_uid)):
        await resolve_visible_agent(uid, agent_id)
        skills = await storage.list_skills(uid)
        mcps = await storage.list_mcps(uid)
        rows = await tool_bindings.list_bindings(user_id=uid, agent_id=agent_id)
        enabled = {(row.kind, row.resource_name): row.enabled for row in rows}

        def view(kind, record):
            return ToolBindingView(
                name=record.name,
                display_name=record.display_name,
                installed_enabled=record.enabled,
                enabled=enabled.get((kind, record.name), False),
            )

        return ToolBindingListResp(
            skills=[view("skill", record) for record in skills],
            mcps=[view("mcp", record) for record in mcps],
        )

    @router.put(
        "/agents/{agent_id}/tool-bindings",
        response_model=ToolBindingView,
    )
    async def update_tool_binding(
        agent_id: str,
        req: ToolBindingUpdateReq,
        uid: str = Depends(_uid),
    ):
        await resolve_visible_agent(uid, agent_id)
        if req.kind == "skill":
            record = await storage.get_skill_by_name(uid, req.resource_name)
        else:
            record = await storage.get_mcp_by_name(uid, req.resource_name)
        if record is None:
            raise HTTPException(status_code=404, detail="安装资源不存在或不属于当前用户")

        binding = await tool_bindings.upsert(
            user_id=uid,
            agent_id=agent_id,
            kind=req.kind,
            resource_name=req.resource_name,
            enabled=req.enabled,
        )
        if workspace_manager is not None:
            await workspace_manager.invalidate_agent_workspace(
                user_id=uid,
                agent_id=agent_id,
            )
        return ToolBindingView(
            name=record.name,
            display_name=record.display_name,
            installed_enabled=record.enabled,
            enabled=binding.enabled,
        )

    return router
