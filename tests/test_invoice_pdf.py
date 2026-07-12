"""Invoice PDF generation tests against Postgres."""

from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Bill, BillLine, Customer, DraftBill, KhataEntry, Product
from src.domain.inventory import InventoryService
from src.domain.invoice import (
    InvoicePdfResult,
    InvoiceService,
    render_invoice_html,
)
from src.domain.shop_profile import (
    ShopProfileResult,
    ShopProfileService,
)

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
    assert get_result.shop_name == "My Kirana"  # type: ignore[union-attr]
    assert get_result.gstin == "27BBBBB1111B1Z5"  # type: ignore[union-attr]
    assert get_result.logo_url is None  # type: ignore[union-attr]
    assert get_result.accent_color is None  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_set_shop_profile_persists_logo_and_accent(
    inventory_session: AsyncSession,
) -> None:
    service = ShopProfileService(inventory_session)
    logo = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    set_result = await service.set_shop_profile(
        OWNER_TELEGRAM_USER_ID,
        shop_name="Branded Kirana",
        address="Brand Lane",
        gstin="27CCCCC2222C2Z5",
        logo_url=logo,
        accent_color="#1a73e8",
    )
    assert set_result.status == "ok"
    assert set_result.logo_url == logo  # type: ignore[union-attr]
    assert set_result.accent_color == "#1A73E8"  # type: ignore[union-attr]

    got = await service.get_shop_profile(OWNER_TELEGRAM_USER_ID)
    assert got.status == "ok"
    assert got.logo_url == logo  # type: ignore[union-attr]
    assert got.accent_color == "#1A73E8"  # type: ignore[union-attr]

    # Name-only update preserves branding when logo/accent omitted.
    await service.set_shop_profile(
        OWNER_TELEGRAM_USER_ID,
        shop_name="Branded Kirana Renamed",
        address="Brand Lane",
        gstin="27CCCCC2222C2Z5",
    )
    preserved = await service.get_shop_profile(OWNER_TELEGRAM_USER_ID)
    assert preserved.status == "ok"
    assert preserved.shop_name == "Branded Kirana Renamed"  # type: ignore[union-attr]
    assert preserved.logo_url == logo  # type: ignore[union-attr]
    assert preserved.accent_color == "#1A73E8"  # type: ignore[union-attr]

    cleared = await service.set_shop_profile(
        OWNER_TELEGRAM_USER_ID,
        shop_name="Branded Kirana Renamed",
        address="Brand Lane",
        gstin="27CCCCC2222C2Z5",
        logo_url="",
        accent_color="",
    )
    assert cleared.status == "ok"
    assert cleared.logo_url is None  # type: ignore[union-attr]
    assert cleared.accent_color is None  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_invalid_accent_color_refused(
    inventory_session: AsyncSession,
) -> None:
    service = ShopProfileService(inventory_session)
    result = await service.set_shop_profile(
        OWNER_TELEGRAM_USER_ID,
        shop_name="Bad Color Shop",
        accent_color="blue",
    )
    assert result.status == "refused"
    assert result.reason == "invalid_accent_color"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_branded_invoice_html_includes_logo_and_accent(
    inventory_session: AsyncSession,
) -> None:
    logo = "https://example.com/logo.png"
    shop = ShopProfileService(inventory_session)
    await shop.set_shop_profile(
        OWNER_TELEGRAM_USER_ID,
        shop_name="Accent Shop",
        address="1 Color St",
        gstin="27DDDDD3333D3Z5",
        logo_url=logo,
        accent_color="#C45C26",
    )
    product = await _create_product(
        inventory_session,
        name="Brand Item",
        mrp_paise=2000,
        gst_slab=5,
        hsn_code="210690",
    )
    bill = await _seed_bill(
        inventory_session,
        payment_mode="upi",
        lines=[(product, Decimal("1"), 2000, 1905, 48, 47, 5)],
        subtotal_paise=1905,
        cgst_paise=48,
        sgst_paise=47,
        round_off_paise=0,
        total_paise=2000,
    )
    invoice_service = InvoiceService(inventory_session)
    profile = await shop.get_shop_profile(OWNER_TELEGRAM_USER_ID)
    assert isinstance(profile, ShopProfileResult)
    pdf_result = await invoice_service.generate_invoice_pdf(
        bill.bill_id,
        owner_telegram_user_id=OWNER_TELEGRAM_USER_ID,
    )
    assert isinstance(pdf_result, InvoicePdfResult)

    bill_loaded = await invoice_service._load_bill_with_lines(bill.bill_id)
    assert bill_loaded is not None
    view = invoice_service._build_invoice_view(
        bill_loaded,
        shop_name=profile.shop_name,
        shop_address=profile.address,
        shop_gstin=profile.gstin,
        logo_url=profile.logo_url,
        accent_color=profile.accent_color,
        payment_reference=None,
    )
    html = render_invoice_html(view)
    assert logo in html
    assert "#C45C26" in html
    assert "HSN Code" in html
    assert "CGST" in html
    assert "SGST" in html
    assert "Round-off" in html


