"""Inventory tool-layer integration tests against Postgres."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Product, StockBatch, StockLedger
from src.domain.inventory import InventoryService


@pytest.mark.asyncio
async def test_find_product_exact_match_maggi(inventory_session: AsyncSession) -> None:
    service = InventoryService(inventory_session)
    result = await service.find_product("maggi")

    assert result.status == "ok"
    assert result.ambiguous is False
    assert len(result.candidates) == 1
    assert result.candidates[0].name == "Maggi Noodles 70g"
    assert result.candidates[0].mrp_paise == 1400
    assert result.candidates[0].gst_slab == 12


@pytest.mark.asyncio
async def test_find_product_ambiguous_atta(inventory_session: AsyncSession) -> None:
    service = InventoryService(inventory_session)
    result = await service.find_product("atta")

    assert result.status == "ambiguous"
    assert result.ambiguous is True
    assert len(result.candidates) >= 2
    candidate_names = {candidate.name for candidate in result.candidates}
    assert "Aashirvaad Atta 5kg" in candidate_names
    assert "Loose Atta" in candidate_names


@pytest.mark.asyncio
async def test_find_product_no_match(inventory_session: AsyncSession) -> None:
    service = InventoryService(inventory_session)
    result = await service.find_product("zzzznonexistentproduct")

    assert result.status == "refused"
    assert result.ambiguous is False
    assert result.candidates == []


@pytest.mark.asyncio
async def test_find_product_alias_chini_resolves_sugar(
    inventory_session: AsyncSession,
) -> None:
    service = InventoryService(inventory_session)
    result = await service.find_product("chini")

    assert result.status == "ok"
    assert result.candidates[0].name == "Sugar"


@pytest.mark.asyncio
async def test_receive_stock_updates_quantity_and_ledger(
    inventory_session: AsyncSession,
) -> None:
    service = InventoryService(inventory_session)
    find_result = await service.find_product("maggi")
    product_id = find_result.candidates[0].product_id
    product_before = await inventory_session.get(Product, product_id)
    assert product_before is not None
    quantity_before = product_before.quantity

    receive_result = await service.receive_stock(
        product_id=product_id,
        quantity=Decimal("50"),
        cost_price_paise=1200,
    )
    await inventory_session.flush()

    product = await inventory_session.get(Product, product_id)
    assert product is not None
    assert product.quantity == quantity_before + Decimal("50")
    assert product.cost_price_paise == product_before.cost_price_paise

    batch = await inventory_session.get(StockBatch, receive_result.batch_id)
    assert batch is not None
    assert batch.batch_qty == Decimal("50")
    assert batch.cost_price_paise == 1200
    assert batch.expiry_date is None

    ledger_row = await inventory_session.get(StockLedger, receive_result.ledger_id)
    assert ledger_row is not None
    assert ledger_row.delta == Decimal("50")
    assert ledger_row.balance_after == quantity_before + Decimal("50")
    assert ledger_row.reason == "stock_in"
    assert ledger_row.ref_id == receive_result.batch_id
    assert receive_result.ledger_id == ledger_row.ledger_id


@pytest.mark.asyncio
async def test_list_low_stock_below_reorder_level(
    inventory_session: AsyncSession,
) -> None:
    service = InventoryService(inventory_session)
    result = await service.list_low_stock()

    product_ids = {product.product_id for product in result.products}
    maggi = (
        await inventory_session.execute(
            select(Product).where(Product.name == "Maggi Noodles 70g")
        )
    ).scalar_one()
    assert maggi.product_id in product_ids


@pytest.mark.asyncio
async def test_add_product_persists_gst_slab_and_hsn(
    inventory_session: AsyncSession,
) -> None:
    service = InventoryService(inventory_session)
    add_result = await service.add_product(
        name="Amul Butter 100g",
        brand="Amul",
        mrp_paise=6200,
        cost_price_paise=5400,
        gst_slab=12,
        hsn_code="04051000",
        unit_type="packaged",
        reorder_level=Decimal("5"),
    )
    await inventory_session.flush()

    product = await inventory_session.get(Product, add_result.product_id)
    assert product is not None
    assert product.gst_slab == 12
    assert product.hsn_code == "04051000"
    assert product.mrp_paise == 6200
