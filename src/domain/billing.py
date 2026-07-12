"""Draft Bill and Bill lifecycle with atomic Finalize."""

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import (
    Bill,
    BillLine,
    DraftBill,
    DraftLine,
    InvoiceCounter,
    Product,
    StockLedger,
)
from src.domain.inventory import ProductNotFoundError
from src.domain.khata import CustomerNotFoundError, KhataService, lock_customer
from src.domain.pricing import LinePricing, compute_bill_totals, compute_line_pricing
from src.domain.stock import lock_products_sorted

PaymentMode = Literal["cash", "upi", "card", "khata"]
VALID_PAYMENT_MODES = frozenset({"cash", "upi", "card", "khata"})


@dataclass(frozen=True)
class OpenDraftBillResult:
    status: Literal["ok"]
    draft_bill_id: int


@dataclass(frozen=True)
class DraftLineView:
    product_id: int
    name: str
    brand: str | None
    quantity: str
    unit_type: str
    mrp_paise: int
    gst_slab: int
    on_hand_quantity: str
    soft_availability_warning: bool


@dataclass(frozen=True)
class ViewDraftResult:
    status: Literal["ok"]
    draft_bill_id: int
    lines: list[DraftLineView]


@dataclass(frozen=True)
class LineMutationResult:
    status: Literal["ok"]
    draft_bill_id: int
    product_id: int
    quantity: str
    soft_availability_warning: bool


@dataclass(frozen=True)
class BelowCostLine:
    product_id: int
    name: str
    mrp_paise: int
    cost_price_paise: int


@dataclass(frozen=True)
class FinalizeBillResult:
    status: Literal["ok"]
    bill_id: int
    invoice_number: str
    payment_mode: str
    subtotal_paise: int
    cgst_paise: int
    sgst_paise: int
    round_off_paise: int
    total_paise: int
    lines: list[dict[str, object]]
    idempotent_replay: bool


@dataclass(frozen=True)
class RefusedResult:
    status: Literal["refused"]
    reason: str
    details: dict[str, object]


@dataclass(frozen=True)
class RequiresConfirmationResult:
    status: Literal["requires_confirmation"]
    reason: Literal["below_cost"]
    lines: list[BelowCostLine]


