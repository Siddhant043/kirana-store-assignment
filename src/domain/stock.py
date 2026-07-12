"""Ordered product and Batch row locking for stock mutations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Product, StockBatch


async def lock_products_sorted(
    session: AsyncSession,
    product_ids: list[int],
) -> dict[int, Product]:
    locked_products: dict[int, Product] = {}
    for product_id in sorted(set(product_ids)):
        result = await session.execute(
            select(Product).where(Product.product_id == product_id).with_for_update()
        )
        product = result.scalar_one_or_none()
        if product is None:
            msg = f"product_id={product_id} not found"
            raise ValueError(msg)
        locked_products[product_id] = product
    return locked_products


async def lock_batches_sorted(
    session: AsyncSession,
    batch_ids: list[int],
) -> dict[int, StockBatch]:
    locked_batches: dict[int, StockBatch] = {}
    for batch_id in sorted(set(batch_ids)):
        result = await session.execute(
            select(StockBatch).where(StockBatch.batch_id == batch_id).with_for_update()
        )
        batch = result.scalar_one_or_none()
        if batch is None:
            msg = f"batch_id={batch_id} not found"
            raise ValueError(msg)
        locked_batches[batch_id] = batch
    return locked_batches
