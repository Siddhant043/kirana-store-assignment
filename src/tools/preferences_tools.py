"""Preferences MCP tool handlers for Owner standing defaults."""

import json
from collections.abc import Awaitable, Callable
from typing import Any

from claude_agent_sdk import tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.context import require_owner_user_id
from src.domain.preferences import (
    KHATA_REMINDER_SCHEDULE_KEY,
    WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
    PreferenceRefusedResult,
    PreferencesService,
    serialize_list_preferences_result,
    serialize_preference_refused_result,
    serialize_set_preference_result,
)

ScheduleChangedCallback = Callable[[], Awaitable[None]]


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
    *,
    on_schedule_changed: ScheduleChangedCallback | None = None,
) -> list[Any]:
    @tool(
        "set_preference",
        "Persist an Owner Preference (default Payment Mode, preferred Product, "
        "weekly_analysis_deck_schedule like 'mon 09:00' IST, "
        "khata_reminder_schedule like '09:00' IST, or "
        "khata_reminder_threshold_paise as integer paise).",
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
        schedule_keys = {
            WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
            KHATA_REMINDER_SCHEDULE_KEY,
        }
        if (
            on_schedule_changed is not None
            and preference_key.strip() in schedule_keys
        ):
            await on_schedule_changed()
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
