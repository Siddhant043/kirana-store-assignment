"""Billing MCP tool handlers."""

import json
from decimal import Decimal
from typing import Any

from claude_agent_sdk import tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.context import require_chat_id
from src.domain.billing import (
    BillingService,
    FinalizeBillResult,
    LineMutationResult,
    OpenDraftBillResult,
    RefusedResult,
    RequiresConfirmationResult,
    ViewDraftResult,
    serialize_finalize_result,
    serialize_line_mutation_result,
    serialize_open_draft_result,
    serialize_refused_result,
    serialize_requires_confirmation_result,
    serialize_view_draft_result,
)
from src.domain.inventory import ProductNotFoundError


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


def _serialize_billing_result(
    result: (
        OpenDraftBillResult
        | ViewDraftResult
        | LineMutationResult
        | FinalizeBillResult
        | RefusedResult
        | RequiresConfirmationResult
    ),
) -> dict[str, object]:
    if isinstance(result, OpenDraftBillResult):
        return serialize_open_draft_result(result)
    if isinstance(result, ViewDraftResult):
        return serialize_view_draft_result(result)
    if isinstance(result, LineMutationResult):
        return serialize_line_mutation_result(result)
    if isinstance(result, FinalizeBillResult):
        return serialize_finalize_result(result)
    if isinstance(result, RequiresConfirmationResult):
        return serialize_requires_confirmation_result(result)
    return serialize_refused_result(result)


def build_billing_tools(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[Any]:
    @tool(
        "open_draft_bill",
        "Open or return the active open Draft Bill for this chat.",
        {},
    )
    async def open_draft_bill_tool(_args: dict[str, Any]) -> dict[str, Any]:
        chat_id = require_chat_id()
        async with session_factory() as session:
            async with session.begin():
                service = BillingService(session, chat_id)
                result = await service.open_draft_bill()
                return _tool_response(_serialize_billing_result(result))

    @tool(
        "add_line",
        "Add a Line to the open Draft Bill by grounded product_id and quantity.",
        {"product_id": int, "quantity": float},
    )
    async def add_line_tool(args: dict[str, Any]) -> dict[str, Any]:
        chat_id = require_chat_id()
        async with session_factory() as session:
            async with session.begin():
                service = BillingService(session, chat_id)
                try:
                    result = await service.add_line(
                        int(args["product_id"]),
                        Decimal(str(args["quantity"])),
                    )
                except ProductNotFoundError as error:
                    return _tool_response(
                        serialize_refused_result(
                            RefusedResult(
                                status="refused",
                                reason="product_not_found",
                                details={"message": str(error)},
                            )
                        ),
                        is_error=True,
                    )
                return _tool_response(_serialize_billing_result(result))

    @tool(
        "update_line",
        "Update quantity on a Line in the open Draft Bill.",
        {"product_id": int, "quantity": float},
    )
    async def update_line_tool(args: dict[str, Any]) -> dict[str, Any]:
        chat_id = require_chat_id()
        async with session_factory() as session:
            async with session.begin():
                service = BillingService(session, chat_id)
                try:
                    result = await service.update_line(
                        int(args["product_id"]),
                        Decimal(str(args["quantity"])),
                    )
                except (ProductNotFoundError, ValueError) as error:
                    return _tool_response(
                        serialize_refused_result(
                            RefusedResult(
                                status="refused",
                                reason="operation_failed",
                                details={"message": str(error)},
                            )
                        ),
                        is_error=True,
                    )
                return _tool_response(_serialize_billing_result(result))

    @tool(
        "remove_line",
        "Remove a Line from the open Draft Bill by product_id.",
        {"product_id": int},
    )
    async def remove_line_tool(args: dict[str, Any]) -> dict[str, Any]:
        chat_id = require_chat_id()
        async with session_factory() as session:
            async with session.begin():
                service = BillingService(session, chat_id)
                try:
                    result = await service.remove_line(int(args["product_id"]))
                except ValueError as error:
                    return _tool_response(
                        serialize_refused_result(
                            RefusedResult(
                                status="refused",
                                reason="operation_failed",
                                details={"message": str(error)},
                            )
                        ),
                        is_error=True,
                    )
                return _tool_response(_serialize_billing_result(result))

    @tool(
        "view_draft",
        "View the current open Draft Bill with Lines and on-hand quantities.",
        {},
    )
    async def view_draft_tool(_args: dict[str, Any]) -> dict[str, Any]:
        chat_id = require_chat_id()
        async with session_factory() as session:
            async with session.begin():
                service = BillingService(session, chat_id)
                result = await service.view_draft()
                return _tool_response(_serialize_billing_result(result))

    @tool(
        "finalize_bill",
        "Finalize the open Draft Bill into a Bill with payment mode and GST breakup.",
        {
            "payment_mode": str,
            "confirm_below_cost": bool,
            "customer_id": int,
        },
    )
    async def finalize_bill_tool(args: dict[str, Any]) -> dict[str, Any]:
        chat_id = require_chat_id()
        confirm_below_cost = bool(args.get("confirm_below_cost", False))
        customer_id = args.get("customer_id")
        parsed_customer_id = int(customer_id) if customer_id is not None else None
        async with session_factory() as session:
            async with session.begin():
                service = BillingService(session, chat_id)
                result = await service.finalize_bill(
                    str(args["payment_mode"]).lower(),
                    confirm_below_cost=confirm_below_cost,
                    customer_id=parsed_customer_id,
                )
                is_error = isinstance(result, RefusedResult)
                return _tool_response(
                    _serialize_billing_result(result), is_error=is_error
                )

    return [
        open_draft_bill_tool,
        add_line_tool,
        update_line_tool,
        remove_line_tool,
        view_draft_tool,
        finalize_bill_tool,
    ]
