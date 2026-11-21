import asyncio
import hashlib
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agentscope.app.workspace_manager import LocalWorkspaceManager

from app.config import Settings
from app.platform.models import Base, WorkspaceBinding
from app.platform.workspace_manager import IsolatedWorkspaceManager
from app.runtime import build_runtime


class FakeStorage:
    def __init__(self, records=()):
        self._records = list(records)

    async def list_sessions(self, user_id, agent_id):
        del user_id, agent_id
        return self._records


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def make_manager(tmp_path, session_factory):
    return IsolatedWorkspaceManager(
        basedir=str(tmp_path),
        session_factory=session_factory,
    )


@pytest.mark.asyncio
async def test_new_workspace_id_is_deterministic_per_user_and_agent(
    tmp_path,
    session_factory,
):
    manager = make_manager(tmp_path, session_factory)

    first = await manager.assign_workspace_id(
        user_id="alice",
        agent_id="shared-agent",
        session_id="session-1",
    )
    second = await manager.assign_workspace_id(
        user_id="alice",
        agent_id="shared-agent",
        session_id="session-2",
    )
    expected = hashlib.blake2b(
        b"alice::shared-agent",
        digest_size=8,
    ).hexdigest()

    assert first == second == expected


@pytest.mark.asyncio
async def test_session_round_trip_can_register_assigned_workspace_id(
    tmp_path,
    session_factory,
):
    manager = make_manager(tmp_path, session_factory)
    workspace_id = await manager.assign_workspace_id(
        user_id="alice",
        agent_id="shared-agent",
        session_id="session-1",
    )

    workspace = await manager.get_workspace(
        "alice",
        "shared-agent",
        "session-1",
        workspace_id,
    )

    assert workspace.workspace_id == workspace_id
    assert workspace.workdir == str(tmp_path / workspace_id)
    await manager.close_all()


@pytest.mark.asyncio
async def test_shared_agent_has_distinct_owned_directories(
    tmp_path,
    session_factory,
):
    manager = make_manager(tmp_path, session_factory)

    alice = await manager.get_workspace("alice", "shared-agent", "session-1")
    bob = await manager.get_workspace("bob", "shared-agent", "session-2")

    assert alice.workspace_id != bob.workspace_id
    assert alice.workdir != bob.workdir
    assert alice.workdir == str(tmp_path / alice.workspace_id)
    assert bob.workdir == str(tmp_path / bob.workspace_id)

    async with session_factory() as session:
        bindings = (await session.scalars(select(WorkspaceBinding))).all()
    assert {(row.workspace_id, row.owner_id) for row in bindings} == {
        (alice.workspace_id, "alice"),
        (bob.workspace_id, "bob"),
    }
    await manager.close_all()


@pytest.mark.asyncio
async def test_explicit_workspace_id_cannot_cross_users(
    tmp_path,
    session_factory,
):
    manager = make_manager(tmp_path, session_factory)
    alice = await manager.get_workspace("alice", "shared-agent", "session-1")

    with pytest.raises(HTTPException) as exc_info:
        await manager.get_workspace(
            "bob",
            "shared-agent",
            "session-2",
            alice.workspace_id,
        )
    assert exc_info.value.status_code == 403
    await manager.close_all()


@pytest.mark.asyncio
async def test_unknown_legacy_workspace_id_fails_closed_without_creating_directory(
    tmp_path,
    session_factory,
):
    manager = make_manager(tmp_path, session_factory)

    with pytest.raises(ValueError, match="未登记"):
        await manager.get_workspace(
            "alice",
            "shared-agent",
            "session-1",
            "legacy-workspace",
        )

    assert not (tmp_path / "legacy-workspace").exists()


@pytest.mark.asyncio
async def test_registered_legacy_session_binding_takes_precedence(
    tmp_path,
    session_factory,
):
    async with session_factory() as session:
        session.add(
            WorkspaceBinding(
                workspace_id="legacy-workspace",
                owner_id="alice",
                agent_id="shared-agent",
                backend="local",
                host_path=str(tmp_path / "legacy-workspace"),
                state="ready",
            )
        )
        await session.commit()
    manager = make_manager(tmp_path, session_factory)
    manager.bind_storage(
        FakeStorage(
            [SimpleNamespace(config=SimpleNamespace(workspace_id="legacy-workspace"))]
        )
    )

    assigned = await manager.assign_workspace_id(
        user_id="alice",
        agent_id="shared-agent",
        session_id="session-new",
    )
    workspace = await manager.get_workspace(
        "alice",
        "shared-agent",
        "session-new",
        assigned,
    )

    assert assigned == "legacy-workspace"
    assert workspace.workspace_id == "legacy-workspace"
    await manager.close_all()


