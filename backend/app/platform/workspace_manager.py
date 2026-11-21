"""AP 的用户 × Agent 工作区归属与本地目录隔离。"""

import asyncio
from collections.abc import Callable
from contextlib import suppress
import hashlib
import os
import time
from datetime import datetime, timezone

from agentscope.app.workspace_manager import IsolationPolicy, LocalWorkspaceManager
from agentscope.workspace import WorkspaceBase
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import WorkspaceBinding
from .scoped_workspace import ScopedWorkspace
from .tool_bindings import ToolBindingStore
from .workspace_leases import RedisWorkspaceCreationLock


class IsolatedWorkspaceManager(LocalWorkspaceManager):
    """用数据库归属约束内核本地工作区，不接受未登记的显式 ID。"""

    def __init__(
        self,
        basedir: str,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        default_mcps: list | None = None,
        skill_paths: list[str] | None = None,
        ttl: float = 3600.0,
        creation_lock_factory: Callable[[str], RedisWorkspaceCreationLock] | None = None,
        creation_lock_timeout: float = 10.0,
        creation_lock_poll_interval: float = 0.05,
        creation_lock_renew_interval: float = 10.0,
    ) -> None:
        super().__init__(
            basedir=basedir,
            isolation=IsolationPolicy.PER_AGENT,
            default_mcps=default_mcps,
            skill_paths=skill_paths,
            ttl=ttl,
        )
        self._session_factory = session_factory
        self._tool_bindings = ToolBindingStore(session_factory)
        self._creation_lock_factory = creation_lock_factory
        self._creation_lock_timeout = creation_lock_timeout
        self._creation_lock_poll_interval = creation_lock_poll_interval
        self._creation_lock_renew_interval = creation_lock_renew_interval

    async def assign_workspace_id(
        self,
        *,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> str:
        """已有 Session 绑定优先，否则生成跨副本一致的确定性 ID。"""
        del session_id
        if self._storage is not None:
            for record in await self._storage.list_sessions(user_id, agent_id):
                if record.config.workspace_id:
                    return record.config.workspace_id
        return hashlib.blake2b(
            f"{user_id}::{agent_id}".encode("utf-8"),
            digest_size=8,
        ).hexdigest()

    async def _resolve_binding(
        self,
        *,
        user_id: str,
        agent_id: str,
        workspace_id: str,
        explicit: bool,
    ) -> WorkspaceBinding:
        async with self._session_factory() as session:
            binding = await session.get(WorkspaceBinding, workspace_id)
            if binding is None:
                assigned_id = hashlib.blake2b(
                    f"{user_id}::{agent_id}".encode("utf-8"),
                    digest_size=8,
                ).hexdigest()
                # 内核会把自动分配的 ID 存入 Session 后显式回传；只允许这个
                # 确定性 ID 自动登记，未知 legacy ID 仍必须失败关闭。
                if explicit and workspace_id != assigned_id:
                    raise ValueError(f"工作区 {workspace_id!r} 未登记，拒绝绑定")
                binding = WorkspaceBinding(
                    workspace_id=workspace_id,
                    owner_id=user_id,
                    agent_id=agent_id,
                    backend="local",
                    host_path=os.path.abspath(os.path.join(self._basedir, workspace_id)),
                    state="creating",
                )
                session.add(binding)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    binding = await session.get(WorkspaceBinding, workspace_id)
                    if binding is None:
                        raise

            if binding.owner_id != user_id:
                raise HTTPException(status_code=403, detail="工作区属于其他用户")
            if binding.backend != "local":
                raise ValueError(f"工作区后端不是 local: {binding.backend}")
            return binding

    async def _mark_ready(self, workspace_id: str) -> None:
        async with self._session_factory() as session:
            binding = await session.get(WorkspaceBinding, workspace_id)
            if binding is not None:
                binding.state = "ready"
                binding.last_used_at = datetime.now(timezone.utc)
                await session.commit()

    async def _mark_error(self, workspace_id: str) -> None:
        async with self._session_factory() as session:
            binding = await session.get(WorkspaceBinding, workspace_id)
            if binding is not None:
                binding.state = "error"
                await session.commit()

    async def invalidate_agent_workspace(
        self,
        *,
        user_id: str,
        agent_id: str,
    ) -> None:
        """关闭并移除当前用户当前 Agent 的缓存，保留磁盘工作区。"""
        async with self._session_factory() as session:
            workspace_id = await session.scalar(
                select(WorkspaceBinding.workspace_id).where(
                    WorkspaceBinding.owner_id == user_id,
                    WorkspaceBinding.agent_id == agent_id,
                )
            )
        if workspace_id is None:
            workspace_id = hashlib.blake2b(
                f"{user_id}::{agent_id}".encode("utf-8"),
                digest_size=8,
            ).hexdigest()
        await self.close(workspace_id)

    async def _materialize_workspace(
        self,
        *,
        user_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str,
    ) -> ScopedWorkspace:
        try:
            # 内核以 <basedir>/<agent_id> 建目录；这里把稳定 workspace_id
            # 作为该层的目录名，避免共享 Agent 的不同用户发生碰撞。
            workspace = await super().get_workspace(
                user_id=user_id,
                agent_id=workspace_id,
                session_id=session_id,
                workspace_id=workspace_id,
            )
        except Exception:
            await self._mark_error(workspace_id)
            raise
        await self._mark_ready(workspace_id)
        return ScopedWorkspace(
            workspace=workspace,
            bindings=self._tool_bindings,
            user_id=user_id,
            agent_id=agent_id,
        )

    async def _acquire_creation_lock(self, lock: RedisWorkspaceCreationLock) -> None:
        deadline = time.monotonic() + self._creation_lock_timeout
        while not await lock.acquire():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"等待工作区创建锁超时: {lock.key}")
            await asyncio.sleep(min(self._creation_lock_poll_interval, remaining))

    async def _renew_creation_lock(
        self,
        lock: RedisWorkspaceCreationLock,
        lost: asyncio.Event,
    ) -> None:
        while True:
            await asyncio.sleep(self._creation_lock_renew_interval)
            try:
                renewed = await lock.renew()
            except Exception:
                renewed = False
            if not renewed:
                lost.set()
                return

    async def get_workspace(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str | None = None,
    ) -> WorkspaceBase:
        explicit = bool(workspace_id)
        workspace_id = workspace_id or await self.assign_workspace_id(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
        )
        binding_args = {
            "user_id": user_id,
            "agent_id": agent_id,
            "workspace_id": workspace_id,
            "explicit": explicit,
        }
        await self._resolve_binding(**binding_args)
        if self._creation_lock_factory is None:
            return await self._materialize_workspace(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                workspace_id=workspace_id,
            )

        lock = self._creation_lock_factory(workspace_id)
        await self._acquire_creation_lock(lock)
        try:
            # 等待锁期间另一副本可能已经完成初始化，拿锁后必须复查归属。
            await self._resolve_binding(**binding_args)
            lost = asyncio.Event()
            renew_task = asyncio.create_task(self._renew_creation_lock(lock, lost))
            try:
                scoped = await self._materialize_workspace(
                    user_id=user_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    workspace_id=workspace_id,
                )
            finally:
                renew_task.cancel()
                with suppress(asyncio.CancelledError):
                    await renew_task
            if lost.is_set():
                await self._mark_error(workspace_id)
                raise RuntimeError(f"工作区创建锁所有权已丢失: {workspace_id}")
        finally:
            await lock.release()
        return scoped
