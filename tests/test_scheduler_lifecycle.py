"""Scheduler refresh registers CronTriggers from Preferences."""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.db.session import create_session_factory
from src.domain.preferences import (
    WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
    PreferencesService,
)
from src.scheduler.lifecycle import (
    create_scheduler,
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
