"""多租户资源访问策略。

实现 AgentScope 的 `ResourceAccessPolicyBase.list_accessible`，从共享表 +
成员表解析跨主人资源；`can_edit` 沿用基类默认实现（owner 恒可编辑，
跨主人按 EDIT 权限判定）。
"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentscope.app.access import (
    ResourceAccessPolicyBase,
    ResourceKind,
    ResourcePermission,
    ResourceRef,
)
from agentscope.app.storage import StorageBase

from .models import Membership, ResourceShare


class TenantResourceAccessPolicy(ResourceAccessPolicyBase):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    async def list_accessible(
        self,
        viewer_id: str,
        kind: ResourceKind,
        storage: StorageBase,
    ) -> list[ResourceRef]:
        async with self._sf() as session:
            # viewer 所在租户集合
            tenant_rows = await session.execute(
                select(Membership.tenant_id).where(Membership.username == viewer_id)
            )
            tenant_ids = [t for (t,) in tenant_rows.all()]

            conds = [ResourceShare.grantee_user_id == viewer_id]
            if tenant_ids:
                conds.append(ResourceShare.grantee_tenant_id.in_(tenant_ids))

            share_rows = await session.execute(
                select(ResourceShare).where(
                    ResourceShare.kind == kind.value,
                    or_(*conds),
                )
            )
            shares = share_rows.scalars().all()

        refs: list[ResourceRef] = []
        for s in shares:
            # 自有资源由内核默认逻辑覆盖，这里只返回跨主人的共享
            if s.owner_id == viewer_id:
                continue
            refs.append(
                ResourceRef(
                    kind=kind,
                    owner_id=s.owner_id,
                    resource_id=s.resource_id,
                    permission=(
                        ResourcePermission.EDIT
                        if s.permission == "edit"
                        else ResourcePermission.READ
                    ),
                )
            )
        return refs
