"""MCP server factories for inventory and billing tools."""

from typing import Any

from claude_agent_sdk import create_sdk_mcp_server
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.tools.billing_tools import build_billing_tools
from src.tools.inventory_tools import build_inventory_tools

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

ALL_STORE_ALLOWED_TOOLS = INVENTORY_ALLOWED_TOOLS + BILLING_ALLOWED_TOOLS


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
