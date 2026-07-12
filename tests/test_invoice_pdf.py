"""Invoice PDF generation tests against Postgres."""

from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Bill, BillLine, Customer, DraftBill, KhataEntry, Product
from src.domain.inventory import InventoryService
from src.domain.invoice import InvoiceService
from src.domain.shop_profile import ShopProfileService

OWNER_TELEGRAM_USER_ID = 9001
CHAT_ID = 42

_invoice_counter = 0


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


async def _create_product(
    session: AsyncSession,
    *,
    name: str,
    mrp_paise: int,
    gst_slab: int,
    hsn_code: str,
) -> Product:
    service = InventoryService(session)
    result = await service.add_product(
        name=name,
        brand=None,
        mrp_paise=mrp_paise,
        cost_price_paise=mrp_paise - 100,
        gst_slab=gst_slab,
        hsn_code=hsn_code,
        unit_type="packaged",
        reorder_level=Decimal("10"),
    )
    assert result.status == "ok"
    product = await session.get(Product, result.product_id)
    assert product is not None
    return product


async def _ensure_shop_profile(session: AsyncSession) -> None:
    service = ShopProfileService(session)
    await service.set_shop_profile(
        OWNER_TELEGRAM_USER_ID,
        shop_name="Sidhu Kirana Store",
        address="12 Market Road, Pune",
        gstin="27AAAAA0000A1Z5",
    )


async def _seed_bill(
    session: AsyncSession,
    *,
    payment_mode: str,
    invoice_number: str | None = None,
    lines: list[tuple[Product, Decimal, int, int, int, int, int]],
    subtotal_paise: int,
    cgst_paise: int,
    sgst_paise: int,
    round_off_paise: int,
    total_paise: int,
) -> Bill:
    global _invoice_counter
    _invoice_counter += 1
    number = invoice_number or f"INV-PDF-{_invoice_counter:04d}"

    draft = DraftBill(chat_id=CHAT_ID, status="finalized")
    session.add(draft)
    await session.flush()

    bill = Bill(
        draft_bill_id=draft.draft_bill_id,
        chat_id=CHAT_ID,
        invoice_number=number,
        payment_mode=payment_mode,
        subtotal_paise=subtotal_paise,
        cgst_paise=cgst_paise,
        sgst_paise=sgst_paise,
        round_off_paise=round_off_paise,
        total_paise=total_paise,
        finalized_at=datetime(2026, 7, 12, 10, 30, tzinfo=UTC),
    )
    session.add(bill)
    await session.flush()
    draft.bill_id = bill.bill_id

    for (
        product,
        quantity,
        line_total_paise,
        taxable_paise,
        line_cgst_paise,
        line_sgst_paise,
        _gst_slab,
    ) in lines:
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
                taxable_paise=taxable_paise,
                cgst_paise=line_cgst_paise,
                sgst_paise=line_sgst_paise,
            )
        )
    await session.flush()
    return bill


@pytest.mark.asyncio
async def test_multi_slab_invoice_pdf_contains_hsn_and_tax_breakup(
    inventory_session: AsyncSession,
) -> None:
    await _ensure_shop_profile(inventory_session)
    atta = await _create_product(
        inventory_session,
        name="Aashirvaad Atta 5kg",
        mrp_paise=28000,
        gst_slab=5,
        hsn_code="110100",
    )
    maggi = await _create_product(
        inventory_session,
        name="Maggi Noodles 70g",
        mrp_paise=1400,
        gst_slab=12,
        hsn_code="190230",
    )
    bill = await _seed_bill(
        inventory_session,
        payment_mode="cash",
        invoice_number="INV-PDF-MULTI-SLAB-0001",
        lines=[
            (atta, Decimal("1"), 28000, 26667, 667, 666, 5),
            (maggi, Decimal("2"), 2800, 2500, 150, 150, 12),
        ],
        subtotal_paise=29167,
        cgst_paise=817,
        sgst_paise=816,
        round_off_paise=17,
        total_paise=30800,
    )

    service = InvoiceService(inventory_session)
    result = await service.generate_invoice_pdf(
        bill.bill_id,
        owner_telegram_user_id=OWNER_TELEGRAM_USER_ID,
    )
    assert result.status == "ok"
    assert result.invoice_number == "INV-PDF-MULTI-SLAB-0001"
    text = _extract_pdf_text(result.pdf_bytes)

    assert "Sidhu Kirana Store" in text
    assert "27AAAAA0000A1Z5" in text
    assert "INV-PDF-MULTI-SLAB-0001" in text
    assert "110100" in text
    assert "190230" in text
    assert "5%" in text
    assert "12%" in text
    assert "0.17" in text
    assert "308.00" in text
    assert "Round-off" in text
    assert "cash" in text


