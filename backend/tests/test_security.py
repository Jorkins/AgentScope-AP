import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.platform.models import Base, Membership, Tenant, User
from app.platform.security import validate_token_membership


@pytest.mark.asyncio
async def test_membership_validator_checks_current_database_membership():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add_all(
            [
                User(id=1, username="alice", password_hash="hash"),
                Tenant(id=7, name="team", owner_id="alice"),
                Membership(id=1, tenant_id=7, username="alice", role="owner"),
            ]
        )
        await session.commit()

    assert await validate_token_membership(session_factory, "alice", "7") is True

    async with session_factory() as session:
        membership = await session.get(Membership, 1)
        await session.delete(membership)
        await session.commit()

    assert await validate_token_membership(session_factory, "alice", "7") is False
    await engine.dispose()
