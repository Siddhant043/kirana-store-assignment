"""Alembic migration tests."""

import asyncio
import os
from pathlib import Path

from alembic.config import Config

from alembic import command
from src.db.session import create_engine
from tests.conftest import table_exists, view_exists

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

    async def assert_billing_tables_exist() -> bool:
        engine = create_engine(migration_postgres_url)
        try:
            draft_bills = await table_exists(engine, "draft_bills")
            draft_lines = await table_exists(engine, "draft_lines")
            bills = await table_exists(engine, "bills")
            bill_lines = await table_exists(engine, "bill_lines")
            invoice_counters = await table_exists(engine, "invoice_counters")
            return (
                draft_bills
                and draft_lines
                and bills
                and bill_lines
                and invoice_counters
            )
        finally:
            await engine.dispose()

    assert asyncio.run(assert_billing_tables_exist())

    async def assert_khata_tables_exist() -> bool:
        engine = create_engine(migration_postgres_url)
        try:
            customers = await table_exists(engine, "customers")
            khata_entries = await table_exists(engine, "khata_entries")
            return customers and khata_entries
        finally:
            await engine.dispose()

    assert asyncio.run(assert_khata_tables_exist())

    async def assert_analytics_views_exist() -> bool:
        engine = create_engine(migration_postgres_url)
        try:
            daily_summary = await view_exists(engine, "daily_summary")
            sales_report = await view_exists(engine, "sales_report")
            return daily_summary and sales_report
        finally:
            await engine.dispose()

    assert asyncio.run(assert_analytics_views_exist())

    async def assert_shop_profile_table_exists() -> bool:
        engine = create_engine(migration_postgres_url)
        try:
            return await table_exists(engine, "shop_profile")
        finally:
            await engine.dispose()

    assert asyncio.run(assert_shop_profile_table_exists())

    async def assert_preferences_table_exists() -> bool:
        engine = create_engine(migration_postgres_url)
        try:
            return await table_exists(engine, "preferences")
        finally:
            await engine.dispose()

    assert asyncio.run(assert_preferences_table_exists())

    command.upgrade(config, "head")
