"""Ordered product row locking for stock mutations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Product


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
