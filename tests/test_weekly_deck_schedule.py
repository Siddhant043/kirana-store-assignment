"""Weekly analysis deck schedule Preference tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.preferences import (
    OWNER_CHAT_ID_KEY,
    WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
    GetPreferenceResult,
    PreferenceRefusedResult,
    PreferencesService,
    ist_iso_week_period_key,
    parse_weekly_deck_schedule,
)
from src.domain.shop_time import SHOP_TZ

OWNER_ID = 9101


@pytest.mark.asyncio
async def test_set_weekly_deck_schedule_persists(
    inventory_session: AsyncSession,
) -> None:
    service = PreferencesService(inventory_session)
    result = await service.set_preference(
        OWNER_ID,
        WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
        "Monday 9:00",
    )
    assert result.status == "ok"
    assert result.preference_value == "mon 09:00"  # type: ignore[union-attr]

    got = await service.get_preference(OWNER_ID, WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY)
    assert isinstance(got, GetPreferenceResult)
    assert got.preference_value == "mon 09:00"


@pytest.mark.asyncio
async def test_invalid_weekly_deck_schedule_refused(
    inventory_session: AsyncSession,
) -> None:
    service = PreferencesService(inventory_session)
    result = await service.set_preference(
        OWNER_ID,
        WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
        "funday 99:99",
    )
    assert isinstance(result, PreferenceRefusedResult)
    assert result.reason == "invalid_weekly_deck_schedule"


@pytest.mark.asyncio
async def test_owner_chat_id_preference_persists(
    inventory_session: AsyncSession,
) -> None:
    service = PreferencesService(inventory_session)
    result = await service.set_preference(OWNER_ID, OWNER_CHAT_ID_KEY, "424242")
    assert result.status == "ok"
    got = await service.get_preference(OWNER_ID, OWNER_CHAT_ID_KEY)
    assert isinstance(got, GetPreferenceResult)
    assert got.preference_value == "424242"


@pytest.mark.asyncio
async def test_invalid_owner_chat_id_refused(
    inventory_session: AsyncSession,
) -> None:
    service = PreferencesService(inventory_session)
    result = await service.set_preference(OWNER_ID, OWNER_CHAT_ID_KEY, "not-a-id")
    assert isinstance(result, PreferenceRefusedResult)
    assert result.reason == "invalid_owner_chat_id"


def test_parse_weekly_deck_schedule() -> None:
    day, hour, minute = parse_weekly_deck_schedule("mon 09:00")
    assert day == "mon"
    assert hour == 9
    assert minute == 0


def test_ist_iso_week_period_key() -> None:
    # Monday 2026-07-13 IST is ISO week 2026-W29
    moment = datetime(2026, 7, 13, 10, 0, tzinfo=SHOP_TZ)
    assert ist_iso_week_period_key(moment) == "2026-W29"
    assert moment.tzinfo == ZoneInfo("Asia/Kolkata")
