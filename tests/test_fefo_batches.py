"""FEFO Batch tracking: receive, oversell, expire, multi-batch, concurrency."""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.db.models import Product, StockBatch, StockLedger
from src.db.session import create_session_factory
from src.domain.billing import BillingService
from src.domain.inventory import InventoryService
from src.domain.shop_time import today_ist


async def _create_product(
    session: AsyncSession,
    name: str,
    *,
    cost_price_paise: int = 8000,
) -> Product:
    service = InventoryService(session)
    result = await service.add_product(
        name=name,
        brand=None,
        mrp_paise=10000,
        cost_price_paise=cost_price_paise,
        gst_slab=5,
        hsn_code="100630",
        unit_type="packaged",
        reorder_level=Decimal("10"),
    )
    assert result.status == "ok"
    product = await session.get(Product, result.product_id)
    assert product is not None
    return product


@pytest.mark.asyncio
async def test_receive_stock_creates_two_distinct_batches(
    inventory_session: AsyncSession,
) -> None:
    product = await _create_product(inventory_session, "FEFO Milk")
    service = InventoryService(inventory_session)
    today = today_ist()

    first = await service.receive_stock(
        product_id=product.product_id,
        quantity=Decimal("10"),
        cost_price_paise=7000,
        expiry_date=today + timedelta(days=5),
    )
    second = await service.receive_stock(
        product_id=product.product_id,
        quantity=Decimal("20"),
        cost_price_paise=7500,
        expiry_date=today + timedelta(days=20),
    )
    await inventory_session.flush()

    batches = (
        (
            await inventory_session.execute(
                select(StockBatch)
                .where(StockBatch.product_id == product.product_id)
                .order_by(StockBatch.batch_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(batches) == 2
    assert first.batch_id != second.batch_id
    assert batches[0].batch_qty == Decimal("10")
    assert batches[0].cost_price_paise == 7000
    assert batches[0].expiry_date == today + timedelta(days=5)
    assert batches[1].batch_qty == Decimal("20")
    assert batches[1].cost_price_paise == 7500
    assert batches[1].expiry_date == today + timedelta(days=20)

    await inventory_session.refresh(product)
    assert product.quantity == Decimal("30")
    assert product.cost_price_paise == 8000


@pytest.mark.asyncio
async def test_oversell_refuses_above_non_expired_sum(
    inventory_session: AsyncSession,
) -> None:
    product = await _create_product(inventory_session, "Oversell Paneer")
    service = InventoryService(inventory_session)
    today = today_ist()
    await service.receive_stock(
        product_id=product.product_id,
        quantity=Decimal("5"),
        expiry_date=today + timedelta(days=10),
    )

    billing_refuse = BillingService(inventory_session, chat_id=5101)
    await billing_refuse.open_draft_bill()
    await billing_refuse.add_line(product.product_id, Decimal("6"))
    refused = await billing_refuse.finalize_bill("cash")
    assert refused.status == "refused"
    assert refused.reason == "oversell"

    billing_ok = BillingService(inventory_session, chat_id=51011)
    await billing_ok.open_draft_bill()
    await billing_ok.add_line(product.product_id, Decimal("5"))
    ok = await billing_ok.finalize_bill("cash")
    assert ok.status == "ok"
    await inventory_session.refresh(product)
    assert product.quantity == Decimal("0")


@pytest.mark.asyncio
async def test_expired_batch_excluded_from_sellable_stock(
    inventory_session: AsyncSession,
) -> None:
    product = await _create_product(inventory_session, "Expiry Yogurt")
    service = InventoryService(inventory_session)
    today = today_ist()
    expired = await service.receive_stock(
        product_id=product.product_id,
        quantity=Decimal("10"),
        expiry_date=today - timedelta(days=1),
    )
    fresh = await service.receive_stock(
        product_id=product.product_id,
        quantity=Decimal("4"),
        expiry_date=today + timedelta(days=14),
    )

    billing = BillingService(inventory_session, chat_id=5102)
    await billing.open_draft_bill()
    await billing.add_line(product.product_id, Decimal("4"))
    ok = await billing.finalize_bill("upi")
    assert ok.status == "ok"

    expired_batch = await inventory_session.get(StockBatch, expired.batch_id)
    fresh_batch = await inventory_session.get(StockBatch, fresh.batch_id)
    assert expired_batch is not None and fresh_batch is not None
    assert expired_batch.batch_qty == Decimal("10")
    assert fresh_batch.batch_qty == Decimal("0")

    await billing.open_draft_bill()
    await billing.add_line(product.product_id, Decimal("1"))
    refused = await billing.finalize_bill("cash")
    assert refused.status == "refused"
    assert refused.reason == "oversell"
    assert expired_batch.batch_qty == Decimal("10")


@pytest.mark.asyncio
async def test_multi_batch_fefo_consumes_nearest_expiry_first(
    inventory_session: AsyncSession,
) -> None:
    product = await _create_product(inventory_session, "FEFO Bread")
    service = InventoryService(inventory_session)
    today = today_ist()
    nearer = await service.receive_stock(
        product_id=product.product_id,
        quantity=Decimal("3"),
        expiry_date=today + timedelta(days=2),
    )
    later = await service.receive_stock(
        product_id=product.product_id,
        quantity=Decimal("5"),
        expiry_date=today + timedelta(days=10),
    )

    billing = BillingService(inventory_session, chat_id=5103)
    await billing.open_draft_bill()
    await billing.add_line(product.product_id, Decimal("5"))
    result = await billing.finalize_bill("card")
    assert result.status == "ok"

    nearer_batch = await inventory_session.get(StockBatch, nearer.batch_id)
    later_batch = await inventory_session.get(StockBatch, later.batch_id)
    assert nearer_batch is not None and later_batch is not None
    assert nearer_batch.batch_qty == Decimal("0")
    assert later_batch.batch_qty == Decimal("3")

    ledger_rows = (
        (
            await inventory_session.execute(
                select(StockLedger).where(
                    StockLedger.product_id == product.product_id,
                    StockLedger.reason == "sale",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(ledger_rows) == 2
    assert sorted(abs(row.delta) for row in ledger_rows) == [
        Decimal("2"),
        Decimal("3"),
    ]
    await inventory_session.refresh(product)
    assert product.quantity == Decimal("3")


@pytest.mark.asyncio
async def test_concurrent_finalize_never_drives_batch_negative(
    migrated_engine: AsyncEngine,
) -> None:
    session_factory = create_session_factory(migrated_engine)

    async with session_factory() as setup_session:
        async with setup_session.begin():
            product = await _create_product(setup_session, "Concurrent Curd")
            product_id = product.product_id
            service = InventoryService(setup_session)
            today = today_ist()
            await service.receive_stock(
                product_id=product_id,
                quantity=Decimal("5"),
                expiry_date=today + timedelta(days=7),
            )

    async def finalize_for_chat(chat_id: int) -> str:
        async with session_factory() as draft_session:
            async with draft_session.begin():
                billing = BillingService(draft_session, chat_id=chat_id)
                await billing.open_draft_bill()
                await billing.add_line(product_id, Decimal("3"))

        async with session_factory() as session:
            async with session.begin():
                billing = BillingService(session, chat_id=chat_id)
                result = await billing.finalize_bill("cash")
                if result.status == "ok":
                    return "ok"
                return result.reason

    outcomes = await asyncio.gather(
        finalize_for_chat(5201),
        finalize_for_chat(5202),
    )
    assert sorted(outcomes) == ["ok", "oversell"]

    async with session_factory() as session:
        product = await session.get(Product, product_id)
        assert product is not None
        assert product.quantity >= Decimal("0")
        batches = (
            (
                await session.execute(
                    select(StockBatch).where(StockBatch.product_id == product_id)
                )
            )
            .scalars()
            .all()
        )
        assert all(batch.batch_qty >= 0 for batch in batches)
        batch_total = sum((batch.batch_qty for batch in batches), Decimal("0"))
        assert batch_total == product.quantity

        sale_rows = (
            (
                await session.execute(
                    select(StockLedger).where(
                        StockLedger.product_id == product_id,
                        StockLedger.reason == "sale",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert sum((row.delta for row in sale_rows), Decimal("0")) == Decimal("-3")


@pytest.mark.asyncio
async def test_list_expiring_soon_surfaces_near_expiry_batches(
    inventory_session: AsyncSession,
) -> None:
    product = await _create_product(inventory_session, "Soon Milk")
    service = InventoryService(inventory_session)
    today = today_ist()
    near = await service.receive_stock(
        product_id=product.product_id,
        quantity=Decimal("2"),
        expiry_date=today + timedelta(days=3),
    )
    await service.receive_stock(
        product_id=product.product_id,
        quantity=Decimal("8"),
        expiry_date=today + timedelta(days=40),
    )
    await service.receive_stock(
        product_id=product.product_id,
        quantity=Decimal("1"),
        expiry_date=None,
    )

    result = await service.list_expiring_soon(within_days=7)
    batch_ids = {batch.batch_id for batch in result.batches}
    assert near.batch_id in batch_ids
    assert all(
        today <= date.fromisoformat(batch.expiry_date) <= today + timedelta(days=7)
        for batch in result.batches
    )
