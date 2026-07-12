"""Read-only analytics: Daily Close and weekly sales reports."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Bill, BillLine, Product
from src.domain.shop_time import (
    rolling_last_n_ist_days,
    today_ist,
    utc_bounds_for_ist_date,
    utc_bounds_for_ist_range,
)

TOP_ITEMS_LIMIT = 10


@dataclass(frozen=True)
class PaymentModeSplit:
    cash_paise: int
    upi_paise: int
    card_paise: int
    khata_paise: int


@dataclass(frozen=True)
class DailySalesPoint:
    business_date: str
    bill_count: int
    total_sales_paise: int


@dataclass(frozen=True)
class GstSlabTotal:
    gst_slab: int
    tax_collected_paise: int
    taxable_paise: int


@dataclass(frozen=True)
class TopItem:
    product_id: int
    name: str
    quantity: str
    revenue_paise: int


@dataclass(frozen=True)
class ReportAggregate:
    bill_count: int
    total_sales_paise: int
    subtotal_paise: int
    cgst_paise: int
    sgst_paise: int
    tax_collected_paise: int
    round_off_paise: int
    payment_mode_split: PaymentModeSplit
    top_items: list[TopItem]


@dataclass(frozen=True)
class DailyCloseResult:
    status: Literal["ok"]
    business_date: str
    timezone: Literal["Asia/Kolkata"]
    bill_count: int
    total_sales_paise: int
    subtotal_paise: int
    cgst_paise: int
    sgst_paise: int
    tax_collected_paise: int
    round_off_paise: int
    payment_mode_split: PaymentModeSplit
    top_items: list[TopItem]


@dataclass(frozen=True)
class WeeklySalesReportResult:
    status: Literal["ok"]
    period_start: str
    period_end: str
    timezone: Literal["Asia/Kolkata"]
    bill_count: int
    total_sales_paise: int
    subtotal_paise: int
    cgst_paise: int
    sgst_paise: int
    tax_collected_paise: int
    round_off_paise: int
    payment_mode_split: PaymentModeSplit
    top_items: list[TopItem]


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def daily_close(
        self,
        business_date: date | None = None,
    ) -> DailyCloseResult:
        target_date = business_date or today_ist()
        start_utc, end_utc = utc_bounds_for_ist_date(target_date)
        report = await self._build_report(start_utc, end_utc)
        return DailyCloseResult(
            status="ok",
            business_date=target_date.isoformat(),
            timezone="Asia/Kolkata",
            bill_count=report.bill_count,
            total_sales_paise=report.total_sales_paise,
            subtotal_paise=report.subtotal_paise,
            cgst_paise=report.cgst_paise,
            sgst_paise=report.sgst_paise,
            tax_collected_paise=report.tax_collected_paise,
            round_off_paise=report.round_off_paise,
            payment_mode_split=report.payment_mode_split,
            top_items=report.top_items,
        )

    async def weekly_sales_report(self) -> WeeklySalesReportResult:
        start_date, end_date = rolling_last_n_ist_days(7)
        report = await self.report_for_ist_range(start_date, end_date)
        return WeeklySalesReportResult(
            status="ok",
            period_start=start_date.isoformat(),
            period_end=end_date.isoformat(),
            timezone="Asia/Kolkata",
            bill_count=report.bill_count,
            total_sales_paise=report.total_sales_paise,
            subtotal_paise=report.subtotal_paise,
            cgst_paise=report.cgst_paise,
            sgst_paise=report.sgst_paise,
            tax_collected_paise=report.tax_collected_paise,
            round_off_paise=report.round_off_paise,
            payment_mode_split=report.payment_mode_split,
            top_items=report.top_items,
        )

    async def report_for_ist_range(
        self,
        start_date: date,
        end_date: date,
    ) -> ReportAggregate:
        start_utc, end_utc = utc_bounds_for_ist_range(start_date, end_date)
        return await self._build_report(start_utc, end_utc)

    async def sales_trend(self, day_count: int = 7) -> list[DailySalesPoint]:
        start_date, end_date = rolling_last_n_ist_days(day_count)
        points: list[DailySalesPoint] = []
        current = start_date
        while current <= end_date:
            start_utc, end_utc = utc_bounds_for_ist_date(current)
            bills = await self._load_bills_in_range(start_utc, end_utc)
            totals = self._bill_totals(bills)
            points.append(
                DailySalesPoint(
                    business_date=current.isoformat(),
                    bill_count=len(bills),
                    total_sales_paise=totals["total_sales_paise"],
                )
            )
            current = current + timedelta(days=1)
        return points

    async def gst_collected_by_slab(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[GstSlabTotal]:
        period_start, period_end = rolling_last_n_ist_days(7)
        if start_date is not None:
            period_start = start_date
        if end_date is not None:
            period_end = end_date
        start_utc, end_utc = utc_bounds_for_ist_range(period_start, period_end)
        result = await self._session.execute(
            select(
                BillLine.gst_slab,
                func.coalesce(
                    func.sum(BillLine.cgst_paise + BillLine.sgst_paise),
                    0,
                ).label("tax_collected_paise"),
                func.coalesce(func.sum(BillLine.taxable_paise), 0).label(
                    "taxable_paise"
                ),
            )
            .join(Bill, Bill.bill_id == BillLine.bill_id)
            .where(
                Bill.finalized_at >= start_utc,
                Bill.finalized_at < end_utc,
            )
            .group_by(BillLine.gst_slab)
            .order_by(BillLine.gst_slab)
        )
        return [
            GstSlabTotal(
                gst_slab=int(row.gst_slab),
                tax_collected_paise=int(row.tax_collected_paise),
                taxable_paise=int(row.taxable_paise),
            )
            for row in result.all()
        ]

    async def top_items_by_quantity(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        *,
        limit: int = TOP_ITEMS_LIMIT,
    ) -> list[TopItem]:
        period_start, period_end = rolling_last_n_ist_days(7)
        if start_date is not None:
            period_start = start_date
        if end_date is not None:
            period_end = end_date
        start_utc, end_utc = utc_bounds_for_ist_range(period_start, period_end)
        result = await self._session.execute(
            select(
                BillLine.product_id,
                Product.name,
                func.sum(BillLine.quantity).label("quantity"),
                func.sum(BillLine.line_total_paise).label("revenue_paise"),
            )
            .join(Bill, Bill.bill_id == BillLine.bill_id)
            .join(Product, Product.product_id == BillLine.product_id)
            .where(
                Bill.finalized_at >= start_utc,
                Bill.finalized_at < end_utc,
            )
            .group_by(BillLine.product_id, Product.name)
            .order_by(func.sum(BillLine.quantity).desc())
            .limit(limit)
        )
        return [
            TopItem(
                product_id=row.product_id,
                name=row.name,
                quantity=str(row.quantity),
                revenue_paise=int(row.revenue_paise),
            )
            for row in result.all()
        ]

    async def _build_report(
        self,
        start_utc: datetime,
        end_utc: datetime,
    ) -> ReportAggregate:
        bills = await self._load_bills_in_range(start_utc, end_utc)
        payment_mode_split = self._payment_mode_split(bills)
        totals = self._bill_totals(bills)
        top_items = await self._top_items_in_range(start_utc, end_utc)
        return ReportAggregate(
            bill_count=len(bills),
            total_sales_paise=totals["total_sales_paise"],
            subtotal_paise=totals["subtotal_paise"],
            cgst_paise=totals["cgst_paise"],
            sgst_paise=totals["sgst_paise"],
            tax_collected_paise=totals["tax_collected_paise"],
            round_off_paise=totals["round_off_paise"],
            payment_mode_split=payment_mode_split,
            top_items=top_items,
        )

    async def _load_bills_in_range(
        self,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[Bill]:
        result = await self._session.execute(
            select(Bill).where(
                Bill.finalized_at >= start_utc,
                Bill.finalized_at < end_utc,
            )
        )
        return list(result.scalars().all())

    def _bill_totals(self, bills: list[Bill]) -> dict[str, int]:
        subtotal_paise = sum(bill.subtotal_paise for bill in bills)
        cgst_paise = sum(bill.cgst_paise for bill in bills)
        sgst_paise = sum(bill.sgst_paise for bill in bills)
        round_off_paise = sum(bill.round_off_paise for bill in bills)
        total_sales_paise = sum(bill.total_paise for bill in bills)
        return {
            "subtotal_paise": subtotal_paise,
            "cgst_paise": cgst_paise,
            "sgst_paise": sgst_paise,
            "tax_collected_paise": cgst_paise + sgst_paise,
            "round_off_paise": round_off_paise,
            "total_sales_paise": total_sales_paise,
        }

    def _payment_mode_split(self, bills: list[Bill]) -> PaymentModeSplit:
        mode_totals = {
            "cash": 0,
            "upi": 0,
            "card": 0,
            "khata": 0,
        }
        for bill in bills:
            mode_totals[bill.payment_mode] += bill.total_paise
        return PaymentModeSplit(
            cash_paise=mode_totals["cash"],
            upi_paise=mode_totals["upi"],
            card_paise=mode_totals["card"],
            khata_paise=mode_totals["khata"],
        )

    async def _top_items_in_range(
        self,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[TopItem]:
        result = await self._session.execute(
            select(
                BillLine.product_id,
                Product.name,
                func.sum(BillLine.quantity).label("quantity"),
                func.sum(BillLine.line_total_paise).label("revenue_paise"),
            )
            .join(Bill, Bill.bill_id == BillLine.bill_id)
            .join(Product, Product.product_id == BillLine.product_id)
            .where(
                Bill.finalized_at >= start_utc,
                Bill.finalized_at < end_utc,
            )
            .group_by(BillLine.product_id, Product.name)
            .order_by(func.sum(BillLine.line_total_paise).desc())
            .limit(TOP_ITEMS_LIMIT)
        )
        rows = result.all()
        return [
            TopItem(
                product_id=row.product_id,
                name=row.name,
                quantity=str(row.quantity),
                revenue_paise=int(row.revenue_paise),
            )
            for row in rows
        ]


def serialize_daily_close_result(result: DailyCloseResult) -> dict[str, object]:
    payload = asdict(result)
    payload["payment_mode_split"] = asdict(result.payment_mode_split)
    payload["top_items"] = [asdict(item) for item in result.top_items]
    return payload


def serialize_weekly_sales_report_result(
    result: WeeklySalesReportResult,
) -> dict[str, object]:
    payload = asdict(result)
    payload["payment_mode_split"] = asdict(result.payment_mode_split)
    payload["top_items"] = [asdict(item) for item in result.top_items]
    return payload
