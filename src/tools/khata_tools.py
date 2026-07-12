"""Khata MCP tool handlers."""

import json
from typing import Any

from claude_agent_sdk import tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.khata import (
    CustomerNotFoundError,
    FindOrCreateCustomerResult,
    KhataBalanceResult,
    KhataMutationResult,
    KhataService,
    RefusedResult,
    RequiresConfirmationResult,
    serialize_find_or_create_customer_result,
    serialize_khata_balance_result,
    serialize_khata_mutation_result,
    serialize_refused_result,
    serialize_requires_confirmation_result,
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


def _serialize_khata_result(
    result: (
        FindOrCreateCustomerResult
        | KhataMutationResult
        | KhataBalanceResult
        | RefusedResult
        | RequiresConfirmationResult
    ),
) -> dict[str, object]:
    if isinstance(result, FindOrCreateCustomerResult):
        return serialize_find_or_create_customer_result(result)
    if isinstance(result, KhataMutationResult):
        return serialize_khata_mutation_result(result)
    if isinstance(result, KhataBalanceResult):
        return serialize_khata_balance_result(result)
    if isinstance(result, RequiresConfirmationResult):
        return serialize_requires_confirmation_result(result)
    return serialize_refused_result(result)


def build_khata_tools(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[Any]:
    @tool(
        "find_or_create_customer",
        "Resolve a Customer by name (optional phone). Confirms before "
        "creating a new Customer; returns ambiguous candidates on collision.",
        {
            "name": str,
            "phone": str,
            "confirm_create": bool,
        },
    )
    async def find_or_create_customer_tool(args: dict[str, Any]) -> dict[str, Any]:
        name = str(args["name"])
        phone = str(args["phone"]) if args.get("phone") else None
        confirm_create = bool(args.get("confirm_create", False))
        async with session_factory() as session:
            async with session.begin():
                service = KhataService(session)
                result = await service.find_or_create_customer(
                    name,
                    phone,
                    confirm_create=confirm_create,
                )
                is_error = isinstance(result, RefusedResult)
                return _tool_response(
                    _serialize_khata_result(result),
                    is_error=is_error,
                )

    @tool(
        "add_khata_charge",
        "Put a manual charge amount on a grounded Customer's Khata.",
        {"customer_id": int, "amount_paise": int},
    )
    async def add_khata_charge_tool(args: dict[str, Any]) -> dict[str, Any]:
        async with session_factory() as session:
            async with session.begin():
                service = KhataService(session)
                try:
                    result = await service.add_khata_charge(
                        int(args["customer_id"]),
                        int(args["amount_paise"]),
                    )
                except CustomerNotFoundError as error:
                    return _tool_response(
                        serialize_refused_result(
                            RefusedResult(
                                status="refused",
                                reason="khata_not_found",
                                details={"message": str(error)},
                            )
                        ),
                        is_error=True,
                    )
                is_error = isinstance(result, RefusedResult)
                return _tool_response(
                    _serialize_khata_result(result),
                    is_error=is_error,
                )

    @tool(
        "record_payment",
        "Record a payment against a Customer's Khata.",
        {
            "customer_id": int,
            "amount_paise": int,
            "confirm_overpayment": bool,
        },
    )
    async def record_payment_tool(args: dict[str, Any]) -> dict[str, Any]:
        confirm_overpayment = bool(args.get("confirm_overpayment", False))
        async with session_factory() as session:
            async with session.begin():
                service = KhataService(session)
                result = await service.record_payment(
                    int(args["customer_id"]),
                    int(args["amount_paise"]),
                    confirm_overpayment=confirm_overpayment,
                )
                is_error = isinstance(result, RefusedResult)
                return _tool_response(
                    _serialize_khata_result(result),
                    is_error=is_error,
                )

    @tool(
        "get_khata_balance",
        "Get a Customer's Khata balance (sum of Khata Entries).",
        {"customer_id": int},
    )
    async def get_khata_balance_tool(args: dict[str, Any]) -> dict[str, Any]:
        async with session_factory() as session:
            async with session.begin():
                service = KhataService(session)
                result = await service.get_khata_balance(int(args["customer_id"]))
                is_error = isinstance(result, RefusedResult)
                return _tool_response(
                    _serialize_khata_result(result),
                    is_error=is_error,
                )

    return [
        find_or_create_customer_tool,
        add_khata_charge_tool,
        record_payment_tool,
        get_khata_balance_tool,
    ]
