"""Billing tool-layer integration tests against Postgres."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.db.models import Bill, DraftBill, Product, StockBatch, StockLedger
from src.db.session import create_session_factory
from src.domain.billing import BillingService
from src.domain.inventory import InventoryService


async def _find_product_id(session: AsyncSession, query: str) -> int:
    service = InventoryService(session)
    result = await service.find_product(query)
    assert result.candidates
    return result.candidates[0].product_id


async def _set_product_quantity(
    session: AsyncSession,
    product_id: int,
    quantity: Decimal,
) -> None:
    product = await session.get(Product, product_id)
    assert product is not None
    existing = (
        await session.execute(
            select(StockBatch).where(StockBatch.product_id == product_id)
        )
    ).scalars().all()
    for batch in existing:
        await session.delete(batch)
    await session.flush()
    if quantity > 0:
        session.add(
            StockBatch(
                product_id=product_id,
                batch_qty=quantity,
                cost_price_paise=product.cost_price_paise,
                expiry_date=None,
            )
        )
    product.quantity = quantity
    await session.flush()


@pytest.mark.asyncio
async def test_add_and_view_draft_does_not_change_stock(
    inventory_session: AsyncSession,
) -> None:
    sugar_id = await _find_product_id(inventory_session, "sugar")
    product_before = await inventory_session.get(Product, sugar_id)
    assert product_before is not None
    quantity_before = product_before.quantity

    billing = BillingService(inventory_session, chat_id=1001)
    await billing.open_draft_bill()
    await billing.add_line(sugar_id, Decimal("1"))
    await inventory_session.flush()

    product_after = await inventory_session.get(Product, sugar_id)
    assert product_after is not None
    assert product_after.quantity == quantity_before


@pytest.mark.asyncio
async def test_finalize_multi_line_bill_decrements_stock(
    inventory_session: AsyncSession,
) -> None:
    sugar_id = await _find_product_id(inventory_session, "sugar")
    maggi_id = await _find_product_id(inventory_session, "maggi")
    await _set_product_quantity(inventory_session, sugar_id, Decimal("10"))
    await _set_product_quantity(inventory_session, maggi_id, Decimal("10"))

    billing = BillingService(inventory_session, chat_id=1002)
    await billing.open_draft_bill()
    await billing.add_line(sugar_id, Decimal("2"))
    await billing.add_line(maggi_id, Decimal("4"))
    result = await billing.finalize_bill("upi")
    assert result.status == "ok"
    await inventory_session.flush()

    sugar = await inventory_session.get(Product, sugar_id)
    maggi = await inventory_session.get(Product, maggi_id)
    assert sugar is not None and maggi is not None
    assert sugar.quantity == Decimal("8")
    assert maggi.quantity == Decimal("6")

    ledger_rows = (
        (
            await inventory_session.execute(
                select(StockLedger).where(
                    StockLedger.reason == "sale",
                    StockLedger.product_id.in_([sugar_id, maggi_id]),
                    StockLedger.ref_id == result.bill_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(ledger_rows) == 2


@pytest.mark.asyncio
async def test_finalize_refuses_when_insufficient_stock(
    inventory_session: AsyncSession,
) -> None:
    maggi_id = await _find_product_id(inventory_session, "maggi")
    await _set_product_quantity(inventory_session, maggi_id, Decimal("2"))

    billing = BillingService(inventory_session, chat_id=1003)
    await billing.open_draft_bill()
    await billing.add_line(maggi_id, Decimal("6"))
    result = await billing.finalize_bill("cash")
    assert result.status == "refused"
    assert result.reason == "oversell"

    maggi = await inventory_session.get(Product, maggi_id)
    assert maggi is not None
    assert maggi.quantity == Decimal("2")

    draft = (
        await inventory_session.execute(
            select(DraftBill).where(DraftBill.chat_id == 1003)
        )
    ).scalar_one()
    assert draft.status == "open"


@pytest.mark.asyncio
async def test_finalize_retry_returns_same_bill_id(
    inventory_session: AsyncSession,
) -> None:
    maggi_id = await _find_product_id(inventory_session, "maggi")
    await _set_product_quantity(inventory_session, maggi_id, Decimal("10"))

    billing = BillingService(inventory_session, chat_id=1004)
    await billing.open_draft_bill()
    await billing.add_line(maggi_id, Decimal("2"))

    first = await billing.finalize_bill("upi")
    second = await billing.finalize_bill("upi")
    assert first.status == "ok"
    assert second.status == "ok"
    assert first.bill_id == second.bill_id
    assert first.invoice_number == second.invoice_number
    assert second.idempotent_replay is True

    maggi = await inventory_session.get(Product, maggi_id)
    assert maggi is not None
    assert maggi.quantity == Decimal("8")

    sale_rows = (
        (
            await inventory_session.execute(
                select(StockLedger).where(
                    StockLedger.product_id == maggi_id,
                    StockLedger.reason == "sale",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(sale_rows) == 1


@pytest.mark.asyncio
async def test_finalize_below_cost_requires_confirmation(
    inventory_session: AsyncSession,
) -> None:
    product = Product(
        name="Below Cost Test Item",
        brand="Test",
        mrp_paise=800,
        cost_price_paise=1000,
        gst_slab=12,
        hsn_code="99999999",
        unit_type="packaged",
        quantity=Decimal("5"),
        reorder_level=Decimal("1"),
    )
    inventory_session.add(product)
    await inventory_session.flush()
    await _set_product_quantity(inventory_session, product.product_id, Decimal("5"))

    billing = BillingService(inventory_session, chat_id=1005)
    await billing.open_draft_bill()
    await billing.add_line(product.product_id, Decimal("1"))

    blocked = await billing.finalize_bill("cash")
    assert blocked.status == "requires_confirmation"
    assert blocked.reason == "below_cost"

    confirmed = await billing.finalize_bill("cash", confirm_below_cost=True)
    assert confirmed.status == "ok"


@pytest.mark.asyncio
async def test_concurrent_finalize_same_sku_never_negative(
    migrated_engine: AsyncEngine,
) -> None:
    session_factory = create_session_factory(migrated_engine)

    async with session_factory() as setup_session:
        async with setup_session.begin():
            maggi_id = await _find_product_id(setup_session, "maggi")
            await _set_product_quantity(setup_session, maggi_id, Decimal("5"))

    async def finalize_for_chat(chat_id: int) -> str:
        async with session_factory() as setup_session:
            async with setup_session.begin():
                maggi_id = await _find_product_id(setup_session, "maggi")
                billing = BillingService(setup_session, chat_id=chat_id)
                await billing.open_draft_bill()
                await billing.add_line(maggi_id, Decimal("3"))

        async with session_factory() as session:
            async with session.begin():
                billing = BillingService(session, chat_id=chat_id)
                result = await billing.finalize_bill("cash")
                if result.status == "ok":
                    return "ok"
                return result.reason

    outcomes = await asyncio.gather(
        finalize_for_chat(2001),
        finalize_for_chat(2002),
    )
    assert sorted(outcomes) == ["ok", "oversell"]

    async with session_factory() as session:
        maggi_id = await _find_product_id(session, "maggi")
        maggi = await session.get(Product, maggi_id)
        assert maggi is not None
        assert maggi.quantity >= Decimal("0")

        sale_rows = (
            (
                await session.execute(
                    select(StockLedger).where(
                        StockLedger.product_id == maggi_id,
                        StockLedger.reason == "sale",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(sale_rows) == 1
        assert sum((row.delta for row in sale_rows), Decimal("0")) == Decimal("-3")

        bills = (
            (
                await session.execute(
                    select(Bill).where(Bill.chat_id.in_([2001, 2002]))
                )
            )
            .scalars()
            .all()
        )
        assert len(bills) == 1
