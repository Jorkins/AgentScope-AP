"""在工作区运行时强制应用用户 × Agent 的 Skill/MCP 白名单。"""

import os
from typing import Any

from agentscope.mcp import MCPClient
from agentscope.skill import Skill
from agentscope.workspace import WorkspaceBase
from fastapi import HTTPException

from .tool_bindings import ToolBindingStore


class ScopedBackend:
    """委托后端能力，并将文件路径限制在当前工作区根目录。"""

    def __init__(self, *, backend: Any, workdir: str) -> None:
        self._backend = backend
        self._workdir = workdir

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    def abspath(self, path: str, *, cwd: str) -> str:
        resolved = os.path.realpath(self._backend.abspath(path, cwd=cwd))
        root = os.path.realpath(self._workdir)
        try:
            contained = os.path.commonpath((root, resolved)) == root
        except ValueError:
            contained = False
        if not contained:
            raise HTTPException(status_code=403, detail="路径超出当前工作区")
        return resolved


class ScopedWorkspace:
    """委托原工作区能力，仅在资源发现层增加 AP 隔离边界。"""

    def __init__(
        self,
        *,
        workspace: WorkspaceBase,
        bindings: ToolBindingStore,
        user_id: str,
        agent_id: str,
    ) -> None:
        self._workspace = workspace
        self._bindings = bindings
        self._user_id = user_id
        self._agent_id = agent_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._workspace, name)

    async def initialize(self) -> None:
        await self._workspace.initialize()

    async def close(self) -> None:
        await self._workspace.close()

    def get_backend(self) -> ScopedBackend:
        return ScopedBackend(
            backend=self._workspace.get_backend(),
            workdir=self._workspace.workdir,
        )

    async def list_skills(self, *, agent_id: str | None = None) -> list[Skill]:
        effective_agent_id = agent_id or self._agent_id
        allowed = await self._bindings.enabled_names(
            user_id=self._user_id,
            agent_id=effective_agent_id,
            kind="skill",
        )
        skills = await self._workspace.list_skills(agent_id=effective_agent_id)
        return [skill for skill in skills if skill.name in allowed]

    async def list_mcps(
        self,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> list[MCPClient]:
        effective_agent_id = agent_id or self._agent_id
        allowed = await self._bindings.enabled_names(
            user_id=self._user_id,
            agent_id=effective_agent_id,
            kind="mcp",
        )
        mcps = await self._workspace.list_mcps(
            agent_id=effective_agent_id,
            session_id=session_id,
        )
        return [mcp for mcp in mcps if mcp.name in allowed]