@pytest.mark.asyncio
async def test_same_owner_can_explicitly_share_a_team_workspace(
    tmp_path,
    session_factory,
):
    manager = make_manager(tmp_path, session_factory)
    leader = await manager.get_workspace("alice", "leader", "session-1")

    member = await manager.get_workspace(
        "alice",
        "member",
        "session-2",
        leader.workspace_id,
    )

    assert member.workspace_id == leader.workspace_id
    assert member.workdir == leader.workdir
    await manager.close_all()


class FakeConnectedMCP:
    def __init__(self):
        self.name = "alice-mcp"
        self.is_connected = True
        self.close_calls = 0

    async def close(self):
        self.close_calls += 1
        self.is_connected = False


@pytest.mark.asyncio
async def test_binding_invalidation_closes_mcp_and_rebuilds_without_deleting_files(
    tmp_path,
    session_factory,
):
    manager = make_manager(tmp_path, session_factory)
    original = await manager.get_workspace("alice", "shared-agent", "session-1")
    handle = FakeConnectedMCP()
    original._workspace._mcp_instances[("shared-agent", "session-1")] = {
        "alice-mcp": handle
    }
    marker = tmp_path / original.workspace_id / "marker.txt"
    marker.write_text("keep me", encoding="utf-8")

    await manager.invalidate_agent_workspace(
        user_id="alice",
        agent_id="shared-agent",
    )
    rebuilt = await manager.get_workspace("alice", "shared-agent", "session-2")

    assert handle.close_calls == 1
    assert original.is_alive is False
    assert rebuilt._workspace is not original._workspace
    assert rebuilt.workspace_id == original.workspace_id
    assert rebuilt.workdir == original.workdir
    assert marker.read_text(encoding="utf-8") == "keep me"
    await manager.close_all()


@pytest.mark.asyncio
async def test_binding_invalidation_does_not_evict_another_users_workspace(
    tmp_path,
    session_factory,
):
    manager = make_manager(tmp_path, session_factory)
    alice = await manager.get_workspace("alice", "shared-agent", "session-1")
    bob = await manager.get_workspace("bob", "shared-agent", "session-2")

    await manager.invalidate_agent_workspace(
        user_id="alice",
        agent_id="shared-agent",
    )
    bob_again = await manager.get_workspace("bob", "shared-agent", "session-3")

    assert bob_again._workspace is bob._workspace
    assert bob_again.is_alive is True
    assert alice.workspace_id != bob.workspace_id
    await manager.close_all()


@pytest.mark.asyncio
async def test_binding_invalidation_uses_registered_legacy_workspace_id(
    tmp_path,
    session_factory,
):
    async with session_factory() as session:
        session.add(
            WorkspaceBinding(
                workspace_id="legacy-workspace",
                owner_id="alice",
                agent_id="shared-agent",
                backend="local",
                host_path=str(tmp_path / "legacy-workspace"),
                state="ready",
            )
        )
        await session.commit()
    manager = make_manager(tmp_path, session_factory)
    original = await manager.get_workspace(
        "alice",
        "shared-agent",
        "session-1",
        "legacy-workspace",
    )

    await manager.invalidate_agent_workspace(
        user_id="alice",
        agent_id="shared-agent",
    )
    rebuilt = await manager.get_workspace(
        "alice",
        "shared-agent",
        "session-2",
        "legacy-workspace",
    )

    assert rebuilt._workspace is not original._workspace
    assert rebuilt.workspace_id == "legacy-workspace"
    await manager.close_all()


@pytest.mark.asyncio
async def test_failed_rematerialization_does_not_reuse_closed_workspace_and_can_retry(
    tmp_path,
    session_factory,
    monkeypatch,
):
    manager = make_manager(tmp_path, session_factory)
    original = await manager.get_workspace("alice", "shared-agent", "session-1")
    await manager.invalidate_agent_workspace(
        user_id="alice",
        agent_id="shared-agent",
    )

    async def fail_materialize(*args, **kwargs):
        raise RuntimeError("materialize failed")

    monkeypatch.setattr(LocalWorkspaceManager, "get_workspace", fail_materialize)
    with pytest.raises(RuntimeError, match="materialize failed"):
        await manager.get_workspace("alice", "shared-agent", "session-2")

    assert original.is_alive is False
    assert original.workspace_id not in manager._cache
    async with session_factory() as session:
        binding = await session.get(WorkspaceBinding, original.workspace_id)
    assert binding.state == "error"

    monkeypatch.undo()
    recovered = await manager.get_workspace("alice", "shared-agent", "session-3")

    assert recovered._workspace is not original._workspace
    assert recovered.is_alive is True
    async with session_factory() as session:
        binding = await session.get(WorkspaceBinding, original.workspace_id)
    assert binding.state == "ready"
    await manager.close_all()


