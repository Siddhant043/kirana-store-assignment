"""Khata balance-scan tests for reminder threshold filtering."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Customer, KhataEntry
from src.domain.khata import (
    KhataService,
    ListCustomersAboveThresholdResult,
    RefusedResult,
)


async def _create_customer(
    session: AsyncSession,
    name: str,
    phone: str | None = None,
) -> Customer:
    customer = Customer(name=name, phone=phone)
    session.add(customer)
    await session.flush()
    return customer


async def _add_charge(
    session: AsyncSession,
    customer_id: int,
    amount_paise: int,
) -> None:
    session.add(
        KhataEntry(
            customer_id=customer_id,
            entry_type="charge",
            amount_paise=amount_paise,
        )
    )
    await session.flush()


async def _add_payment(
    session: AsyncSession,
    customer_id: int,
    amount_paise: int,
) -> None:
    session.add(
        KhataEntry(
            customer_id=customer_id,
            entry_type="payment",
            amount_paise=amount_paise,
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_list_customers_above_threshold_filters_and_orders(
    inventory_session: AsyncSession,
) -> None:
    above = await _create_customer(inventory_session, "ScanAbove Ramesh", "1111111111")
    exact = await _create_customer(inventory_session, "ScanExact Suresh", "2222222222")
    below = await _create_customer(inventory_session, "ScanBelow Mahesh", "3333333333")
    zero = await _create_customer(inventory_session, "ScanZero Naresh", None)

    await _add_charge(inventory_session, above.customer_id, 100_000)
    await _add_payment(inventory_session, above.customer_id, 10_000)  # 90000
    await _add_charge(inventory_session, exact.customer_id, 50_000)
    await _add_charge(inventory_session, below.customer_id, 49_999)
    await _add_charge(inventory_session, zero.customer_id, 20_000)
    await _add_payment(inventory_session, zero.customer_id, 20_000)  # 0

    service = KhataService(inventory_session)
    result = await service.list_customers_above_threshold(50_000)

    assert isinstance(result, ListCustomersAboveThresholdResult)
    assert result.status == "ok"
    assert result.threshold_paise == 50_000
    by_name = {row.name: row for row in result.customers}
    assert "ScanAbove Ramesh" in by_name
    assert "ScanExact Suresh" in by_name
    assert "ScanBelow Mahesh" not in by_name
    assert "ScanZero Naresh" not in by_name
    assert by_name["ScanAbove Ramesh"].balance_paise == 90_000
    assert by_name["ScanAbove Ramesh"].phone == "1111111111"
    assert by_name["ScanExact Suresh"].balance_paise == 50_000
    assert by_name["ScanExact Suresh"].customer_id == exact.customer_id
    seeded_order = [
        row.name
        for row in result.customers
        if row.name in {"ScanAbove Ramesh", "ScanExact Suresh"}
    ]
    assert seeded_order == ["ScanAbove Ramesh", "ScanExact Suresh"]


@pytest.mark.asyncio
async def test_list_customers_above_threshold_refuses_negative(
    inventory_session: AsyncSession,
) -> None:
    service = KhataService(inventory_session)
    result = await service.list_customers_above_threshold(-1)
    assert isinstance(result, RefusedResult)
    assert result.reason == "invalid_threshold_paise"
