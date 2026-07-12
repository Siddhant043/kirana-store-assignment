"""Inventory domain logic: Product lookup, stock-in, and stock queries."""

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Product, StockBatch, StockLedger
from src.domain.shop_time import today_ist

FindProductStatus = Literal["ok", "ambiguous", "refused"]
MIN_MATCH_SCORE = 0.25
AMBIGUITY_SCORE_DELTA = 0.08
DEFAULT_EXPIRING_SOON_DAYS = 7


@dataclass(frozen=True)
class ProductCandidate:
    product_id: int
    name: str
    brand: str | None
    mrp_paise: int
    cost_price_paise: int
    gst_slab: int
    hsn_code: str
    unit_type: str
    quantity: str
    reorder_level: str
    match_score: float


@dataclass(frozen=True)
class FindProductResult:
    status: FindProductStatus
    candidates: list[ProductCandidate]
    ambiguous: bool


@dataclass(frozen=True)
class AddProductResult:
    status: Literal["ok"]
    product_id: int


@dataclass(frozen=True)
class ReceiveStockResult:
    status: Literal["ok"]
    product_id: int
    quantity_after: str
    ledger_id: int
    batch_id: int


@dataclass(frozen=True)
class GetStockResult:
    status: Literal["ok"]
    product_id: int
    name: str
    quantity: str
    reorder_level: str
    unit_type: str


@dataclass(frozen=True)
class LowStockProduct:
    product_id: int
    name: str
    brand: str | None
    quantity: str
    reorder_level: str
    unit_type: str


@dataclass(frozen=True)
class ListLowStockResult:
    status: Literal["ok"]
    products: list[LowStockProduct]


@dataclass(frozen=True)
class ExpiringBatch:
    batch_id: int
    product_id: int
    name: str
    batch_qty: str
    expiry_date: str
    cost_price_paise: int


@dataclass(frozen=True)
class ListExpiringSoonResult:
    status: Literal["ok"]
    within_days: int
    as_of_date: str
    batches: list[ExpiringBatch]


class ProductNotFoundError(Exception):
    pass


FIND_PRODUCT_SQL = text(
    """
    WITH matches AS (
        SELECT
            p.product_id,
            GREATEST(
                similarity(lower(p.name), lower(:query)),
                similarity(lower(coalesce(p.brand, '')), lower(:query))
            ) AS match_score
        FROM products p
        WHERE
            similarity(lower(p.name), lower(:query)) >= :min_score
            OR similarity(lower(coalesce(p.brand, '')), lower(:query)) >= :min_score
        UNION ALL
        SELECT
            a.product_id,
            similarity(lower(a.alias), lower(:query)) AS match_score
        FROM aliases a
        WHERE similarity(lower(a.alias), lower(:query)) >= :min_score
    ),
    ranked AS (
        SELECT
            product_id,
            MAX(match_score) AS match_score
        FROM matches
        GROUP BY product_id
    )
    SELECT
        p.product_id,
        p.name,
        p.brand,
        p.mrp_paise,
        p.cost_price_paise,
        p.gst_slab,
        p.hsn_code,
        p.unit_type,
        p.quantity,
        p.reorder_level,
        r.match_score
    FROM ranked r
    JOIN products p ON p.product_id = r.product_id
    ORDER BY r.match_score DESC, p.name ASC
    """
)


class InventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_product(
        self,
        *,
        name: str,
        brand: str | None,
        mrp_paise: int,
        cost_price_paise: int,
        gst_slab: int,
        hsn_code: str,
        unit_type: str,
        reorder_level: Decimal,
    ) -> AddProductResult:
        product = Product(
            name=name,
            brand=brand,
            mrp_paise=mrp_paise,
            cost_price_paise=cost_price_paise,
            gst_slab=gst_slab,
            hsn_code=hsn_code,
            unit_type=unit_type,
            quantity=Decimal("0"),
            reorder_level=reorder_level,
        )
        self._session.add(product)
        await self._session.flush()
        return AddProductResult(status="ok", product_id=product.product_id)

    async def find_product(self, query: str) -> FindProductResult:
        normalized_query = query.strip()
        if not normalized_query:
            return FindProductResult(status="refused", candidates=[], ambiguous=False)

        result = await self._session.execute(
            FIND_PRODUCT_SQL,
            {
                "query": normalized_query,
                "min_score": MIN_MATCH_SCORE,
            },
        )
        rows = result.mappings().all()

        candidates = [
            ProductCandidate(
                product_id=row["product_id"],
                name=row["name"],
                brand=row["brand"],
                mrp_paise=row["mrp_paise"],
                cost_price_paise=row["cost_price_paise"],
                gst_slab=row["gst_slab"],
                hsn_code=row["hsn_code"],
                unit_type=row["unit_type"],
                quantity=str(row["quantity"]),
                reorder_level=str(row["reorder_level"]),
                match_score=float(row["match_score"]),
            )
            for row in rows
        ]

        if not candidates:
            return FindProductResult(status="refused", candidates=[], ambiguous=False)

        ambiguous = _is_ambiguous(candidates)
        status: FindProductStatus = "ambiguous" if ambiguous else "ok"
        return FindProductResult(
            status=status,
            candidates=candidates,
            ambiguous=ambiguous,
        )

    async def receive_stock(
        self,
        *,
        product_id: int,
        quantity: Decimal,
        cost_price_paise: int | None = None,
        expiry_date: date | None = None,
    ) -> ReceiveStockResult:
        if quantity <= 0:
            msg = "quantity must be positive"
            raise ValueError(msg)

        product = await self._lock_product(product_id)
        batch_cost = (
            cost_price_paise
            if cost_price_paise is not None
            else product.cost_price_paise
        )
        batch = StockBatch(
            product_id=product_id,
            batch_qty=quantity,
            cost_price_paise=batch_cost,
            expiry_date=expiry_date,
        )
        self._session.add(batch)
        await self._session.flush()

        new_quantity = await self._reconcile_product_quantity(product)
        ledger_entry = StockLedger(
            product_id=product_id,
            delta=quantity,
            reason="stock_in",
            ref_id=batch.batch_id,
            balance_after=new_quantity,
        )
        self._session.add(ledger_entry)
        await self._session.flush()

        return ReceiveStockResult(
            status="ok",
            product_id=product_id,
            quantity_after=str(new_quantity),
            ledger_id=ledger_entry.ledger_id,
            batch_id=batch.batch_id,
        )

    async def get_stock(self, product_id: int) -> GetStockResult:
        product = await self._get_product(product_id)
        return GetStockResult(
            status="ok",
            product_id=product.product_id,
            name=product.name,
            quantity=str(product.quantity),
            reorder_level=str(product.reorder_level),
            unit_type=product.unit_type,
        )

    async def list_low_stock(self) -> ListLowStockResult:
        result = await self._session.execute(
            select(Product)
            .where(Product.quantity < Product.reorder_level)
            .order_by(Product.name)
        )
        products = [
            LowStockProduct(
                product_id=product.product_id,
                name=product.name,
                brand=product.brand,
                quantity=str(product.quantity),
                reorder_level=str(product.reorder_level),
                unit_type=product.unit_type,
            )
            for product in result.scalars().all()
        ]
        return ListLowStockResult(status="ok", products=products)

    async def list_expiring_soon(
        self,
        within_days: int = DEFAULT_EXPIRING_SOON_DAYS,
    ) -> ListExpiringSoonResult:
        if within_days < 0:
            msg = "within_days must be non-negative"
            raise ValueError(msg)
        as_of = today_ist()
        end_date = as_of + timedelta(days=within_days)
        result = await self._session.execute(
            select(StockBatch, Product.name)
            .join(Product, Product.product_id == StockBatch.product_id)
            .where(
                StockBatch.expiry_date.is_not(None),
                StockBatch.expiry_date >= as_of,
                StockBatch.expiry_date <= end_date,
                StockBatch.batch_qty > 0,
            )
            .order_by(StockBatch.expiry_date.asc(), StockBatch.batch_id.asc())
        )
        batches = [
            ExpiringBatch(
                batch_id=batch.batch_id,
                product_id=batch.product_id,
                name=name,
                batch_qty=str(batch.batch_qty),
                expiry_date=batch.expiry_date.isoformat()
                if batch.expiry_date is not None
                else "",
                cost_price_paise=batch.cost_price_paise,
            )
            for batch, name in result.all()
        ]
        return ListExpiringSoonResult(
            status="ok",
            within_days=within_days,
            as_of_date=as_of.isoformat(),
            batches=batches,
        )

    async def _reconcile_product_quantity(self, product: Product) -> Decimal:
        result = await self._session.execute(
            select(func.coalesce(func.sum(StockBatch.batch_qty), 0)).where(
                StockBatch.product_id == product.product_id
            )
        )
        total = Decimal(str(result.scalar_one()))
        product.quantity = total
        return total

    async def _lock_product(self, product_id: int) -> Product:
        result = await self._session.execute(
            select(Product).where(Product.product_id == product_id).with_for_update()
        )
        product = result.scalar_one_or_none()
        if product is None:
            raise ProductNotFoundError(f"product_id={product_id} not found")
        return product

    async def _get_product(self, product_id: int) -> Product:
        result = await self._session.execute(
            select(Product).where(Product.product_id == product_id)
        )
        product = result.scalar_one_or_none()
        if product is None:
            raise ProductNotFoundError(f"product_id={product_id} not found")
        return product


def _is_ambiguous(candidates: list[ProductCandidate]) -> bool:
    if len(candidates) < 2:
        return False
    top_score = candidates[0].match_score
    second_score = candidates[1].match_score
    return abs(top_score - second_score) <= AMBIGUITY_SCORE_DELTA


def serialize_find_product_result(result: FindProductResult) -> dict[str, object]:
    return {
        "status": result.status,
        "ambiguous": result.ambiguous,
        "candidates": [asdict(candidate) for candidate in result.candidates],
    }


def serialize_add_product_result(result: AddProductResult) -> dict[str, object]:
    return asdict(result)


def serialize_receive_stock_result(result: ReceiveStockResult) -> dict[str, object]:
    return asdict(result)


def serialize_get_stock_result(result: GetStockResult) -> dict[str, object]:
    return asdict(result)


def serialize_list_low_stock_result(result: ListLowStockResult) -> dict[str, object]:
    return {
        "status": result.status,
        "products": [asdict(product) for product in result.products],
    }


def serialize_list_expiring_soon_result(
    result: ListExpiringSoonResult,
) -> dict[str, object]:
    return {
        "status": result.status,
        "within_days": result.within_days,
        "as_of_date": result.as_of_date,
        "batches": [asdict(batch) for batch in result.batches],
    }
