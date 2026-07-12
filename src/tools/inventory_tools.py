"""Inventory MCP tool handlers."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

from claude_agent_sdk import tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.context import current_photo_bytes
from src.domain.barcode import scan_barcode_image, serialize_scan_barcode_result
from src.domain.inventory import (
    InventoryService,
    ProductNotFoundError,
    serialize_add_product_result,
    serialize_find_product_result,
    serialize_get_stock_result,
    serialize_list_expiring_soon_result,
    serialize_list_low_stock_result,
    serialize_prepare_photo_product_result,
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
        "scan_barcode",
        "Decode a barcode from the current photo attachment and look up the "
        "exact Product by products.barcode. No owner confirmation is needed "
        "on a successful match. Call this first when the owner sends a photo.",
        {},
    )
    async def scan_barcode_tool(_args: dict[str, Any]) -> dict[str, Any]:
        photo = current_photo_bytes.get()
        async with session_factory() as session:
            async with session.begin():
                service = InventoryService(session)
                result = await scan_barcode_image(service, photo)
                is_error = result.status == "refused"
                return _tool_response(
                    serialize_scan_barcode_result(result),
                    is_error=is_error,
                )

    @tool(
        "prepare_photo_product",
        "After find_product on a vision guess, gate add_line behind owner "
        "confirmation. Call with confirm=false first (returns "
        "requires_confirmation), then confirm=true only after the owner agrees. "
        "Never add_line from a photo vision guess until confirm=true.",
        {
            "product_id": int,
            "confirm": bool,
        },
    )
    async def prepare_photo_product_tool(args: dict[str, Any]) -> dict[str, Any]:
        product_id = int(args["product_id"])
        confirm = bool(args.get("confirm", False))
        async with session_factory() as session:
            async with session.begin():
                service = InventoryService(session)
                result = await service.prepare_photo_product(
                    product_id,
                    confirm=confirm,
                )
                return _tool_response(
                    serialize_prepare_photo_product_result(result),
                    is_error=result.status == "refused",
                )

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
        "Receive stock for a grounded product_id as a new Batch "
        "(optional cost_price_paise and expiry_date YYYY-MM-DD). "
        "Null expiry = non-perishable/loose. Appends a Stock Ledger row "
        "and reconciles Product.quantity.",
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
        expiry_raw = args.get("expiry_date")
        expiry_date: date | None = None
        if isinstance(expiry_raw, str) and expiry_raw.strip():
            expiry_date = date.fromisoformat(expiry_raw.strip())
        async with session_factory() as session:
            async with session.begin():
                service = InventoryService(session)
                try:
                    result = await service.receive_stock(
                        product_id=int(args["product_id"]),
                        quantity=Decimal(str(args["quantity"])),
                        cost_price_paise=cost_price_paise,
                        expiry_date=expiry_date,
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

    @tool(
        "list_expiring_soon",
        "List Batches with expiry_date within the next N IST days "
        "(default 7). Use for 'what's expiring soon?'.",
        {
            "within_days": int,
        },
    )
    async def list_expiring_soon_tool(args: dict[str, Any]) -> dict[str, Any]:
        within_raw = args.get("within_days")
        within_days = int(within_raw) if within_raw is not None else 7
        async with session_factory() as session:
            async with session.begin():
                service = InventoryService(session)
                try:
                    result = await service.list_expiring_soon(within_days=within_days)
                except ValueError as error:
                    return _tool_response(
                        {"status": "refused", "reason": str(error)},
                        is_error=True,
                    )
                return _tool_response(serialize_list_expiring_soon_result(result))

    return [
        find_product_tool,
        scan_barcode_tool,
        prepare_photo_product_tool,
        add_product_tool,
        receive_stock_tool,
        get_stock_tool,
        list_low_stock_tool,
        list_expiring_soon_tool,
    ]