class BillingService:
    def __init__(self, session: AsyncSession, chat_id: int) -> None:
        self._session = session
        self._chat_id = chat_id

    async def open_draft_bill(self) -> OpenDraftBillResult:
        draft = await self._get_or_create_open_draft()
        return OpenDraftBillResult(status="ok", draft_bill_id=draft.draft_bill_id)

    async def add_line(
        self,
        product_id: int,
        quantity: Decimal,
    ) -> LineMutationResult | RefusedResult:
        draft = await self._get_or_create_open_draft()
        product = await self._get_product(product_id)
        validation_error = self._validate_quantity(product, quantity)
        if validation_error is not None:
            return RefusedResult(status="refused", reason=validation_error, details={})

        soft_warning = product.quantity < quantity
        existing_line = await self._get_draft_line(draft.draft_bill_id, product_id)
        if existing_line is None:
            self._session.add(
                DraftLine(
                    draft_bill_id=draft.draft_bill_id,
                    product_id=product_id,
                    quantity=quantity,
                )
            )
        else:
            existing_line.quantity = existing_line.quantity + quantity
            soft_warning = product.quantity < existing_line.quantity

        await self._session.flush()
        final_quantity = (
            existing_line.quantity if existing_line is not None else quantity
        )
        return LineMutationResult(
            status="ok",
            draft_bill_id=draft.draft_bill_id,
            product_id=product_id,
            quantity=str(final_quantity),
            soft_availability_warning=soft_warning,
        )

    async def update_line(
        self,
        product_id: int,
        quantity: Decimal,
    ) -> LineMutationResult | RefusedResult:
        draft = await self._require_open_draft()
        product = await self._get_product(product_id)
        validation_error = self._validate_quantity(product, quantity)
        if validation_error is not None:
            return RefusedResult(status="refused", reason=validation_error, details={})

        draft_line = await self._get_draft_line(draft.draft_bill_id, product_id)
        if draft_line is None:
            return RefusedResult(
                status="refused",
                reason="line_not_found",
                details={"product_id": product_id},
            )

        draft_line.quantity = quantity
        await self._session.flush()
        return LineMutationResult(
            status="ok",
            draft_bill_id=draft.draft_bill_id,
            product_id=product_id,
            quantity=str(quantity),
            soft_availability_warning=product.quantity < quantity,
        )

    async def remove_line(
        self,
        product_id: int,
    ) -> LineMutationResult | RefusedResult:
        draft = await self._require_open_draft()
        draft_line = await self._get_draft_line(draft.draft_bill_id, product_id)
        if draft_line is None:
            return RefusedResult(
                status="refused",
                reason="line_not_found",
                details={"product_id": product_id},
            )

        await self._session.execute(
            delete(DraftLine).where(DraftLine.draft_line_id == draft_line.draft_line_id)
        )
        await self._session.flush()
        return LineMutationResult(
            status="ok",
            draft_bill_id=draft.draft_bill_id,
            product_id=product_id,
            quantity="0",
            soft_availability_warning=False,
        )

    async def view_draft(self) -> ViewDraftResult | RefusedResult:
        draft = await self._get_open_draft()
        if draft is None:
            return RefusedResult(
                status="refused",
                reason="no_open_draft",
                details={},
            )

        lines = await self._load_draft_line_views(draft.draft_bill_id)
        return ViewDraftResult(
            status="ok",
            draft_bill_id=draft.draft_bill_id,
            lines=lines,
        )

    async def finalize_bill(
        self,
        payment_mode: str,
        *,
        confirm_below_cost: bool = False,
        customer_id: int | None = None,
    ) -> FinalizeBillResult | RefusedResult | RequiresConfirmationResult:
        if payment_mode not in VALID_PAYMENT_MODES:
            return RefusedResult(
                status="refused",
                reason="invalid_payment_mode",
                details={"payment_mode": payment_mode},
            )
        if payment_mode == "khata" and customer_id is None:
            return RefusedResult(
                status="refused",
                reason="customer_required",
                details={"payment_mode": payment_mode},
            )

        open_draft = await self._get_open_draft()
        if open_draft is None:
            finalized_draft = await self._get_latest_finalized_draft()
            if finalized_draft is not None and finalized_draft.bill_id is not None:
                return await self._existing_finalize_result(
                    finalized_draft.bill_id,
                    idempotent_replay=True,
                )
            return RefusedResult(
                status="refused",
                reason="no_open_draft",
                details={},
            )

        draft = await self._lock_draft_by_id(open_draft.draft_bill_id)
        if draft.status == "finalized" and draft.bill_id is not None:
            return await self._existing_finalize_result(
                draft.bill_id, idempotent_replay=True
            )
        if draft.status != "open":
            return RefusedResult(status="refused", reason="no_open_draft", details={})

        draft_lines = await self._load_draft_lines(draft.draft_bill_id)
        if not draft_lines:
            return RefusedResult(status="refused", reason="empty_draft", details={})

        product_ids = [line.product_id for line in draft_lines]
        locked_products = await lock_products_sorted(self._session, product_ids)

        if payment_mode == "khata" and customer_id is not None:
            try:
                await lock_customer(self._session, customer_id)
            except CustomerNotFoundError:
                return RefusedResult(
                    status="refused",
                    reason="customer_not_found",
                    details={"customer_id": customer_id},
                )

        below_cost_lines = [
            BelowCostLine(
                product_id=product.product_id,
                name=product.name,
                mrp_paise=product.mrp_paise,
                cost_price_paise=product.cost_price_paise,
            )
            for line in draft_lines
            if (product := locked_products[line.product_id]).mrp_paise
            < product.cost_price_paise
        ]
        if below_cost_lines and not confirm_below_cost:
            return RequiresConfirmationResult(
                status="requires_confirmation",
                reason="below_cost",
                lines=below_cost_lines,
            )

        for line in draft_lines:
            product = locked_products[line.product_id]
            if product.quantity < line.quantity:
                return RefusedResult(
                    status="refused",
                    reason="oversell",
                    details={
                        "product_id": line.product_id,
                        "name": product.name,
                        "requested": str(line.quantity),
                        "available": str(product.quantity),
                    },
                )

        line_pricings: list[tuple[DraftLine, Product, LinePricing]] = []
        for line in draft_lines:
            product = locked_products[line.product_id]
            pricing = compute_line_pricing(
                product.mrp_paise,
                line.quantity,
                product.gst_slab,
                product.unit_type,
            )
            line_pricings.append((line, product, pricing))

        bill_totals = compute_bill_totals([pricing for _, _, pricing in line_pricings])
        invoice_number = await self._mint_invoice_number()

        bill = Bill(
            draft_bill_id=draft.draft_bill_id,
            chat_id=self._chat_id,
            invoice_number=invoice_number,
            payment_mode=payment_mode,
            subtotal_paise=bill_totals.subtotal_paise,
            cgst_paise=bill_totals.cgst_paise,
            sgst_paise=bill_totals.sgst_paise,
            round_off_paise=bill_totals.round_off_paise,
            total_paise=bill_totals.total_paise,
        )
        self._session.add(bill)
        await self._session.flush()

        bill_line_payloads: list[dict[str, object]] = []
        for line, product, pricing in line_pricings:
            self._session.add(
                BillLine(
                    bill_id=bill.bill_id,
                    product_id=product.product_id,
                    quantity=line.quantity,
                    mrp_paise=product.mrp_paise,
                    cost_price_paise=product.cost_price_paise,
                    gst_slab=product.gst_slab,
                    hsn_code=product.hsn_code,
                    line_total_paise=pricing.line_total_paise,
                    taxable_paise=pricing.taxable_paise,
                    cgst_paise=pricing.cgst_paise,
                    sgst_paise=pricing.sgst_paise,
                )
            )

            locked_product = locked_products[product.product_id]
            new_quantity = locked_product.quantity - line.quantity
            locked_product.quantity = new_quantity
            self._session.add(
                StockLedger(
                    product_id=product.product_id,
                    delta=-line.quantity,
                    reason="sale",
                    ref_id=bill.bill_id,
                    balance_after=new_quantity,
                )
            )
            bill_line_payloads.append(
                {
                    "product_id": product.product_id,
                    "name": product.name,
                    "quantity": str(line.quantity),
                    "line_total_paise": pricing.line_total_paise,
                    "taxable_paise": pricing.taxable_paise,
                    "cgst_paise": pricing.cgst_paise,
                    "sgst_paise": pricing.sgst_paise,
                }
            )

        draft.status = "finalized"
        draft.bill_id = bill.bill_id
        draft.updated_at = datetime.now(tz=UTC)

        if payment_mode == "khata" and customer_id is not None:
            khata_service = KhataService(self._session)
            await khata_service.append_bill_charge(
                customer_id,
                bill.bill_id,
                bill.total_paise,
            )

        await self._session.flush()

        return FinalizeBillResult(
            status="ok",
            bill_id=bill.bill_id,
            invoice_number=bill.invoice_number,
            payment_mode=bill.payment_mode,
            subtotal_paise=bill.subtotal_paise,
            cgst_paise=bill.cgst_paise,
            sgst_paise=bill.sgst_paise,
            round_off_paise=bill.round_off_paise,
            total_paise=bill.total_paise,
            lines=bill_line_payloads,
            idempotent_replay=False,
        )

    async def _existing_finalize_result(
        self,
        bill_id: int,
        *,
        idempotent_replay: bool,
    ) -> FinalizeBillResult:
        result = await self._session.execute(
            select(Bill)
            .where(Bill.bill_id == bill_id)
            .options(selectinload(Bill.lines).selectinload(BillLine.product))
        )
        bill = result.scalar_one()
        lines = [
            {
                "product_id": line.product_id,
                "name": line.product.name,
                "quantity": str(line.quantity),
                "line_total_paise": line.line_total_paise,
                "taxable_paise": line.taxable_paise,
                "cgst_paise": line.cgst_paise,
                "sgst_paise": line.sgst_paise,
            }
            for line in bill.lines
        ]
        return FinalizeBillResult(
            status="ok",
            bill_id=bill.bill_id,
            invoice_number=bill.invoice_number,
            payment_mode=bill.payment_mode,
            subtotal_paise=bill.subtotal_paise,
            cgst_paise=bill.cgst_paise,
            sgst_paise=bill.sgst_paise,
            round_off_paise=bill.round_off_paise,
            total_paise=bill.total_paise,
            lines=lines,
            idempotent_replay=idempotent_replay,
        )

    async def _mint_invoice_number(self) -> str:
        today = date.today()
        result = await self._session.execute(
            select(InvoiceCounter)
            .where(InvoiceCounter.counter_date == today)
            .with_for_update()
        )
        counter = result.scalar_one_or_none()
        if counter is None:
            counter = InvoiceCounter(counter_date=today, last_seq=0)
            self._session.add(counter)
            await self._session.flush()

        counter.last_seq += 1
        await self._session.flush()
        return f"INV-{today.strftime('%Y%m%d')}-{counter.last_seq:04d}"

    async def _get_or_create_open_draft(self) -> DraftBill:
        draft = await self._get_open_draft()
        if draft is not None:
            return draft

        draft = DraftBill(chat_id=self._chat_id, status="open")
        self._session.add(draft)
        await self._session.flush()
        return draft

    async def _require_open_draft(self) -> DraftBill:
        draft = await self._get_open_draft()
        if draft is None:
            msg = "no open draft bill for chat"
            raise ValueError(msg)
        return draft

    async def _get_open_draft(self) -> DraftBill | None:
        result = await self._session.execute(
            select(DraftBill).where(
                DraftBill.chat_id == self._chat_id,
                DraftBill.status == "open",
            )
        )
        return result.scalar_one_or_none()

    async def _lock_draft_by_id(self, draft_bill_id: int) -> DraftBill:
        result = await self._session.execute(
            select(DraftBill)
            .where(DraftBill.draft_bill_id == draft_bill_id)
            .with_for_update()
        )
        draft = result.scalar_one()
        return draft

    async def _get_latest_finalized_draft(self) -> DraftBill | None:
        result = await self._session.execute(
            select(DraftBill)
            .where(
                DraftBill.chat_id == self._chat_id,
                DraftBill.status == "finalized",
            )
            .order_by(DraftBill.draft_bill_id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_draft_line(
        self,
        draft_bill_id: int,
        product_id: int,
    ) -> DraftLine | None:
        result = await self._session.execute(
            select(DraftLine).where(
                DraftLine.draft_bill_id == draft_bill_id,
                DraftLine.product_id == product_id,
            )
        )
        return result.scalar_one_or_none()

    async def _load_draft_lines(self, draft_bill_id: int) -> list[DraftLine]:
        result = await self._session.execute(
            select(DraftLine).where(DraftLine.draft_bill_id == draft_bill_id)
        )
        return list(result.scalars().all())

    async def _load_draft_lines_with_products(
        self,
        draft_bill_id: int,
    ) -> list[DraftLine]:
        result = await self._session.execute(
            select(DraftLine)
            .where(DraftLine.draft_bill_id == draft_bill_id)
            .options(selectinload(DraftLine.product))
        )
        return list(result.scalars().all())

    async def _load_draft_line_views(self, draft_bill_id: int) -> list[DraftLineView]:
        draft_lines = await self._load_draft_lines_with_products(draft_bill_id)
        return [
            DraftLineView(
                product_id=line.product.product_id,
                name=line.product.name,
                brand=line.product.brand,
                quantity=str(line.quantity),
                unit_type=line.product.unit_type,
                mrp_paise=line.product.mrp_paise,
                gst_slab=line.product.gst_slab,
                on_hand_quantity=str(line.product.quantity),
                soft_availability_warning=line.product.quantity < line.quantity,
            )
            for line in draft_lines
        ]

    async def _get_product(self, product_id: int) -> Product:
        result = await self._session.execute(
            select(Product).where(Product.product_id == product_id)
        )
        product = result.scalar_one_or_none()
        if product is None:
            raise ProductNotFoundError(f"product_id={product_id} not found")
        return product

    def _validate_quantity(self, product: Product, quantity: Decimal) -> str | None:
        if quantity <= 0:
            return "invalid_quantity"
        if product.unit_type == "packaged" and quantity != quantity.to_integral_value():
            return "packaged_quantity_must_be_integer"
        return None


def serialize_open_draft_result(result: OpenDraftBillResult) -> dict[str, object]:
    return asdict(result)


def serialize_view_draft_result(result: ViewDraftResult) -> dict[str, object]:
    return {
        "status": result.status,
        "draft_bill_id": result.draft_bill_id,
        "lines": [asdict(line) for line in result.lines],
    }


def serialize_line_mutation_result(result: LineMutationResult) -> dict[str, object]:
    return asdict(result)


def serialize_finalize_result(result: FinalizeBillResult) -> dict[str, object]:
    return asdict(result)


def serialize_refused_result(result: RefusedResult) -> dict[str, object]:
    return asdict(result)


def serialize_requires_confirmation_result(
    result: RequiresConfirmationResult,
) -> dict[str, object]:
    return {
        "status": result.status,
        "reason": result.reason,
        "lines": [asdict(line) for line in result.lines],
    }
