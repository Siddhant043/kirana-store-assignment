"""Documents MCP tool handlers for invoices and Shop Profile."""

import json
from typing import Any, Protocol

from claude_agent_sdk import tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.context import require_chat_id, require_owner_user_id
from src.db.models import Bill
from src.domain.invoice import (
    InvoiceRefusedResult,
    InvoiceService,
    resolved_bill_from_model,
    serialize_invoice_pdf_result,
    serialize_invoice_refused_result,
    serialize_resolved_bill_result,
)
from src.domain.shop_profile import (
    ShopProfileMissingResult,
    ShopProfileResult,
    ShopProfileService,
    serialize_shop_profile_missing_result,
    serialize_shop_profile_result,
)


class DocumentSender(Protocol):
    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption: str | None = None,
    ) -> None: ...


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


def build_documents_tools(
    session_factory: async_sessionmaker[AsyncSession],
    message_sender: DocumentSender,
) -> list[Any]:
    @tool(
        "set_shop_profile",
        "Create or update the Shop Profile (shop name, address, GSTIN) "
        "printed on invoice PDFs.",
        {
            "shop_name": str,
            "address": str,
            "gstin": str,
        },
    )
    async def set_shop_profile_tool(args: dict[str, Any]) -> dict[str, Any]:
        owner_telegram_user_id = require_owner_user_id()
        shop_name = str(args["shop_name"])
        address = str(args["address"]) if args.get("address") else None
        gstin = str(args["gstin"]) if args.get("gstin") else None
        async with session_factory() as session:
            async with session.begin():
                service = ShopProfileService(session)
                result = await service.set_shop_profile(
                    owner_telegram_user_id,
                    shop_name=shop_name,
                    address=address,
                    gstin=gstin,
                )
                return _tool_response(serialize_shop_profile_result(result))

    @tool(
        "get_shop_profile",
        "Read the Shop Profile for the current Owner.",
        {},
    )
    async def get_shop_profile_tool(_args: dict[str, Any]) -> dict[str, Any]:
        owner_telegram_user_id = require_owner_user_id()
        async with session_factory() as session:
            service = ShopProfileService(session)
            result = await service.get_shop_profile(owner_telegram_user_id)
            return _tool_response(_serialize_shop_profile(result))

    @tool(
        "find_bill",
        "Resolve a finalized Bill by bill_id or invoice_number, "
        "or return the most recent Bill for this chat.",
        {
            "bill_id": int,
            "invoice_number": str,
        },
    )
    async def find_bill_tool(args: dict[str, Any]) -> dict[str, Any]:
        chat_id = require_chat_id()
        bill_id = int(args["bill_id"]) if args.get("bill_id") is not None else None
        invoice_number = (
            str(args["invoice_number"]) if args.get("invoice_number") else None
        )
        async with session_factory() as session:
            service = InvoiceService(session)
            result = await service.resolve_bill(
                chat_id,
                bill_id=bill_id,
                invoice_number=invoice_number,
            )
            if isinstance(result, Bill):
                return _tool_response(
                    serialize_resolved_bill_result(resolved_bill_from_model(result))
                )
            return _tool_response(serialize_invoice_refused_result(result))

    @tool(
        "send_invoice_pdf",
        "Generate a GST invoice PDF for a finalized Bill and send it as a "
        "Telegram document. Omit bill_id/invoice_number to use the most recent Bill.",
        {
            "bill_id": int,
            "invoice_number": str,
        },
    )
    async def send_invoice_pdf_tool(args: dict[str, Any]) -> dict[str, Any]:
        chat_id = require_chat_id()
        owner_telegram_user_id = require_owner_user_id()
        bill_id = int(args["bill_id"]) if args.get("bill_id") is not None else None
        invoice_number = (
            str(args["invoice_number"]) if args.get("invoice_number") else None
        )
        async with session_factory() as session:
            service = InvoiceService(session)
            resolved = await service.resolve_bill(
                chat_id,
                bill_id=bill_id,
                invoice_number=invoice_number,
            )
            if isinstance(resolved, InvoiceRefusedResult):
                return _tool_response(serialize_invoice_refused_result(resolved))

            pdf_result = await service.generate_invoice_pdf(
                resolved.bill_id,
                owner_telegram_user_id=owner_telegram_user_id,
            )
            if isinstance(pdf_result, InvoiceRefusedResult):
                return _tool_response(serialize_invoice_refused_result(pdf_result))

            await message_sender.send_document(
                chat_id=chat_id,
                filename=pdf_result.filename,
                data=pdf_result.pdf_bytes,
                caption=f"Invoice {pdf_result.invoice_number}",
            )
            return _tool_response(serialize_invoice_pdf_result(pdf_result))

    return [
        set_shop_profile_tool,
        get_shop_profile_tool,
        find_bill_tool,
        send_invoice_pdf_tool,
    ]


def _serialize_shop_profile(
    result: ShopProfileResult | ShopProfileMissingResult,
) -> dict[str, object]:
    if isinstance(result, ShopProfileResult):
        return serialize_shop_profile_result(result)
    return serialize_shop_profile_missing_result(result)
