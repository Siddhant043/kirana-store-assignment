"""Inventory MCP tool handlers."""

import json
from decimal import Decimal
from typing import Any

from claude_agent_sdk import tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.inventory import (
    InventoryService,
    ProductNotFoundError,
    serialize_add_product_result,
    serialize_find_product_result,
    serialize_get_stock_result,
    serialize_list_low_stock_result,
    serialize_receive_stock_result,
)


def _tool_response(
    payload: dict[str, object],
    *,
    is_error: bool = False,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "content": [{"type": "text", "text": json.dumps(payload)}],
    }
    if is_error:
        response["is_error"] = True
    return response


def build_inventory_tools(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[Any]:
    @tool(
        "find_product",
        "Fuzzy-match Products by name, brand, or Alias. "
        "Returns ranked candidates from the DB only.",
        {"query": str},
    )
    async def find_product_tool(args: dict[str, Any]) -> dict[str, Any]:
        query_text = str(args["query"])
        async with session_factory() as session:
            async with session.begin():
                service = InventoryService(session)
                result = await service.find_product(query_text)
                return _tool_response(serialize_find_product_result(result))

    @tool(
        "add_product",
        "Create a new Product with MRP, cost price, GST slab, HSN, "
        "unit type, and reorder level.",
        {
            "name": str,
            "brand": str,
            "mrp_paise": int,
            "cost_price_paise": int,
            "gst_slab": int,
            "hsn_code": str,
            "unit_type": str,
            "reorder_level": float,
        },
    )
    async def add_product_tool(args: dict[str, Any]) -> dict[str, Any]:
        brand_value = str(args["brand"]).strip()
        async with session_factory() as session:
            async with session.begin():
                service = InventoryService(session)
                result = await service.add_product(
                    name=str(args["name"]),
                    brand=brand_value or None,
                    mrp_paise=int(args["mrp_paise"]),
                    cost_price_paise=int(args["cost_price_paise"]),
                    gst_slab=int(args["gst_slab"]),
                    hsn_code=str(args["hsn_code"]),
                    unit_type=str(args["unit_type"]),
                    reorder_level=Decimal(str(args["reorder_level"])),
                )
                return _tool_response(serialize_add_product_result(result))

    @tool(
        "receive_stock",
        "Receive stock for a grounded product_id. "
        "Appends a Stock Ledger row and updates quantity.",
        {
            "product_id": int,
            "quantity": float,
        },
    )
    async def receive_stock_tool(args: dict[str, Any]) -> dict[str, Any]:
        cost_price_raw = args.get("cost_price_paise")
        cost_price_paise: int | None = None
        if isinstance(cost_price_raw, int):
            cost_price_paise = cost_price_raw
        elif isinstance(cost_price_raw, float):
            cost_price_paise = int(cost_price_raw)
        async with session_factory() as session:
            async with session.begin():
                service = InventoryService(session)
                try:
                    result = await service.receive_stock(
                        product_id=int(args["product_id"]),
                        quantity=Decimal(str(args["quantity"])),
                        cost_price_paise=cost_price_paise,
                    )
                except ProductNotFoundError as error:
                    return _tool_response(
                        {"status": "refused", "reason": str(error)},
                        is_error=True,
                    )
                except ValueError as error:
                    return _tool_response(
                        {"status": "refused", "reason": str(error)},
                        is_error=True,
                    )
                return _tool_response(serialize_receive_stock_result(result))

    @tool(
        "get_stock",
        "Read current quantity and reorder level for a grounded product_id.",
        {"product_id": int},
    )
    async def get_stock_tool(args: dict[str, Any]) -> dict[str, Any]:
        async with session_factory() as session:
            async with session.begin():
                service = InventoryService(session)
                try:
                    result = await service.get_stock(int(args["product_id"]))
                except ProductNotFoundError as error:
                    return _tool_response(
                        {"status": "refused", "reason": str(error)},
                        is_error=True,
                    )
                return _tool_response(serialize_get_stock_result(result))

    @tool(
        "list_low_stock",
        "List Products whose quantity is below their reorder level.",
        {},
    )
    async def list_low_stock_tool(_args: dict[str, Any]) -> dict[str, Any]:
        async with session_factory() as session:
            async with session.begin():
                service = InventoryService(session)
                result = await service.list_low_stock()
                return _tool_response(serialize_list_low_stock_result(result))

    return [
        find_product_tool,
        add_product_tool,
        receive_stock_tool,
        get_stock_tool,
        list_low_stock_tool,
    ]
