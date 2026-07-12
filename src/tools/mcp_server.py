"""MCP server factories for inventory, billing, khata, analytics, and documents."""

from typing import Any

from claude_agent_sdk import create_sdk_mcp_server
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.tools.analytics_tools import build_analytics_tools
from src.tools.billing_tools import build_billing_tools
from src.tools.documents_tools import DocumentSender, build_documents_tools
from src.tools.inventory_tools import build_inventory_tools
from src.tools.khata_tools import build_khata_tools

INVENTORY_ALLOWED_TOOLS = [
    "mcp__inventory__find_product",
    "mcp__inventory__add_product",
    "mcp__inventory__receive_stock",
    "mcp__inventory__get_stock",
    "mcp__inventory__list_low_stock",
]

BILLING_ALLOWED_TOOLS = [
    "mcp__billing__open_draft_bill",
    "mcp__billing__add_line",
    "mcp__billing__update_line",
    "mcp__billing__remove_line",
    "mcp__billing__view_draft",
    "mcp__billing__finalize_bill",
]

KHATA_ALLOWED_TOOLS = [
    "mcp__khata__find_or_create_customer",
    "mcp__khata__add_khata_charge",
    "mcp__khata__record_payment",
    "mcp__khata__get_khata_balance",
]

ANALYTICS_ALLOWED_TOOLS = [
    "mcp__analytics__daily_close",
    "mcp__analytics__weekly_sales_report",
]

DOCUMENTS_ALLOWED_TOOLS = [
    "mcp__documents__set_shop_profile",
    "mcp__documents__get_shop_profile",
    "mcp__documents__find_bill",
    "mcp__documents__send_invoice_pdf",
    "mcp__documents__send_analysis_deck",
]

ALL_STORE_ALLOWED_TOOLS = (
    INVENTORY_ALLOWED_TOOLS
    + BILLING_ALLOWED_TOOLS
    + KHATA_ALLOWED_TOOLS
    + ANALYTICS_ALLOWED_TOOLS
    + DOCUMENTS_ALLOWED_TOOLS
)


def create_inventory_mcp_server(
    session_factory: async_sessionmaker[AsyncSession],
) -> Any:
    tools = build_inventory_tools(session_factory)
    return create_sdk_mcp_server(
        name="inventory",
        version="1.0.0",
        tools=tools,
    )


def create_billing_mcp_server(
    session_factory: async_sessionmaker[AsyncSession],
) -> Any:
    tools = build_billing_tools(session_factory)
    return create_sdk_mcp_server(
        name="billing",
        version="1.0.0",
        tools=tools,
    )


def create_khata_mcp_server(
    session_factory: async_sessionmaker[AsyncSession],
) -> Any:
    tools = build_khata_tools(session_factory)
    return create_sdk_mcp_server(
        name="khata",
        version="1.0.0",
        tools=tools,
    )


def create_analytics_mcp_server(
    session_factory: async_sessionmaker[AsyncSession],
) -> Any:
    tools = build_analytics_tools(session_factory)
    return create_sdk_mcp_server(
        name="analytics",
        version="1.0.0",
        tools=tools,
    )


def create_documents_mcp_server(
    session_factory: async_sessionmaker[AsyncSession],
    message_sender: DocumentSender,
) -> Any:
    tools = build_documents_tools(session_factory, message_sender)
    return create_sdk_mcp_server(
        name="documents",
        version="1.0.0",
        tools=tools,
    )
