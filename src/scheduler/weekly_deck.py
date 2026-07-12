"""Weekly analysis deck scheduled job (ADR-0013)."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.handler import MessageSender
from src.db.sent_jobs import SentJobsStore
from src.domain.analysis_deck_delivery import send_weekly_analysis_deck_to_chat
from src.domain.preferences import (
    OWNER_CHAT_ID_KEY,
    WEEKLY_ANALYSIS_DECK_JOB_KEY,
    WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
    GetPreferenceResult,
    PreferencesService,
    ist_iso_week_period_key,
)

WeeklyDeckJobOutcome = Literal[
    "sent",
    "skipped_already_sent",
    "skipped_missing_chat",
    "skipped_no_schedule",
]


async def run_weekly_analysis_deck_job(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    message_sender: MessageSender,
    owner_telegram_user_id: int,
    clock: Callable[[], datetime] | None = None,
) -> WeeklyDeckJobOutcome:
    now = clock() if clock is not None else datetime.now(tz=UTC)
    period_key = ist_iso_week_period_key(now)

    async with session_factory() as session:
        preferences = PreferencesService(session)
        schedule = await preferences.get_preference(
            owner_telegram_user_id,
            WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
        )
        if not isinstance(schedule, GetPreferenceResult):
            return "skipped_no_schedule"

        chat = await preferences.get_preference(
            owner_telegram_user_id,
            OWNER_CHAT_ID_KEY,
        )
        if not isinstance(chat, GetPreferenceResult):
            return "skipped_missing_chat"
        chat_id = int(chat.preference_value)

        sent_jobs = SentJobsStore(session)
        if await sent_jobs.already_sent(
            owner_telegram_user_id,
            WEEKLY_ANALYSIS_DECK_JOB_KEY,
            period_key,
        ):
            return "skipped_already_sent"

    async with session_factory() as session:
        async with session.begin():
            sent_jobs = SentJobsStore(session)
            if await sent_jobs.already_sent(
                owner_telegram_user_id,
                WEEKLY_ANALYSIS_DECK_JOB_KEY,
                period_key,
            ):
                return "skipped_already_sent"

            await send_weekly_analysis_deck_to_chat(
                session,
                message_sender,
                chat_id,
            )
            await sent_jobs.record_sent(
                owner_telegram_user_id,
                WEEKLY_ANALYSIS_DECK_JOB_KEY,
                period_key,
            )
            return "sent"
