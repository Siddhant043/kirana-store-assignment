"""Documents MCP tool handlers for invoices and Shop Profile."""

import json
from typing import Any, Protocol

from claude_agent_sdk import tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.context import require_chat_id, require_owner_user_id
from src.db.models import Bill
from src.domain.analysis_deck_delivery import send_weekly_analysis_deck_to_chat
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
    ShopProfileRefusedResult,
    ShopProfileResult,
    ShopProfileService,
    serialize_shop_profile_missing_result,
    serialize_shop_profile_refused_result,
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
        "Create or update the Shop Profile (shop name, address, GSTIN, "
        "optional logo_url and accent_color) printed on invoice PDFs. "
        "Omit logo_url/accent_color to leave existing branding unchanged; "
        "pass empty string to clear a branding field.",
        {
            "shop_name": str,
            "address": str,
            "gstin": str,
            "logo_url": str,
            "accent_color": str,
        },
    )
    async def set_shop_profile_tool(args: dict[str, Any]) -> dict[str, Any]:
        owner_telegram_user_id = require_owner_user_id()
        shop_name = str(args["shop_name"])
        address = str(args["address"]) if args.get("address") else None
        gstin = str(args["gstin"]) if args.get("gstin") else None
        branding_kwargs: dict[str, str | None] = {}
        if "logo_url" in args:
            raw_logo = args.get("logo_url")
            branding_kwargs["logo_url"] = (
                str(raw_logo) if raw_logo is not None else None
            )
        if "accent_color" in args:
            raw_accent = args.get("accent_color")
            branding_kwargs["accent_color"] = (
                str(raw_accent) if raw_accent is not None else None
            )
        async with session_factory() as session:
            async with session.begin():
                service = ShopProfileService(session)
                result = await service.set_shop_profile(
                    owner_telegram_user_id,
                    shop_name=shop_name,
                    address=address,
                    gstin=gstin,
                    **branding_kwargs,
                )
                if isinstance(result, ShopProfileRefusedResult):
                    return _tool_response(
                        serialize_shop_profile_refused_result(result),
                        is_error=True,
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

    @tool(
        "send_analysis_deck",
        "Generate this week's sales analysis deck (.pptx) with native charts "
        "for sales trend, top items, Payment Mode mix, GST by GST Slab, and "
        "stock health, then send it as a Telegram document.",
        {
            "day_count": int,
        },
    )
    async def send_analysis_deck_tool(args: dict[str, Any]) -> dict[str, Any]:
        chat_id = require_chat_id()
        day_count = int(args["day_count"]) if args.get("day_count") is not None else 7
        async with session_factory() as session:
            delivery = await send_weekly_analysis_deck_to_chat(
                session,
                message_sender,
                chat_id,
                day_count=day_count,
            )
            return _tool_response(
                {
                    "status": delivery.status,
                    "filename": delivery.filename,
                    "period_start": delivery.period_start,
                    "period_end": delivery.period_end,
                    "bill_count": delivery.bill_count,
                    "total_sales_paise": delivery.total_sales_paise,
                }
            )

    return [
        set_shop_profile_tool,
        get_shop_profile_tool,
        find_bill_tool,
        send_invoice_pdf_tool,
        send_analysis_deck_tool,
    ]


def _serialize_shop_profile(
    result: ShopProfileResult | ShopProfileMissingResult,
) -> dict[str, object]:
    if isinstance(result, ShopProfileResult):
        return serialize_shop_profile_result(result)
    return serialize_shop_profile_missing_result(result)
