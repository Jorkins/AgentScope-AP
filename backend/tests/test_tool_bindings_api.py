from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.platform.auth import AuthService
from app.platform.models import AgentToolBinding, Base, ResourceShare
from app.platform.routes import _uid, create_router
from app.platform.tool_bindings import ToolBindingStore


class FakeStorage:
    def __init__(self):
        self.agents = {
            ("alice", "shared-agent"): SimpleNamespace(
                id="shared-agent",
                user_id="alice",
                source="user",
            )
        }
        self.skills = {
            "alice": [SimpleNamespace(name="alice-skill", display_name="Alice Skill", enabled=True)],
            "bob": [SimpleNamespace(name="bob-skill", display_name="Bob Skill", enabled=True)],
        }
        self.mcps = {
            "alice": [
                SimpleNamespace(
                    name="alice-mcp",
                    display_name="Alice MCP",
                    enabled=True,
                    values={"api_key": "super-secret"},
                    client=SimpleNamespace(
                        mcp_config={"headers": {"Authorization": "super-secret"}}
                    ),
                )
            ],
            "bob": [
                SimpleNamespace(
                    name="bob-mcp",
                    display_name="Bob MCP",
                    enabled=True,
                    values={"api_key": "bob-secret"},
                )
            ],
        }

    async def get_agent(self, user_id, agent_id):
        return self.agents.get((user_id, agent_id))

    async def list_skills(self, user_id):
        return self.skills.get(user_id, [])

    async def list_mcps(self, user_id):
        return self.mcps.get(user_id, [])

    async def get_skill_by_name(self, user_id, name):
        return next(
            (item for item in self.skills.get(user_id, []) if item.name == name),
            None,
        )

    async def get_mcp_by_name(self, user_id, name):
        return next(
            (item for item in self.mcps.get(user_id, []) if item.name == name),
            None,
        )


class FakeWorkspaceManager:
    def __init__(self):
        self.invalidations = []

    async def invalidate_agent_workspace(self, *, user_id, agent_id):
        self.invalidations.append((user_id, agent_id))


