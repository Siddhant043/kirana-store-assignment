"""Exact Product barcode lookup tests."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.inventory import FindProductResult, InventoryService


@pytest.mark.asyncio
async def test_find_product_by_barcode_returns_seeded_packaged_product(
    inventory_session: AsyncSession,
) -> None:
    service = InventoryService(inventory_session)
    result = await service.find_product_by_barcode("8901262010016")

    assert isinstance(result, FindProductResult)
    assert result.status == "ok"
    assert result.ambiguous is False
    assert len(result.candidates) == 1
    assert result.candidates[0].name == "Amul Butter 100g"
    assert result.candidates[0].match_score == 1.0


@pytest.mark.asyncio
async def test_find_product_by_barcode_unknown_refuses(
    inventory_session: AsyncSession,
) -> None:
    service = InventoryService(inventory_session)
    result = await service.find_product_by_barcode("0000000000000")

    assert result.status == "refused"
    assert result.candidates == []
    assert result.ambiguous is False


@pytest.mark.asyncio
async def test_find_product_by_barcode_blank_refuses(
    inventory_session: AsyncSession,
) -> None:
    service = InventoryService(inventory_session)
    result = await service.find_product_by_barcode("   ")
    assert result.status == "refused"
    assert result.candidates == []
