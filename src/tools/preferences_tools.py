"""Preferences MCP tool handlers for Owner standing defaults."""

import json
from typing import Any

from claude_agent_sdk import tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.context import require_owner_user_id
from src.domain.preferences import (
    PreferenceRefusedResult,
    PreferencesService,
    serialize_list_preferences_result,
    serialize_preference_refused_result,
    serialize_set_preference_result,
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


def build_preferences_tools(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[Any]:
    @tool(
        "set_preference",
        "Persist an Owner Preference (default Payment Mode or preferred Product). "
        "For preferred products pass preference_key preferred_product:<query> "
        "and preference_value as the grounded product_id string.",
        {
            "preference_key": str,
            "preference_value": str,
        },
    )
    async def set_preference_tool(args: dict[str, Any]) -> dict[str, Any]:
        owner_telegram_user_id = require_owner_user_id()
        preference_key = str(args["preference_key"])
        preference_value = str(args["preference_value"])
        async with session_factory() as session:
            async with session.begin():
                service = PreferencesService(session)
                result = await service.set_preference(
                    owner_telegram_user_id,
                    preference_key,
                    preference_value,
                )
                if isinstance(result, PreferenceRefusedResult):
                    return _tool_response(
                        serialize_preference_refused_result(result),
                        is_error=True,
                    )
                return _tool_response(serialize_set_preference_result(result))

    @tool(
        "get_preferences",
        "List all Preferences for the current Owner.",
        {},
    )
    async def get_preferences_tool(_args: dict[str, Any]) -> dict[str, Any]:
        owner_telegram_user_id = require_owner_user_id()
        async with session_factory() as session:
            service = PreferencesService(session)
            result = await service.list_preferences(owner_telegram_user_id)
            return _tool_response(serialize_list_preferences_result(result))

    return [set_preference_tool, get_preferences_tool]
