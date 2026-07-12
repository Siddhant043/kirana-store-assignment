"""Scheduler refresh registers CronTriggers from Preferences."""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.db.session import create_session_factory
from src.domain.preferences import (
    KHATA_REMINDER_SCHEDULE_KEY,
    WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
    PreferencesService,
)
from src.scheduler.lifecycle import (
    create_scheduler,
    khata_reminders_job_id,
    refresh_khata_reminder_jobs,
    refresh_scheduled_jobs,
    refresh_weekly_deck_jobs,
    weekly_deck_job_id,
)


class _NoopSender:
    async def send_text(self, chat_id: int, text: str) -> None:
        return None

    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption: str | None = None,
    ) -> None:
        return None


@pytest.mark.asyncio
async def test_refresh_weekly_deck_jobs_registers_cron(
    db_engine: AsyncEngine,
) -> None:
    session_factory: async_sessionmaker[AsyncSession] = create_session_factory(
        db_engine
    )
    owner_id = 9401
    async with session_factory() as session:
        async with session.begin():
            await PreferencesService(session).set_preference(
                owner_id,
                WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
                "wed 14:30",
            )

    scheduler = create_scheduler()
    await refresh_weekly_deck_jobs(scheduler, session_factory, _NoopSender())
    job = scheduler.get_job(weekly_deck_job_id(owner_id))
    assert job is not None
    assert job.trigger is not None
    assert job.misfire_grace_time == 300


@pytest.mark.asyncio
async def test_refresh_khata_reminder_jobs_registers_on_same_scheduler(
    db_engine: AsyncEngine,
) -> None:
    session_factory: async_sessionmaker[AsyncSession] = create_session_factory(
        db_engine
    )
    owner_id = 9402
    async with session_factory() as session:
        async with session.begin():
            prefs = PreferencesService(session)
            await prefs.set_preference(
                owner_id,
                WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
                "mon 09:00",
            )
            await prefs.set_preference(
                owner_id,
                KHATA_REMINDER_SCHEDULE_KEY,
                "18:00",
            )

    scheduler = create_scheduler()
    await refresh_scheduled_jobs(scheduler, session_factory, _NoopSender())

    weekly = scheduler.get_job(weekly_deck_job_id(owner_id))
    khata = scheduler.get_job(khata_reminders_job_id(owner_id))
    assert weekly is not None
    assert khata is not None
    assert weekly.misfire_grace_time == 300
    assert khata.misfire_grace_time == 300
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert weekly_deck_job_id(owner_id) in job_ids
    assert khata_reminders_job_id(owner_id) in job_ids


@pytest.mark.asyncio
async def test_refresh_khata_reminder_jobs_alone_registers_cron(
    db_engine: AsyncEngine,
) -> None:
    session_factory: async_sessionmaker[AsyncSession] = create_session_factory(
        db_engine
    )
    owner_id = 9403
    async with session_factory() as session:
        async with session.begin():
            await PreferencesService(session).set_preference(
                owner_id,
                KHATA_REMINDER_SCHEDULE_KEY,
                "07:15",
            )

    scheduler = create_scheduler()
    await refresh_khata_reminder_jobs(scheduler, session_factory, _NoopSender())
    job = scheduler.get_job(khata_reminders_job_id(owner_id))
    assert job is not None
    assert job.misfire_grace_time == 300
