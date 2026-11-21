"""串行升级 AP 自有表与 AgentScope 内核表。"""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from agentscope.app.storage import AsyncSQLAlchemyStorage
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings

_BACKEND = Path(__file__).resolve().parents[1]


async def migrate_database(database_url: str) -> None:
    """先迁移 AP 表，再通过内核自带迁移升级其 schema。"""
    config = Config(str(_BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: set(
                    inspect(sync_connection).get_table_names()
                )
            )
    finally:
        await engine.dispose()

    legacy_tables = {
        "ap_users",
        "ap_tenants",
        "ap_memberships",
        "ap_resource_shares",
    }
    if legacy_tables <= tables and "ap_alembic_version" not in tables:
        await asyncio.to_thread(command.stamp, config, "0001_platform_baseline")
    await asyncio.to_thread(command.upgrade, config, "head")

    async with AsyncSQLAlchemyStorage(
        url=database_url,
        create_tables=False,
        auto_migrate=True,
    ):
        pass


def main() -> None:
    asyncio.run(migrate_database(settings.DATABASE_URL))


if __name__ == "__main__":
    main()
