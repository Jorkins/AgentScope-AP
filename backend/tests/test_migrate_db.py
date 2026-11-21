import sqlite3

import pytest

from scripts.migrate_db import migrate_database


@pytest.mark.asyncio
async def test_migrate_database_upgrades_ap_and_kernel_schemas(tmp_path):
    database_path = tmp_path / "migration.db"
    await migrate_database(f"sqlite+aiosqlite:///{database_path}")

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {
        "ap_users",
        "ap_resource_shares",
        "ap_workspace_bindings",
        "ap_agent_tool_bindings",
        "ap_knowledge_chunks",
        "ap_alembic_version",
        "agents",
        "alembic_version",
    } <= tables


@pytest.mark.asyncio
async def test_migrate_database_baselines_legacy_create_all_tables(tmp_path):
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE ap_users (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE ap_tenants (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE ap_memberships (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE ap_resource_shares ("
            "id INTEGER PRIMARY KEY, kind VARCHAR, owner_id VARCHAR, "
            "resource_id VARCHAR, grantee_user_id VARCHAR, grantee_tenant_id INTEGER)"
        )

    await migrate_database(f"sqlite+aiosqlite:///{database_path}")

    with sqlite3.connect(database_path) as connection:
        version = connection.execute(
            "SELECT version_num FROM ap_alembic_version"
        ).fetchone()[0]
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }

    assert version == "0004_hybrid_knowledge"
    assert {"uq_share_user_grantee", "uq_share_tenant_grantee"} <= indexes
