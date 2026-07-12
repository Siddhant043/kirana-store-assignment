"""Analytics integration tests against Postgres."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Bill, BillLine, DraftBill, Product
from src.domain.analytics import AnalyticsService, serialize_daily_close_result
from src.domain.inventory import InventoryService
from src.domain.shop_time import (
    rolling_last_n_ist_days,
    today_ist,
    utc_bounds_for_ist_date,
)

SHOP_TZ = ZoneInfo("Asia/Kolkata")
UTC = UTC

_invoice_counter = 0


async def _create_product(session: AsyncSession, name: str) -> Product:
    service = InventoryService(session)
    result = await service.add_product(
        name=name,
        brand=None,
        mrp_paise=10000,
        cost_price_paise=8000,
        gst_slab=5,
        hsn_code="100630",
        unit_type="packaged",
        reorder_level=Decimal("10"),
    )
    assert result.status == "ok"
    product = await session.get(Product, result.product_id)
    assert product is not None
    return product


async def _seed_bill(
    session: AsyncSession,
    *,
    finalized_at: datetime,
    payment_mode: str,
    subtotal_paise: int,
    cgst_paise: int,
    sgst_paise: int,
    round_off_paise: int,
    total_paise: int,
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
        invoice_number=f"INV-ANALYTICS-{_invoice_counter}",
        payment_mode=payment_mode,
        subtotal_paise=subtotal_paise,
        cgst_paise=cgst_paise,
        sgst_paise=sgst_paise,
        round_off_paise=round_off_paise,
        total_paise=total_paise,
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
async def test_late_night_sale_on_correct_ist_business_day(
    inventory_session: AsyncSession,
) -> None:
    product = await _create_product(inventory_session, "Late Night Rice")
    business_date = date(2026, 3, 15)
    late_night_utc = _ist_datetime(business_date, 23, 45)

    await _seed_bill(
        inventory_session,
        finalized_at=late_night_utc,
        payment_mode="cash",
        subtotal_paise=10000,
        cgst_paise=250,
        sgst_paise=250,
        round_off_paise=0,
        total_paise=10000,
        lines=[(product, Decimal("1"), 10000)],
    )

    service = AnalyticsService(inventory_session)
    same_day = await service.daily_close(business_date)
    next_day = await service.daily_close(business_date + timedelta(days=1))

    assert same_day.bill_count == 1
    assert same_day.total_sales_paise == 10000
    assert next_day.bill_count == 0
    assert next_day.total_sales_paise == 0


@pytest.mark.asyncio
async def test_payment_mode_split_sums_to_total(
    inventory_session: AsyncSession,
) -> None:
    product = await _create_product(inventory_session, "Split Wheat")
    business_date = date(2026, 4, 10)
    midday_utc = _ist_datetime(business_date, 12, 0)

    await _seed_bill(
        inventory_session,
        finalized_at=midday_utc,
        payment_mode="cash",
        subtotal_paise=1000,
        cgst_paise=0,
        sgst_paise=0,
        round_off_paise=0,
        total_paise=1000,
        lines=[(product, Decimal("1"), 1000)],
    )
    await _seed_bill(
        inventory_session,
        finalized_at=midday_utc,
        payment_mode="upi",
        subtotal_paise=2000,
        cgst_paise=0,
        sgst_paise=0,
        round_off_paise=0,
        total_paise=2000,
        lines=[(product, Decimal("2"), 2000)],
    )
    await _seed_bill(
        inventory_session,
        finalized_at=midday_utc,
        payment_mode="khata",
        subtotal_paise=3000,
        cgst_paise=0,
        sgst_paise=0,
        round_off_paise=0,
        total_paise=3000,
        lines=[(product, Decimal("3"), 3000)],
    )

    service = AnalyticsService(inventory_session)
    report = await service.daily_close(business_date)
    split = report.payment_mode_split

    assert split.cash_paise == 1000
    assert split.upi_paise == 2000
    assert split.khata_paise == 3000
    assert split.card_paise == 0
    assert (
        split.cash_paise + split.upi_paise + split.card_paise + split.khata_paise
        == report.total_sales_paise
    )


@pytest.mark.asyncio
async def test_tax_collected_matches_bill_gst_sums(
    inventory_session: AsyncSession,
) -> None:
    product = await _create_product(inventory_session, "Tax Dal")
    business_date = date(2026, 5, 1)
    finalized_at = _ist_datetime(business_date, 10, 30)

    await _seed_bill(
        inventory_session,
        finalized_at=finalized_at,
        payment_mode="cash",
        subtotal_paise=5000,
        cgst_paise=125,
        sgst_paise=125,
        round_off_paise=0,
        total_paise=5000,
        lines=[(product, Decimal("1"), 5000)],
    )
    await _seed_bill(
        inventory_session,
        finalized_at=finalized_at,
        payment_mode="upi",
        subtotal_paise=7000,
        cgst_paise=175,
        sgst_paise=175,
        round_off_paise=0,
        total_paise=7000,
        lines=[(product, Decimal("2"), 7000)],
    )

    service = AnalyticsService(inventory_session)
    report = await service.daily_close(business_date)

    assert report.cgst_paise == 300
    assert report.sgst_paise == 300
    assert report.tax_collected_paise == 600


@pytest.mark.asyncio
async def test_weekly_report_covers_rolling_last_7_ist_days(
    inventory_session: AsyncSession,
) -> None:
    product = await _create_product(inventory_session, "Weekly Sugar")
    window_start, window_end = rolling_last_n_ist_days(7)
    in_window_date = window_end - timedelta(days=3)
    out_of_window_date = window_end - timedelta(days=8)

    start_utc, _ = utc_bounds_for_ist_date(in_window_date)
    old_start_utc, _ = utc_bounds_for_ist_date(out_of_window_date)

    await _seed_bill(
        inventory_session,
        finalized_at=start_utc + timedelta(hours=1),
        payment_mode="cash",
        subtotal_paise=4000,
        cgst_paise=0,
        sgst_paise=0,
        round_off_paise=0,
        total_paise=4000,
        lines=[(product, Decimal("1"), 4000)],
    )
    await _seed_bill(
        inventory_session,
        finalized_at=old_start_utc + timedelta(hours=1),
        payment_mode="cash",
        subtotal_paise=9000,
        cgst_paise=0,
        sgst_paise=0,
        round_off_paise=0,
        total_paise=9000,
        lines=[(product, Decimal("1"), 9000)],
    )

    service = AnalyticsService(inventory_session)
    report = await service.weekly_sales_report()

    assert report.period_start == window_start.isoformat()
    assert report.period_end == window_end.isoformat()
    assert report.bill_count == 1
    assert report.total_sales_paise == 4000


@pytest.mark.asyncio
async def test_daily_close_idempotent_read_returns_identical_figures(
    inventory_session: AsyncSession,
) -> None:
    product = await _create_product(inventory_session, "Idempotent Oil")
    business_date = date(2026, 6, 20)
    finalized_at = _ist_datetime(business_date, 14, 0)

    await _seed_bill(
        inventory_session,
        finalized_at=finalized_at,
        payment_mode="card",
        subtotal_paise=1500,
        cgst_paise=38,
        sgst_paise=37,
        round_off_paise=0,
        total_paise=1500,
        lines=[(product, Decimal("1.5"), 1500)],
    )

    service = AnalyticsService(inventory_session)
    first = serialize_daily_close_result(await service.daily_close(business_date))
    second = serialize_daily_close_result(await service.daily_close(business_date))

    assert first == second


@pytest.mark.asyncio
async def test_weekly_report_works_after_daily_close(
    inventory_session: AsyncSession,
) -> None:
    product = await _create_product(inventory_session, "After Close Tea")
    today = today_ist()
    finalized_at = _ist_datetime(today, 16, 0)

    await _seed_bill(
        inventory_session,
        finalized_at=finalized_at,
        payment_mode="cash",
        subtotal_paise=2500,
        cgst_paise=0,
        sgst_paise=0,
        round_off_paise=0,
        total_paise=2500,
        lines=[(product, Decimal("2"), 2500)],
    )

    service = AnalyticsService(inventory_session)
    daily = await service.daily_close(today)
    weekly = await service.weekly_sales_report()

    assert daily.bill_count == 1
    assert weekly.bill_count == 1
    assert weekly.total_sales_paise == 2500
