"""Alembic migration tests."""

import asyncio
import os
from pathlib import Path

from alembic.config import Config

from alembic import command
from src.db.session import create_engine
from tests.conftest import table_exists

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


def test_alembic_upgrade_creates_processed_updates_from_empty(
    migration_postgres_url: str,
) -> None:
    os.environ["DATABASE_URL"] = migration_postgres_url
    config = _alembic_config()

    command.upgrade(config, "head")

    async def assert_table_exists() -> bool:
        engine = create_engine(migration_postgres_url)
        try:
            return await table_exists(engine, "processed_updates")
        finally:
            await engine.dispose()

    assert asyncio.run(assert_table_exists())

    async def assert_inventory_tables_exist() -> bool:
        engine = create_engine(migration_postgres_url)
        try:
            products = await table_exists(engine, "products")
            aliases = await table_exists(engine, "aliases")
            stock_ledger = await table_exists(engine, "stock_ledger")
            return products and aliases and stock_ledger
        finally:
            await engine.dispose()

    assert asyncio.run(assert_inventory_tables_exist())

    command.upgrade(config, "head")
