import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.platform.models import AgentToolBinding, Base
from app.platform.scoped_workspace import ScopedWorkspace
from app.platform.tool_bindings import ToolBindingStore


class FakeWorkspace:
    def __init__(self):
        self.workspace_id = "workspace-1"
        self.workdir = "/workspaces/workspace-1"
        self.backend = object()
        self.agent_ids = []
        self.is_alive = False

    async def list_skills(self, *, agent_id=None):
        self.agent_ids.append(agent_id)
        return [
            SimpleNamespace(name="allowed-skill"),
            SimpleNamespace(name="disabled-skill"),
            SimpleNamespace(name="unbound-skill"),
            SimpleNamespace(name="other-agent-skill"),
            SimpleNamespace(name="other-user-skill"),
        ]

    async def list_mcps(self, *, agent_id=None, session_id=None):
        del session_id
        self.agent_ids.append(agent_id)
        return [
            SimpleNamespace(name="allowed-mcp"),
            SimpleNamespace(name="disabled-mcp"),
            SimpleNamespace(name="unbound-mcp"),
            SimpleNamespace(name="other-agent-mcp"),
            SimpleNamespace(name="other-user-mcp"),
        ]

    def get_backend(self):
        return self.backend

    async def list_tools(self):
        return ["workspace-tools"]

    async def initialize(self):
        self.is_alive = True

    async def close(self):
        self.is_alive = False


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                AgentToolBinding(
                    user_id="alice",
                    agent_id="agent-1",
                    kind="skill",
                    resource_name="allowed-skill",
                    enabled=True,
                ),
                AgentToolBinding(
                    user_id="alice",
                    agent_id="agent-1",
                    kind="skill",
                    resource_name="disabled-skill",
                    enabled=False,
                ),
                AgentToolBinding(
                    user_id="alice",
                    agent_id="agent-2",
                    kind="skill",
                    resource_name="other-agent-skill",
                    enabled=True,
                ),
                AgentToolBinding(
                    user_id="bob",
                    agent_id="agent-1",
                    kind="skill",
                    resource_name="other-user-skill",
                    enabled=True,
                ),
                AgentToolBinding(
                    user_id="alice",
                    agent_id="agent-1",
                    kind="mcp",
                    resource_name="allowed-mcp",
                    enabled=True,
                ),
                AgentToolBinding(
                    user_id="alice",
                    agent_id="agent-1",
                    kind="mcp",
                    resource_name="disabled-mcp",
                    enabled=False,
                ),
                AgentToolBinding(
                    user_id="alice",
                    agent_id="agent-2",
                    kind="mcp",
                    resource_name="other-agent-mcp",
                    enabled=True,
                ),
                AgentToolBinding(
                    user_id="bob",
                    agent_id="agent-1",
                    kind="mcp",
                    resource_name="other-user-mcp",
                    enabled=True,
                ),
            ]
        )
        await session.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


def make_scoped_workspace(session_factory):
    inner = FakeWorkspace()
    scoped = ScopedWorkspace(
        workspace=inner,
        bindings=ToolBindingStore(session_factory),
        user_id="alice",
        agent_id="agent-1",
    )
    return inner, scoped


@pytest.mark.asyncio
async def test_list_skills_applies_current_user_agent_whitelist(session_factory):
    inner, scoped = make_scoped_workspace(session_factory)

    skills = await scoped.list_skills()

    assert [skill.name for skill in skills] == ["allowed-skill"]
    assert inner.agent_ids == ["agent-1"]


@pytest.mark.asyncio
async def test_list_mcps_applies_current_user_agent_whitelist(session_factory):
    inner, scoped = make_scoped_workspace(session_factory)

    mcps = await scoped.list_mcps(session_id="session-1")

    assert [mcp.name for mcp in mcps] == ["allowed-mcp"]
    assert inner.agent_ids == ["agent-1"]


@pytest.mark.asyncio
async def test_workspace_capabilities_and_lifecycle_are_delegated(session_factory):
    inner, scoped = make_scoped_workspace(session_factory)

    await scoped.initialize()

    assert scoped.get_backend()._backend is inner.backend
    assert await scoped.list_tools() == ["workspace-tools"]
    assert inner.is_alive is True

    await scoped.close()
    assert inner.is_alive is False


def test_workspace_backend_confines_file_paths_to_current_workspace(
    tmp_path,
    session_factory,
):
    inner = FakeWorkspace()
    inner.workdir = str(tmp_path / "alice")
    inner.backend = SimpleNamespace(
        abspath=lambda path, *, cwd: os.path.abspath(
            path if os.path.isabs(path) else os.path.join(cwd, path)
        )
    )
    scoped = ScopedWorkspace(
        workspace=inner,
        bindings=ToolBindingStore(session_factory),
        user_id="alice",
        agent_id="agent-1",
    )
    backend = scoped.get_backend()

    inside = backend.abspath("marker.txt", cwd=inner.workdir)

    assert inside == os.path.realpath(tmp_path / "alice" / "marker.txt")
    for outside in (
        os.path.join("..", "bob", "secret.txt"),
        str(tmp_path / "bob" / "secret.txt"),
    ):
        with pytest.raises(HTTPException) as error:
            backend.abspath(outside, cwd=inner.workdir)
        assert error.value.status_code == 403
