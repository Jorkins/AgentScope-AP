"""用户 × Agent 的 Skill/MCP 运行时白名单查询。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import AgentToolBinding


class ToolBindingStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_bindings(
        self,
        *,
        user_id: str,
        agent_id: str,
    ) -> list[AgentToolBinding]:
        """返回当前用户在一个 Agent 上的全部显式绑定。"""
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(AgentToolBinding).where(
                    AgentToolBinding.user_id == user_id,
                    AgentToolBinding.agent_id == agent_id,
                )
            )
            return list(rows)

    async def upsert(
        self,
        *,
        user_id: str,
        agent_id: str,
        kind: str,
        resource_name: str,
        enabled: bool,
    ) -> AgentToolBinding:
        """按四元组幂等更新绑定，不删除用户历史开关记录。"""
        if kind not in {"skill", "mcp"}:
            raise ValueError(f"不支持的工具绑定类型: {kind}")
        async with self._session_factory() as session:
            binding = await session.scalar(
                select(AgentToolBinding).where(
                    AgentToolBinding.user_id == user_id,
                    AgentToolBinding.agent_id == agent_id,
                    AgentToolBinding.kind == kind,
                    AgentToolBinding.resource_name == resource_name,
                )
            )
            if binding is None:
                binding = AgentToolBinding(
                    user_id=user_id,
                    agent_id=agent_id,
                    kind=kind,
                    resource_name=resource_name,
                    enabled=enabled,
                )
                session.add(binding)
            else:
                binding.enabled = enabled
            await session.commit()
            return binding

    async def enabled_names(
        self,
        *,
        user_id: str,
        agent_id: str,
        kind: str,
    ) -> set[str]:
        """只返回当前用户、当前 Agent 显式启用的资源名。"""
        if kind not in {"skill", "mcp"}:
            raise ValueError(f"不支持的工具绑定类型: {kind}")
        async with self._session_factory() as session:
            names = await session.scalars(
                select(AgentToolBinding.resource_name).where(
                    AgentToolBinding.user_id == user_id,
                    AgentToolBinding.agent_id == agent_id,
                    AgentToolBinding.kind == kind,
                    AgentToolBinding.enabled.is_(True),
                )
            )
            return set(names)
