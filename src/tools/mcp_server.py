"""MCP server factory for inventory tools."""

from typing import Any

from claude_agent_sdk import create_sdk_mcp_server
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.tools.inventory_tools import build_inventory_tools

INVENTORY_ALLOWED_TOOLS = [
    "mcp__inventory__find_product",
    "mcp__inventory__add_product",
    "mcp__inventory__receive_stock",
    "mcp__inventory__get_stock",
    "mcp__inventory__list_low_stock",
]


def create_inventory_mcp_server(
    session_factory: async_sessionmaker[AsyncSession],
) -> Any:
    tools = build_inventory_tools(session_factory)
    return create_sdk_mcp_server(
        name="inventory",
        version="1.0.0",
        tools=tools,
    )
