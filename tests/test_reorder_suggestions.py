"""Reorder suggestions ranked by sales velocity (Postgres testcontainer)."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Bill, BillLine, DraftBill, Product
from src.domain.analytics import AnalyticsService
from src.domain.inventory import InventoryService
from src.domain.shop_time import rolling_last_n_ist_days

SHOP_TZ = ZoneInfo("Asia/Kolkata")

_invoice_counter = 0


async def _create_product(
    session: AsyncSession,
    name: str,
    *,
    reorder_level: Decimal = Decimal("10"),
) -> Product:
    service = InventoryService(session)
    result = await service.add_product(
        name=name,
        brand=None,
        mrp_paise=10000,
        cost_price_paise=8000,
        gst_slab=5,
        hsn_code="100630",
        unit_type="packaged",
        reorder_level=reorder_level,
    )
    assert result.status == "ok"
    product = await session.get(Product, result.product_id)
    assert product is not None
    return product


async def _set_quantity(
    session: AsyncSession,
    product: Product,
    quantity: Decimal,
) -> None:
    if quantity > 0:
        await InventoryService(session).receive_stock(
            product_id=product.product_id,
            quantity=quantity,
        )
    await session.refresh(product)


async def _seed_bill(
    session: AsyncSession,
    *,
    finalized_at: datetime,
    lines: list[tuple[Product, Decimal, int]],
) -> Bill:
    global _invoice_counter
    _invoice_counter += 1

    draft = DraftBill(chat_id=1, status="finalized")
    session.add(draft)
    await session.flush()

    bill = Bill(
        draft_bill_id=draft.draft_bill_id,
        chat_id=1,
        invoice_number=f"INV-REORDER-{_invoice_counter}",
        payment_mode="cash",
        subtotal_paise=10000,
        cgst_paise=0,
        sgst_paise=0,
        round_off_paise=0,
        total_paise=10000,
        finalized_at=finalized_at,
    )
    session.add(bill)
    await session.flush()
    draft.bill_id = bill.bill_id

    for product, quantity, line_total_paise in lines:
        session.add(
            BillLine(
                bill_id=bill.bill_id,
                product_id=product.product_id,
                quantity=quantity,
                mrp_paise=product.mrp_paise,
                cost_price_paise=product.cost_price_paise,
                gst_slab=product.gst_slab,
                hsn_code=product.hsn_code,
                line_total_paise=line_total_paise,
                taxable_paise=line_total_paise,
                cgst_paise=0,
                sgst_paise=0,
            )
        )

    await session.flush()
    return bill


def _ist_datetime(business_date: date, hour: int, minute: int) -> datetime:
    local_time = datetime.combine(
        business_date,
        time(hour=hour, minute=minute),
        tzinfo=SHOP_TZ,
    )
    return local_time.astimezone(UTC)


@pytest.mark.asyncio
async def test_fast_moving_low_stock_ranks_above_slow_moving(
    inventory_session: AsyncSession,
) -> None:
    fast = await _create_product(inventory_session, "Fast Moving Atta")
    slow = await _create_product(inventory_session, "Slow Moving Atta")
    await _set_quantity(inventory_session, fast, Decimal("5"))
    await _set_quantity(inventory_session, slow, Decimal("5"))

    window_start, _window_end = rolling_last_n_ist_days(7)
    sale_day = window_start + timedelta(days=1)
    finalized_at = _ist_datetime(sale_day, 12, 0)

    await _seed_bill(
        inventory_session,
        finalized_at=finalized_at,
        lines=[(fast, Decimal("70"), 70000)],
    )
    await _seed_bill(
        inventory_session,
        finalized_at=finalized_at,
        lines=[(slow, Decimal("7"), 7000)],
    )

    result = await AnalyticsService(inventory_session).reorder_suggestions()

    by_id = {item.product_id: item for item in result.suggestions}
    assert fast.product_id in by_id
    assert slow.product_id in by_id

    ranked_ids = [
        item.product_id
        for item in result.suggestions
        if item.product_id in {fast.product_id, slow.product_id}
    ]
    assert ranked_ids[0] == fast.product_id
    assert ranked_ids[1] == slow.product_id

    assert by_id[fast.product_id].basis == "sales_velocity"
    assert by_id[slow.product_id].basis == "sales_velocity"
    assert Decimal(by_id[fast.product_id].days_of_stock or "0") < Decimal(
        by_id[slow.product_id].days_of_stock or "0"
    )


@pytest.mark.asyncio
async def test_zero_sales_history_falls_back_to_reorder_level(
    inventory_session: AsyncSession,
) -> None:
    lonely = await _create_product(inventory_session, "No Sales Oil")
    await _set_quantity(inventory_session, lonely, Decimal("3"))

    result = await AnalyticsService(inventory_session).reorder_suggestions()

    match = next(
        item for item in result.suggestions if item.product_id == lonely.product_id
    )
    assert match.basis == "reorder_level"
    assert match.days_of_stock is None
    assert match.daily_velocity is None
    assert match.sold_quantity_in_window == "0"


@pytest.mark.asyncio
async def test_zero_sales_well_stocked_not_suggested(
    inventory_session: AsyncSession,
) -> None:
    healthy = await _create_product(
        inventory_session,
        "Healthy Stock Soap",
        reorder_level=Decimal("10"),
    )
    await _set_quantity(inventory_session, healthy, Decimal("50"))

    result = await AnalyticsService(inventory_session).reorder_suggestions()

    suggested_ids = {item.product_id for item in result.suggestions}
    assert healthy.product_id not in suggested_ids
