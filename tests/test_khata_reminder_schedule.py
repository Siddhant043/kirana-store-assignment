"""Khata reminder schedule and threshold Preference tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.preferences import (
    KHATA_REMINDER_SCHEDULE_KEY,
    KHATA_REMINDER_THRESHOLD_PAISE_KEY,
    GetPreferenceResult,
    PreferenceRefusedResult,
    PreferencesService,
    ist_calendar_day_period_key,
    parse_khata_reminder_schedule,
)
from src.domain.shop_time import SHOP_TZ

OWNER_ID = 9201


@pytest.mark.asyncio
async def test_set_khata_reminder_schedule_persists(
    inventory_session: AsyncSession,
) -> None:
    service = PreferencesService(inventory_session)
    result = await service.set_preference(
        OWNER_ID,
        KHATA_REMINDER_SCHEDULE_KEY,
        "9:00",
    )
    assert result.status == "ok"
    assert result.preference_value == "09:00"  # type: ignore[union-attr]

    got = await service.get_preference(OWNER_ID, KHATA_REMINDER_SCHEDULE_KEY)
    assert isinstance(got, GetPreferenceResult)
    assert got.preference_value == "09:00"


@pytest.mark.asyncio
async def test_invalid_khata_reminder_schedule_refused(
    inventory_session: AsyncSession,
) -> None:
    service = PreferencesService(inventory_session)
    result = await service.set_preference(
        OWNER_ID,
        KHATA_REMINDER_SCHEDULE_KEY,
        "25:99",
    )
    assert isinstance(result, PreferenceRefusedResult)
    assert result.reason == "invalid_khata_reminder_schedule"


@pytest.mark.asyncio
async def test_set_khata_reminder_threshold_persists(
    inventory_session: AsyncSession,
) -> None:
    service = PreferencesService(inventory_session)
    result = await service.set_preference(
        OWNER_ID,
        KHATA_REMINDER_THRESHOLD_PAISE_KEY,
        "50000",
    )
    assert result.status == "ok"
    assert result.preference_value == "50000"  # type: ignore[union-attr]

    got = await service.get_preference(OWNER_ID, KHATA_REMINDER_THRESHOLD_PAISE_KEY)
    assert isinstance(got, GetPreferenceResult)
    assert got.preference_value == "50000"


@pytest.mark.asyncio
async def test_invalid_khata_reminder_threshold_refused(
    inventory_session: AsyncSession,
) -> None:
    service = PreferencesService(inventory_session)
    result = await service.set_preference(
        OWNER_ID,
        KHATA_REMINDER_THRESHOLD_PAISE_KEY,
        "-100",
    )
    assert isinstance(result, PreferenceRefusedResult)
    assert result.reason == "invalid_khata_reminder_threshold_paise"


def test_parse_khata_reminder_schedule() -> None:
    hour, minute = parse_khata_reminder_schedule("09:30")
    assert hour == 9
    assert minute == 30


def test_ist_calendar_day_period_key() -> None:
    moment = datetime(2026, 7, 12, 23, 30, tzinfo=SHOP_TZ)
    assert ist_calendar_day_period_key(moment) == "2026-07-12"
    assert moment.tzinfo == ZoneInfo("Asia/Kolkata")
