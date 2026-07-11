"""Shared pytest fixtures."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from testcontainers.postgres import PostgresContainer

from src.db.models import Base
from src.db.session import create_engine, create_session_factory


@pytest.fixture(scope="session")
def postgres_url() -> str:
    with PostgresContainer("postgres:16", driver=None) as postgres:
        host = postgres.get_container_host_ip()
        port = postgres.get_exposed_port(5432)
        user = postgres.username
        password = postgres.password
        dbname = postgres.dbname
        yield f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}"


@pytest.fixture(scope="session")
def migration_postgres_url() -> str:
    with PostgresContainer("postgres:16", driver=None) as postgres:
        host = postgres.get_container_host_ip()
        port = postgres.get_exposed_port(5432)
        user = postgres.username
        password = postgres.password
        dbname = postgres.dbname
        yield f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}"


@pytest.fixture
async def db_engine(postgres_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(
    db_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    session_factory = create_session_factory(db_engine)
    async with session_factory() as session:
        yield session
        await session.rollback()


async def table_exists(engine: AsyncEngine, table_name: str) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :name"
                ")"
            ),
            {"name": table_name},
        )
        return bool(result.scalar())