class FakeCreationLock:
    def __init__(self):
        self._guard = asyncio.Lock()
        self._held = False
        self.key = "lock:workspace:create:test"
        self.acquire_result = True
        self.renew_result = True
        self.releases = 0

    async def acquire(self):
        async with self._guard:
            if self._held or not self.acquire_result:
                return False
            self._held = True
            return True

    async def renew(self):
        return self._held and self.renew_result

    async def release(self):
        self.releases += 1
        self._held = False
        return True


@pytest.mark.asyncio
async def test_creation_lock_serializes_concurrent_managers(
    tmp_path,
    session_factory,
    monkeypatch,
):
    lock = FakeCreationLock()
    active = 0
    peak = 0

    async def fake_materialize(self, user_id, agent_id, session_id, workspace_id=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return SimpleNamespace(
            workspace_id=workspace_id,
            workdir=str(tmp_path / workspace_id),
        )

    monkeypatch.setattr(LocalWorkspaceManager, "get_workspace", fake_materialize)

    def make_locked_manager():
        return IsolatedWorkspaceManager(
            basedir=str(tmp_path),
            session_factory=session_factory,
            creation_lock_factory=lambda _: lock,
            creation_lock_poll_interval=0.001,
            creation_lock_renew_interval=0.005,
        )

    first, second = await asyncio.gather(
        make_locked_manager().get_workspace("alice", "shared-agent", "session-1"),
        make_locked_manager().get_workspace("alice", "shared-agent", "session-2"),
    )

    assert first.workspace_id == second.workspace_id
    assert peak == 1
    assert lock.releases == 2


@pytest.mark.asyncio
async def test_lost_creation_lock_fails_closed_and_marks_error(
    tmp_path,
    session_factory,
    monkeypatch,
):
    lock = FakeCreationLock()
    lock.renew_result = False

    async def slow_materialize(self, user_id, agent_id, session_id, workspace_id=None):
        await asyncio.sleep(0.03)
        return SimpleNamespace(workspace_id=workspace_id)

    monkeypatch.setattr(LocalWorkspaceManager, "get_workspace", slow_materialize)
    manager = IsolatedWorkspaceManager(
        basedir=str(tmp_path),
        session_factory=session_factory,
        creation_lock_factory=lambda _: lock,
        creation_lock_renew_interval=0.001,
    )

    with pytest.raises(RuntimeError, match="锁所有权"):
        await manager.get_workspace("alice", "shared-agent", "session-1")

    workspace_id = await manager.assign_workspace_id(
        user_id="alice",
        agent_id="shared-agent",
        session_id="session-1",
    )
    async with session_factory() as session:
        binding = await session.get(WorkspaceBinding, workspace_id)
    assert binding.state == "error"
    assert lock.releases == 1


@pytest.mark.asyncio
async def test_creation_lock_timeout_does_not_materialize(
    tmp_path,
    session_factory,
    monkeypatch,
):
    lock = FakeCreationLock()
    lock.acquire_result = False
    calls = 0

    async def unexpected_materialize(*args, **kwargs):
        nonlocal calls
        calls += 1

    monkeypatch.setattr(LocalWorkspaceManager, "get_workspace", unexpected_materialize)
    manager = IsolatedWorkspaceManager(
        basedir=str(tmp_path),
        session_factory=session_factory,
        creation_lock_factory=lambda _: lock,
        creation_lock_timeout=0.001,
        creation_lock_poll_interval=0.001,
    )

    with pytest.raises(TimeoutError, match="工作区创建锁"):
        await manager.get_workspace("alice", "shared-agent", "session-1")

    assert calls == 0
    assert lock.releases == 0


def test_runtime_assembles_isolated_workspace_manager():
    settings = Settings(
        _env_file=None,
        JWT_SECRET="test-secret-0123456789abcdef0123456789abcdef",
    )

    runtime = build_runtime(settings)

    assert isinstance(runtime.workspace_manager, IsolatedWorkspaceManager)
