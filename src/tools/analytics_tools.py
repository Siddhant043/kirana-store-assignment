"""Analytics MCP tool handlers."""

import json
from datetime import date
from typing import Any

from claude_agent_sdk import tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.analytics import (
    AnalyticsService,
    serialize_daily_close_result,
    serialize_reorder_suggestions_result,
    serialize_weekly_sales_report_result,
)


def _tool_response(payload: dict[str, object]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload)}],
    }


def build_analytics_tools(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[Any]:
    @tool(
        "daily_close",
        "Read-only Daily Close for an IST business date. Omit business_date "
        "for today. Returns sales totals, tax, payment mode split, top items.",
        {
            "business_date": str,
        },
    )
    async def daily_close_tool(args: dict[str, Any]) -> dict[str, Any]:
        business_date = args.get("business_date")
        parsed_date = str(business_date) if business_date else None
        async with session_factory() as session:
            service = AnalyticsService(session)
            if parsed_date is not None:
                result = await service.daily_close(date.fromisoformat(parsed_date))
            else:
                result = await service.daily_close()
            return _tool_response(serialize_daily_close_result(result))

    @tool(
        "weekly_sales_report",
        "Read-only rolling 7-day IST sales report including today. "
        "Returns totals, tax, payment mode split, and top items.",
        {},
    )
    async def weekly_sales_report_tool(args: dict[str, Any]) -> dict[str, Any]:
        del args
        async with session_factory() as session:
            service = AnalyticsService(session)
            result = await service.weekly_sales_report()
            return _tool_response(serialize_weekly_sales_report_result(result))

    @tool(
        "reorder_suggestions",
        "Rank Products below Reorder Level by estimated days of stock remaining "
        "from recent sales velocity (rolling 7 IST days). Use for "
        "'what should I reorder?' / how fast stock is selling. "
        "Falls back to plain Reorder Level when a Product has no recent sales.",
        {},
    )
    async def reorder_suggestions_tool(args: dict[str, Any]) -> dict[str, Any]:
        del args
        async with session_factory() as session:
            service = AnalyticsService(session)
            result = await service.reorder_suggestions()
            return _tool_response(serialize_reorder_suggestions_result(result))

    return [daily_close_tool, weekly_sales_report_tool, reorder_suggestions_tool]
