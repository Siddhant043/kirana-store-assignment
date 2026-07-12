"""Read-only invoice PDF generation from finalized Bills."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from weasyprint import HTML  # type: ignore[import-untyped]

from src.db.models import Bill, BillLine, Customer, KhataEntry, Product
from src.domain.shop_profile import ShopProfileMissingResult, ShopProfileService

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"


@dataclass(frozen=True)
class InvoiceLineView:
    product_name: str
    hsn_code: str
    quantity: str
    mrp_paise: int
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    gst_slab: int
    line_total_paise: int


@dataclass(frozen=True)
class TaxBreakupRow:
    gst_slab: int
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int


@dataclass(frozen=True)
class InvoiceView:
    shop_name: str
    shop_address: str | None
    shop_gstin: str | None
    invoice_number: str
    finalized_at: datetime
    payment_mode: str
    payment_reference: str | None
    lines: list[InvoiceLineView]
    tax_breakup: list[TaxBreakupRow]
    subtotal_paise: int
    cgst_paise: int
    sgst_paise: int
    round_off_paise: int
    total_paise: int


@dataclass(frozen=True)
class InvoicePdfResult:
    status: Literal["ok"]
    bill_id: int
    invoice_number: str
    pdf_bytes: bytes
    filename: str


@dataclass(frozen=True)
class InvoiceRefusedResult:
    status: Literal["refused"]
    reason: Literal["bill_not_found", "shop_profile_missing", "no_bills"]
    details: dict[str, object]


@dataclass(frozen=True)
class ResolvedBillResult:
    status: Literal["ok"]
    bill_id: int
    invoice_number: str
    payment_mode: str
    total_paise: int
    finalized_at: str


def format_paise_as_rupees(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    absolute_paise = abs(paise)
    rupees, remaining_paise = divmod(absolute_paise, 100)
    return f"{sign}{rupees}.{remaining_paise:02d}"


class InvoiceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve_bill(
        self,
        chat_id: int,
        *,
        bill_id: int | None = None,
        invoice_number: str | None = None,
    ) -> Bill | InvoiceRefusedResult:
        if bill_id is not None:
            bill = await self._load_bill(bill_id)
            if bill is None or bill.chat_id != chat_id:
                return InvoiceRefusedResult(
                    status="refused",
                    reason="bill_not_found",
                    details={"bill_id": bill_id},
                )
            return bill

        if invoice_number is not None:
            result = await self._session.execute(
                select(Bill).where(
                    Bill.invoice_number == invoice_number,
                    Bill.chat_id == chat_id,
                )
            )
            bill = result.scalar_one_or_none()
            if bill is None:
                return InvoiceRefusedResult(
                    status="refused",
                    reason="bill_not_found",
                    details={"invoice_number": invoice_number},
                )
            return bill

        result = await self._session.execute(
            select(Bill)
            .where(Bill.chat_id == chat_id)
            .order_by(Bill.finalized_at.desc())
            .limit(1)
        )
        bill = result.scalar_one_or_none()
        if bill is None:
            return InvoiceRefusedResult(
                status="refused",
                reason="no_bills",
                details={"chat_id": chat_id},
            )
        return bill

    async def generate_invoice_pdf(
        self,
        bill_id: int,
        *,
        owner_telegram_user_id: int,
    ) -> InvoicePdfResult | InvoiceRefusedResult:
        bill = await self._load_bill_with_lines(bill_id)
        if bill is None:
            return InvoiceRefusedResult(
                status="refused",
                reason="bill_not_found",
                details={"bill_id": bill_id},
            )

        shop_service = ShopProfileService(self._session)
        shop_result = await shop_service.get_shop_profile(owner_telegram_user_id)
        if isinstance(shop_result, ShopProfileMissingResult):
            return InvoiceRefusedResult(
                status="refused",
                reason="shop_profile_missing",
                details={"owner_telegram_user_id": owner_telegram_user_id},
            )

        payment_reference = await self._khata_customer_name(bill)
        invoice_view = self._build_invoice_view(
            bill,
            shop_name=shop_result.shop_name,
            shop_address=shop_result.address,
            shop_gstin=shop_result.gstin,
            payment_reference=payment_reference,
        )
        pdf_bytes = render_invoice_pdf(invoice_view)
        filename = f"{bill.invoice_number}.pdf"
        return InvoicePdfResult(
            status="ok",
            bill_id=bill.bill_id,
            invoice_number=bill.invoice_number,
            pdf_bytes=pdf_bytes,
            filename=filename,
        )

    async def _load_bill(self, bill_id: int) -> Bill | None:
        result = await self._session.execute(
            select(Bill).where(Bill.bill_id == bill_id)
        )
        return result.scalar_one_or_none()

    async def _load_bill_with_lines(self, bill_id: int) -> Bill | None:
        result = await self._session.execute(
            select(Bill)
            .where(Bill.bill_id == bill_id)
            .options(
                selectinload(Bill.lines).selectinload(BillLine.product),
            )
        )
        return result.scalar_one_or_none()

    async def _khata_customer_name(self, bill: Bill) -> str | None:
        if bill.payment_mode != "khata":
            return None
        result = await self._session.execute(
            select(Customer.name)
            .join(KhataEntry, KhataEntry.customer_id == Customer.customer_id)
            .where(
                KhataEntry.bill_id == bill.bill_id,
                KhataEntry.entry_type == "charge",
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _build_invoice_view(
        self,
        bill: Bill,
        *,
        shop_name: str,
        shop_address: str | None,
        shop_gstin: str | None,
        payment_reference: str | None,
    ) -> InvoiceView:
        lines = [
            InvoiceLineView(
                product_name=_product_name(line),
                hsn_code=line.hsn_code,
                quantity=_format_quantity(line.quantity),
                mrp_paise=line.mrp_paise,
                taxable_paise=line.taxable_paise,
                cgst_paise=line.cgst_paise,
                sgst_paise=line.sgst_paise,
                gst_slab=line.gst_slab,
                line_total_paise=line.line_total_paise,
            )
            for line in bill.lines
        ]
        return InvoiceView(
            shop_name=shop_name,
            shop_address=shop_address,
            shop_gstin=shop_gstin,
            invoice_number=bill.invoice_number,
            finalized_at=bill.finalized_at,
            payment_mode=bill.payment_mode,
            payment_reference=payment_reference,
            lines=lines,
            tax_breakup=_tax_breakup_from_lines(bill.lines),
            subtotal_paise=bill.subtotal_paise,
            cgst_paise=bill.cgst_paise,
            sgst_paise=bill.sgst_paise,
            round_off_paise=bill.round_off_paise,
            total_paise=bill.total_paise,
        )


def _product_name(line: BillLine) -> str:
    product: Product | None = line.product
    if product is None:
        return f"Product {line.product_id}"
    return product.name


def _format_quantity(quantity: Decimal) -> str:
    normalized = quantity.normalize()
    return format(normalized, "f")


def _tax_breakup_from_lines(lines: list[BillLine]) -> list[TaxBreakupRow]:
    breakup: dict[int, TaxBreakupRow] = {}
    for line in lines:
        existing = breakup.get(line.gst_slab)
        if existing is None:
            breakup[line.gst_slab] = TaxBreakupRow(
                gst_slab=line.gst_slab,
                taxable_paise=line.taxable_paise,
                cgst_paise=line.cgst_paise,
                sgst_paise=line.sgst_paise,
            )
        else:
            breakup[line.gst_slab] = TaxBreakupRow(
                gst_slab=line.gst_slab,
                taxable_paise=existing.taxable_paise + line.taxable_paise,
                cgst_paise=existing.cgst_paise + line.cgst_paise,
                sgst_paise=existing.sgst_paise + line.sgst_paise,
            )
    return [breakup[slab] for slab in sorted(breakup)]


def render_invoice_pdf(invoice: InvoiceView) -> bytes:
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    environment.filters["paise"] = format_paise_as_rupees
    template = environment.get_template("invoice.html")
    html = template.render(invoice=invoice)
    pdf_buffer = BytesIO()
    HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf(pdf_buffer)
    return pdf_buffer.getvalue()


def serialize_invoice_pdf_result(result: InvoicePdfResult) -> dict[str, object]:
    return {
        "status": result.status,
        "bill_id": result.bill_id,
        "invoice_number": result.invoice_number,
        "filename": result.filename,
    }


def serialize_invoice_refused_result(
    result: InvoiceRefusedResult,
) -> dict[str, object]:
    return {
        "status": result.status,
        "reason": result.reason,
        "details": result.details,
    }


def serialize_resolved_bill_result(result: ResolvedBillResult) -> dict[str, object]:
    return {
        "status": result.status,
        "bill_id": result.bill_id,
        "invoice_number": result.invoice_number,
        "payment_mode": result.payment_mode,
        "total_paise": result.total_paise,
        "finalized_at": result.finalized_at,
    }


def resolved_bill_from_model(bill: Bill) -> ResolvedBillResult:
    return ResolvedBillResult(
        status="ok",
        bill_id=bill.bill_id,
        invoice_number=bill.invoice_number,
        payment_mode=bill.payment_mode,
        total_paise=bill.total_paise,
        finalized_at=bill.finalized_at.isoformat(),
    )