def _gst_mandated_snippets(pdf_text: str) -> list[str]:
    """Stable GST body tokens used to compare branded vs unbranded PDFs."""
    keys = (
        "HSN",
        "CGST",
        "SGST",
        "Round-off",
        "Taxable",
        "Invoice",
        "GSTIN",
        "Grand Total",
        "Payment Mode",
    )
    lines = [line.strip() for line in pdf_text.splitlines() if line.strip()]
    return [line for line in lines if any(key in line for key in keys)]


@pytest.mark.asyncio
async def test_branded_vs_unbranded_gst_text_unchanged(
    inventory_session: AsyncSession,
) -> None:
    shop = ShopProfileService(inventory_session)
    await shop.set_shop_profile(
        OWNER_TELEGRAM_USER_ID,
        shop_name="Parity Kirana",
        address="2 Tax Road",
        gstin="27EEEEE4444E4Z5",
    )
    product = await _create_product(
        inventory_session,
        name="Parity Item",
        mrp_paise=28000,
        gst_slab=5,
        hsn_code="11010010",
    )
    bill = await _seed_bill(
        inventory_session,
        payment_mode="cash",
        invoice_number="INV-BRAND-PARITY-0001",
        lines=[(product, Decimal("1"), 28000, 26667, 667, 666, 5)],
        subtotal_paise=26667,
        cgst_paise=667,
        sgst_paise=666,
        round_off_paise=0,
        total_paise=28000,
    )
    invoice_service = InvoiceService(inventory_session)

    unbranded = await invoice_service.generate_invoice_pdf(
        bill.bill_id,
        owner_telegram_user_id=OWNER_TELEGRAM_USER_ID,
    )
    assert isinstance(unbranded, InvoicePdfResult)
    unbranded_text = _extract_pdf_text(unbranded.pdf_bytes)

    await shop.set_shop_profile(
        OWNER_TELEGRAM_USER_ID,
        shop_name="Parity Kirana",
        address="2 Tax Road",
        gstin="27EEEEE4444E4Z5",
        logo_url="https://example.com/parity-logo.png",
        accent_color="#0B8043",
    )
    branded = await invoice_service.generate_invoice_pdf(
        bill.bill_id,
        owner_telegram_user_id=OWNER_TELEGRAM_USER_ID,
    )
    assert isinstance(branded, InvoicePdfResult)
    branded_text = _extract_pdf_text(branded.pdf_bytes)

    assert _gst_mandated_snippets(unbranded_text) == _gst_mandated_snippets(
        branded_text
    )
    assert "INV-BRAND-PARITY-0001" in branded_text
    assert "11010010" in branded_text


@pytest.mark.asyncio
async def test_unbranded_invoice_still_renders(
    inventory_session: AsyncSession,
) -> None:
    await _ensure_shop_profile(inventory_session)
    product = await _create_product(
        inventory_session,
        name="Unbranded Item",
        mrp_paise=1000,
        gst_slab=0,
        hsn_code="100630",
    )
    bill = await _seed_bill(
        inventory_session,
        payment_mode="cash",
        lines=[(product, Decimal("1"), 1000, 1000, 0, 0, 0)],
        subtotal_paise=1000,
        cgst_paise=0,
        sgst_paise=0,
        round_off_paise=0,
        total_paise=1000,
    )
    result = await InvoiceService(inventory_session).generate_invoice_pdf(
        bill.bill_id,
        owner_telegram_user_id=OWNER_TELEGRAM_USER_ID,
    )
    assert isinstance(result, InvoicePdfResult)
    text = _extract_pdf_text(result.pdf_bytes)
    assert "Sidhu Kirana Store" in text
    assert "HSN" in text
    assert "Round-off" in text


@pytest.mark.asyncio
async def test_regenerate_same_bill_pdf_text_identical(
    inventory_session: AsyncSession,
) -> None:
    shop = ShopProfileService(inventory_session)
    await shop.set_shop_profile(
        OWNER_TELEGRAM_USER_ID,
        shop_name="Stable Brand",
        address="3 Same St",
        gstin="27FFFFF5555F5Z5",
        logo_url="https://example.com/stable.png",
        accent_color="#202124",
    )
    product = await _create_product(
        inventory_session,
        name="Stable Item",
        mrp_paise=5000,
        gst_slab=12,
        hsn_code="190230",
    )
    bill = await _seed_bill(
        inventory_session,
        payment_mode="upi",
        invoice_number="INV-STABLE-0001",
        lines=[(product, Decimal("2"), 5000, 4464, 268, 268, 12)],
        subtotal_paise=8928,
        cgst_paise=536,
        sgst_paise=536,
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
    assert isinstance(first, InvoicePdfResult)
    assert isinstance(second, InvoicePdfResult)
    assert _extract_pdf_text(first.pdf_bytes) == _extract_pdf_text(second.pdf_bytes)
