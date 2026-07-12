"""Shared pytest fixtures."""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from testcontainers.postgres import PostgresContainer

from alembic import command
from src.db.session import create_engine, create_session_factory

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


def _alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    os.environ["DATABASE_URL"] = database_url
    return config


@pytest.fixture(scope="session")
def migrated_postgres_url(postgres_url: str) -> str:
    config = _alembic_config(postgres_url)
    command.upgrade(config, "head")
    return postgres_url


@pytest.fixture
async def migrated_engine(migrated_postgres_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(migrated_postgres_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def inventory_session(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    session_factory = create_session_factory(migrated_engine)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def db_engine(migrated_postgres_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(migrated_postgres_url)
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


async def view_exists(engine: AsyncEngine, view_name: str) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM information_schema.views "
                "WHERE table_schema = 'public' AND table_name = :name"
                ")"
            ),
            {"name": view_name},
        )
        return bool(result.scalar())