@pytest_asyncio.fixture
async def binding_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        session.add(
            ResourceShare(
                kind="agent",
                owner_id="alice",
                resource_id="shared-agent",
                permission="read",
                grantee_user_id="bob",
            )
        )
        await session.commit()

    storage = FakeStorage()
    workspace_manager = FakeWorkspaceManager()
    identity = {"user_id": "alice"}
    app = FastAPI()
    app.include_router(
        create_router(
            session_factory,
            AuthService(secret="x" * 32),
            storage=storage,
            workspace_manager=workspace_manager,
        )
    )
    app.dependency_overrides[_uid] = lambda: identity["user_id"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield SimpleNamespace(
            client=client,
            identity=identity,
            session_factory=session_factory,
            workspace_manager=workspace_manager,
        )
    await engine.dispose()


def binding_url(agent_id="shared-agent"):
    return f"/api/platform/agents/{agent_id}/tool-bindings"


async def update_binding(client, kind, resource_name, enabled=True):
    return await client.put(
        binding_url(),
        json={"kind": kind, "resource_name": resource_name, "enabled": enabled},
    )


@pytest.mark.asyncio
async def test_binding_get_and_upsert_only_use_current_user_installations(binding_client):
    client = binding_client.client

    initial = await client.get(binding_url())

    assert initial.status_code == 200
    assert initial.json() == {
        "skills": [
            {
                "name": "alice-skill",
                "display_name": "Alice Skill",
                "installed_enabled": True,
                "enabled": False,
            }
        ],
        "mcps": [
            {
                "name": "alice-mcp",
                "display_name": "Alice MCP",
                "installed_enabled": True,
                "enabled": False,
            }
        ],
    }
    assert "super-secret" not in initial.text
    assert "values" not in initial.text
    assert "mcp_config" not in initial.text

    enabled = await update_binding(client, "skill", "alice-skill")
    repeated = await update_binding(client, "skill", "alice-skill")
    mcp_enabled = await update_binding(client, "mcp", "alice-mcp")

    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert repeated.status_code == 200
    assert mcp_enabled.status_code == 200
    assert "super-secret" not in mcp_enabled.text
    current = await client.get(binding_url())
    assert current.json()["skills"][0]["enabled"] is True
    assert current.json()["mcps"][0]["enabled"] is True

    disabled = await update_binding(client, "skill", "alice-skill", enabled=False)
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    async with binding_client.session_factory() as session:
        rows = (
            await session.scalars(
                select(AgentToolBinding).where(AgentToolBinding.user_id == "alice")
            )
        ).all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_shared_agent_bindings_are_independent_per_user(binding_client):
    store = ToolBindingStore(binding_client.session_factory)

    alice_response = await update_binding(binding_client.client, "skill", "alice-skill")
    binding_client.identity["user_id"] = "bob"
    bob_list = await binding_client.client.get(binding_url())
    bob_response = await update_binding(binding_client.client, "skill", "bob-skill")

    assert alice_response.status_code == 200
    assert bob_list.status_code == 200
    assert [item["name"] for item in bob_list.json()["skills"]] == ["bob-skill"]
    assert bob_list.json()["skills"][0]["enabled"] is False
    assert bob_response.status_code == 200
    assert await store.enabled_names(
        user_id="alice", agent_id="shared-agent", kind="skill"
    ) == {"alice-skill"}
    assert await store.enabled_names(
        user_id="bob", agent_id="shared-agent", kind="skill"
    ) == {"bob-skill"}


@pytest.mark.asyncio
async def test_invisible_agent_and_cross_user_installations_return_404(binding_client):
    binding_client.identity["user_id"] = "charlie"
    invisible = await binding_client.client.get(binding_url())
    invisible_update = await update_binding(binding_client.client, "skill", "alice-skill")

    assert invisible.status_code == 404
    assert invisible_update.status_code == 404

    binding_client.identity["user_id"] = "bob"
    cross_user_skill = await update_binding(binding_client.client, "skill", "alice-skill")
    cross_user_mcp = await update_binding(binding_client.client, "mcp", "alice-mcp")

    assert cross_user_skill.status_code == 404
    assert cross_user_mcp.status_code == 404
    async with binding_client.session_factory() as session:
        rows = (
            await session.scalars(
                select(AgentToolBinding).where(AgentToolBinding.user_id == "bob")
            )
        ).all()
    assert rows == []


@pytest.mark.asyncio
async def test_binding_update_rejects_invalid_kind_and_empty_name(binding_client):
    invalid_kind = await update_binding(binding_client.client, "tool", "alice-skill")
    empty_name = await update_binding(binding_client.client, "skill", "")

    assert invalid_kind.status_code == 422
    assert empty_name.status_code == 422


@pytest.mark.asyncio
async def test_binding_update_invalidates_only_current_user_agent_workspace(
    binding_client,
):
    alice_response = await update_binding(
        binding_client.client,
        "skill",
        "alice-skill",
    )

    assert alice_response.status_code == 200
    assert binding_client.workspace_manager.invalidations == [
        ("alice", "shared-agent")
    ]

    binding_client.identity["user_id"] = "bob"
    bob_list = await binding_client.client.get(binding_url())
    bob_response = await update_binding(
        binding_client.client,
        "mcp",
        "bob-mcp",
    )

    assert bob_list.status_code == 200
    assert bob_response.status_code == 200
    assert binding_client.workspace_manager.invalidations == [
        ("alice", "shared-agent"),
        ("bob", "shared-agent"),
    ]

    binding_client.identity["user_id"] = "charlie"
    rejected = await update_binding(
        binding_client.client,
        "skill",
        "alice-skill",
    )

    assert rejected.status_code == 404
    assert binding_client.workspace_manager.invalidations == [
        ("alice", "shared-agent"),
        ("bob", "shared-agent"),
    ]