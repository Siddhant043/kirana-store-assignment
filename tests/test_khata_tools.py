"""Khata tool-layer integration tests against Postgres."""

from decimal import Decimal

import pytest
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Customer, KhataEntry, Product, StockLedger
from src.domain.billing import BillingService
from src.domain.inventory import InventoryService
from src.domain.khata import KhataService


async def _create_customer(
    session: AsyncSession,
    name: str,
    phone: str | None = None,
) -> Customer:
    customer = Customer(name=name, phone=phone)
    session.add(customer)
    await session.flush()
    return customer


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
    product.quantity = quantity
    await session.flush()


async def _manual_balance(session: AsyncSession, customer_id: int) -> int:
    signed_amount = case(
        (KhataEntry.entry_type == "charge", KhataEntry.amount_paise),
        else_=-KhataEntry.amount_paise,
    )
    result = await session.execute(
        select(func.coalesce(func.sum(signed_amount), 0)).where(
            KhataEntry.customer_id == customer_id
        )
    )
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_find_or_create_customer_new_name_requires_confirmation(
    inventory_session: AsyncSession,
) -> None:
    service = KhataService(inventory_session)
    result = await service.find_or_create_customer("Suresh Kumar")
    assert result.status == "requires_confirmation"
    assert result.reason == "new_customer"
    assert result.name == "Suresh Kumar"

    customers = (await inventory_session.execute(select(Customer))).scalars().all()
    assert customers == []


@pytest.mark.asyncio
async def test_find_or_create_customer_creates_after_confirm(
    inventory_session: AsyncSession,
) -> None:
    service = KhataService(inventory_session)
    result = await service.find_or_create_customer(
        "Suresh Kumar",
        "9876543210",
        confirm_create=True,
    )
    assert result.status == "ok"
    assert result.customer_id is not None
    assert result.ambiguous is False

    customer = await inventory_session.get(Customer, result.customer_id)
    assert customer is not None
    assert customer.name == "Suresh Kumar"
    assert customer.phone == "9876543210"


@pytest.mark.asyncio
async def test_find_or_create_customer_name_collision_ambiguous(
    inventory_session: AsyncSession,
) -> None:
    await _create_customer(inventory_session, "Ramesh", "1111111111")
    await _create_customer(inventory_session, "Ramesh", "2222222222")

    service = KhataService(inventory_session)
    result = await service.find_or_create_customer("Ramesh")
    assert result.status == "ambiguous"
    assert result.ambiguous is True
    assert len(result.candidates) >= 2
    assert result.customer_id is None


@pytest.mark.asyncio
async def test_record_payment_refused_when_customer_not_found(
    inventory_session: AsyncSession,
) -> None:
    service = KhataService(inventory_session)
    result = await service.record_payment(999_999, 30000)
    assert result.status == "refused"
    assert result.reason == "khata_not_found"


@pytest.mark.asyncio
async def test_record_payment_overpayment_requires_confirmation(
    inventory_session: AsyncSession,
) -> None:
    customer = await _create_customer(inventory_session, "Ramesh")
    khata = KhataService(inventory_session)
    charge = await khata.add_khata_charge(customer.customer_id, 50000)
    assert charge.status == "ok"

    result = await khata.record_payment(customer.customer_id, 80000)
    assert result.status == "requires_confirmation"
    assert result.reason == "overpayment"
    assert result.balance_paise == 50000
    assert result.payment_paise == 80000


@pytest.mark.asyncio
async def test_record_payment_reduces_balance(
    inventory_session: AsyncSession,
) -> None:
    customer = await _create_customer(inventory_session, "Ramesh")
    khata = KhataService(inventory_session)
    await khata.add_khata_charge(customer.customer_id, 50000)
    payment = await khata.record_payment(customer.customer_id, 30000)
    assert payment.status == "ok"
    assert payment.balance_paise == 20000


@pytest.mark.asyncio
async def test_balance_is_sum_of_charges_and_payments(
    inventory_session: AsyncSession,
) -> None:
    customer = await _create_customer(inventory_session, "Ramesh")
    khata = KhataService(inventory_session)
    await khata.add_khata_charge(customer.customer_id, 50000)
    await khata.record_payment(customer.customer_id, 30000)
    await khata.add_khata_charge(customer.customer_id, 10000)

    balance = await khata.get_khata_balance(customer.customer_id)
    assert balance.status == "ok"
    assert balance.balance_paise == 30000
    assert balance.balance_paise == await _manual_balance(
        inventory_session,
        customer.customer_id,
    )


@pytest.mark.asyncio
async def test_credit_finalize_decrements_stock_and_writes_one_charge(
    inventory_session: AsyncSession,
) -> None:
    customer = await _create_customer(inventory_session, "Ramesh")
    maggi_id = await _find_product_id(inventory_session, "maggi")
    await _set_product_quantity(inventory_session, maggi_id, Decimal("10"))

    billing = BillingService(inventory_session, chat_id=3001)
    await billing.open_draft_bill()
    await billing.add_line(maggi_id, Decimal("2"))
    result = await billing.finalize_bill("khata", customer_id=customer.customer_id)
    assert result.status == "ok"
    await inventory_session.flush()

    maggi = await inventory_session.get(Product, maggi_id)
    assert maggi is not None
    assert maggi.quantity == Decimal("8")

    sale_rows = (
        (
            await inventory_session.execute(
                select(StockLedger).where(
                    StockLedger.product_id == maggi_id,
                    StockLedger.reason == "sale",
                    StockLedger.ref_id == result.bill_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(sale_rows) == 1

    charge_rows = (
        (
            await inventory_session.execute(
                select(KhataEntry).where(
                    KhataEntry.customer_id == customer.customer_id,
                    KhataEntry.entry_type == "charge",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(charge_rows) == 1
    assert charge_rows[0].bill_id == result.bill_id
    assert charge_rows[0].amount_paise == result.total_paise

    khata = KhataService(inventory_session)
    balance = await khata.get_khata_balance(customer.customer_id)
    assert balance.status == "ok"
    assert balance.balance_paise == result.total_paise


@pytest.mark.asyncio
async def test_credit_finalize_retry_does_not_double_charge(
    inventory_session: AsyncSession,
) -> None:
    customer = await _create_customer(inventory_session, "Ramesh")
    maggi_id = await _find_product_id(inventory_session, "maggi")
    await _set_product_quantity(inventory_session, maggi_id, Decimal("10"))

    billing = BillingService(inventory_session, chat_id=3002)
    await billing.open_draft_bill()
    await billing.add_line(maggi_id, Decimal("1"))

    first = await billing.finalize_bill("khata", customer_id=customer.customer_id)
    second = await billing.finalize_bill("khata", customer_id=customer.customer_id)
    assert first.status == "ok"
    assert second.status == "ok"
    assert first.bill_id == second.bill_id
    assert second.idempotent_replay is True
    await inventory_session.flush()

    maggi = await inventory_session.get(Product, maggi_id)
    assert maggi is not None
    assert maggi.quantity == Decimal("9")

    charge_rows = (
        (
            await inventory_session.execute(
                select(KhataEntry).where(KhataEntry.customer_id == customer.customer_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(charge_rows) == 1

    sale_rows = (
        (
            await inventory_session.execute(
                select(StockLedger).where(
                    StockLedger.reason == "sale",
                    StockLedger.ref_id == first.bill_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(sale_rows) == 1
