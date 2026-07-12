"""APScheduler lifecycle for the in-process weekly analysis deck (ADR-0013)."""

import logging
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.handler import MessageSender
from src.db.models import Preference
from src.domain.preferences import (
    WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
    parse_weekly_deck_schedule,
)
from src.domain.shop_time import SHOP_TZ
from src.scheduler.weekly_deck import run_weekly_analysis_deck_job

logger = logging.getLogger(__name__)

MISFIRE_GRACE_SECONDS = 300
_WEEKLY_DECK_JOB_ID_PREFIX = "weekly_deck_"

ScheduleChangedCallback = Callable[[], Awaitable[None]]


def create_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone=SHOP_TZ)


def weekly_deck_job_id(owner_telegram_user_id: int) -> str:
    return f"{_WEEKLY_DECK_JOB_ID_PREFIX}{owner_telegram_user_id}"


def _make_weekly_deck_job(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    message_sender: MessageSender,
    owner_telegram_user_id: int,
) -> Callable[[], Awaitable[None]]:
    async def job() -> None:
        outcome = await run_weekly_analysis_deck_job(
            session_factory=session_factory,
            message_sender=message_sender,
            owner_telegram_user_id=owner_telegram_user_id,
        )
        logger.info(
            "Weekly analysis deck job owner=%s outcome=%s",
            owner_telegram_user_id,
            outcome,
        )

    return job


async def refresh_weekly_deck_jobs(
    scheduler: AsyncIOScheduler,
    session_factory: async_sessionmaker[AsyncSession],
    message_sender: MessageSender,
) -> None:
    """Load schedule Preferences and (re)register CronTriggers per Owner."""
    async with session_factory() as session:
        result = await session.execute(
            select(Preference).where(
                Preference.preference_key == WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY
            )
        )
        rows = list(result.scalars().all())

    for job in list(scheduler.get_jobs()):
        if job.id and job.id.startswith(_WEEKLY_DECK_JOB_ID_PREFIX):
            scheduler.remove_job(job.id)

    for row in rows:
        try:
            day, hour, minute = parse_weekly_deck_schedule(row.preference_value)
        except ValueError:
            logger.warning(
                "Skipping invalid weekly deck schedule for owner=%s value=%r",
                row.owner_telegram_user_id,
                row.preference_value,
            )
            continue

        owner_id = row.owner_telegram_user_id
        scheduler.add_job(
            _make_weekly_deck_job(
                session_factory=session_factory,
                message_sender=message_sender,
                owner_telegram_user_id=owner_id,
            ),
            trigger=CronTrigger(
                day_of_week=day,
                hour=hour,
                minute=minute,
                timezone=SHOP_TZ,
            ),
            id=weekly_deck_job_id(owner_id),
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=MISFIRE_GRACE_SECONDS,
            max_instances=1,
        )
        logger.info(
            "Scheduled weekly analysis deck owner=%s at %s %02d:%02d IST",
            owner_id,
            day,
            hour,
            minute,
        )


def start_scheduler(scheduler: AsyncIOScheduler) -> None:
    if not scheduler.running:
        scheduler.start()
        logger.info("AsyncIOScheduler started")


def shutdown_scheduler(scheduler: AsyncIOScheduler) -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("AsyncIOScheduler shut down")