@pytest.mark.asyncio
async def test_khata_invoice_pdf_shows_customer_name(
    inventory_session: AsyncSession,
) -> None:
    await _ensure_shop_profile(inventory_session)
    product = await _create_product(
        inventory_session,
        name="Tata Salt 1kg",
        mrp_paise=3000,
        gst_slab=5,
        hsn_code="250100",
    )
    customer = Customer(name="Suresh Kumar", phone="9876543210")
    inventory_session.add(customer)
    await inventory_session.flush()

    bill = await _seed_bill(
        inventory_session,
        payment_mode="khata",
        invoice_number="INV-KHATA-0001",
        lines=[(product, Decimal("1"), 3000, 2857, 72, 71, 5)],
        subtotal_paise=2857,
        cgst_paise=72,
        sgst_paise=71,
        round_off_paise=0,
        total_paise=3000,
    )
    inventory_session.add(
        KhataEntry(
            customer_id=customer.customer_id,
            entry_type="charge",
            amount_paise=3000,
            bill_id=bill.bill_id,
        )
    )
    await inventory_session.flush()

    service = InvoiceService(inventory_session)
    result = await service.generate_invoice_pdf(
        bill.bill_id,
        owner_telegram_user_id=OWNER_TELEGRAM_USER_ID,
    )
    assert result.status == "ok"
    text = _extract_pdf_text(result.pdf_bytes)
    assert "khata" in text
    assert "Suresh Kumar" in text
    assert "250100" in text


@pytest.mark.asyncio
async def test_regenerating_invoice_pdf_yields_identical_extracted_text(
    inventory_session: AsyncSession,
) -> None:
    await _ensure_shop_profile(inventory_session)
    product = await _create_product(
        inventory_session,
        name="Loose Sugar",
        mrp_paise=5000,
        gst_slab=0,
        hsn_code="170199",
    )
    bill = await _seed_bill(
        inventory_session,
        payment_mode="upi",
        invoice_number="INV-STABLE-0001",
        lines=[(product, Decimal("2"), 10000, 10000, 0, 0, 0)],
        subtotal_paise=10000,
        cgst_paise=0,
        sgst_paise=0,
        round_off_paise=0,
        total_paise=10000,
    )

    service = InvoiceService(inventory_session)
    first = await service.generate_invoice_pdf(
        bill.bill_id,
        owner_telegram_user_id=OWNER_TELEGRAM_USER_ID,
    )
    second = await service.generate_invoice_pdf(
        bill.bill_id,
        owner_telegram_user_id=OWNER_TELEGRAM_USER_ID,
    )
    assert first.status == "ok"
    assert second.status == "ok"
    assert _extract_pdf_text(first.pdf_bytes) == _extract_pdf_text(second.pdf_bytes)


@pytest.mark.asyncio
async def test_generate_invoice_pdf_refuses_missing_bill(
    inventory_session: AsyncSession,
) -> None:
    await _ensure_shop_profile(inventory_session)
    service = InvoiceService(inventory_session)
    result = await service.generate_invoice_pdf(
        999999,
        owner_telegram_user_id=OWNER_TELEGRAM_USER_ID,
    )
    assert result.status == "refused"
    assert result.reason == "bill_not_found"


@pytest.mark.asyncio
async def test_generate_invoice_pdf_refuses_missing_shop_profile(
    inventory_session: AsyncSession,
) -> None:
    product = await _create_product(
        inventory_session,
        name="Parle-G",
        mrp_paise=1000,
        gst_slab=18,
        hsn_code="190531",
    )
    bill = await _seed_bill(
        inventory_session,
        payment_mode="card",
        lines=[(product, Decimal("1"), 1000, 847, 77, 76, 18)],
        subtotal_paise=847,
        cgst_paise=77,
        sgst_paise=76,
        round_off_paise=0,
        total_paise=1000,
    )
    service = InvoiceService(inventory_session)
    result = await service.generate_invoice_pdf(
        bill.bill_id,
        owner_telegram_user_id=OWNER_TELEGRAM_USER_ID,
    )
    assert result.status == "refused"
    assert result.reason == "shop_profile_missing"


@pytest.mark.asyncio
async def test_set_and_get_shop_profile_round_trip(
    inventory_session: AsyncSession,
) -> None:
    service = ShopProfileService(inventory_session)
    set_result = await service.set_shop_profile(
        OWNER_TELEGRAM_USER_ID,
        shop_name="My Kirana",
        address="Lane 1",
        gstin="27BBBBB1111B1Z5",
    )
    assert set_result.status == "ok"
    get_result = await service.get_shop_profile(OWNER_TELEGRAM_USER_ID)
    assert get_result.status == "ok"
    assert get_result.shop_name == "My Kirana"
    assert get_result.gstin == "27BBBBB1111B1Z5"
