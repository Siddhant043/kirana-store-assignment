"""Daily Khata reminder digest job (ADR-0013)."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.handler import MessageSender
from src.db.sent_jobs import SentJobsStore
from src.domain.invoice import format_paise_as_rupees
from src.domain.khata import (
    CustomerBalanceRow,
    KhataService,
    ListCustomersAboveThresholdResult,
)
from src.domain.preferences import (
    KHATA_REMINDER_SCHEDULE_KEY,
    KHATA_REMINDER_THRESHOLD_PAISE_KEY,
    KHATA_REMINDERS_JOB_KEY,
    OWNER_CHAT_ID_KEY,
    GetPreferenceResult,
    PreferencesService,
    ist_calendar_day_period_key,
)

KhataRemindersJobOutcome = Literal[
    "sent",
    "skipped_already_sent",
    "skipped_missing_chat",
    "skipped_no_schedule",
    "skipped_no_threshold",
]


def format_khata_reminders_digest(
    *,
    threshold_paise: int,
    customers: list[CustomerBalanceRow],
) -> str:
    threshold_rupees = format_paise_as_rupees(threshold_paise)
    header = (
        f"Khata reminders — Customers with outstanding balance "
        f"≥ ₹{threshold_rupees}:"
    )
    if not customers:
        return f"{header}\nNone above threshold today."

    lines = [header]
    for customer in customers:
        line = (
            f"• {customer.name} — "
            f"₹{format_paise_as_rupees(customer.balance_paise)}"
        )
        if customer.phone:
            line = f"{line} ({customer.phone})"
        lines.append(line)
    return "\n".join(lines)


async def run_khata_reminders_job(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    message_sender: MessageSender,
    owner_telegram_user_id: int,
    clock: Callable[[], datetime] | None = None,
) -> KhataRemindersJobOutcome:
    now = clock() if clock is not None else datetime.now(tz=UTC)
    period_key = ist_calendar_day_period_key(now)

    async with session_factory() as session:
        preferences = PreferencesService(session)
        schedule = await preferences.get_preference(
            owner_telegram_user_id,
            KHATA_REMINDER_SCHEDULE_KEY,
        )
        if not isinstance(schedule, GetPreferenceResult):
            return "skipped_no_schedule"

        threshold = await preferences.get_preference(
            owner_telegram_user_id,
            KHATA_REMINDER_THRESHOLD_PAISE_KEY,
        )
        if not isinstance(threshold, GetPreferenceResult):
            return "skipped_no_threshold"
        threshold_paise = int(threshold.preference_value)

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
            KHATA_REMINDERS_JOB_KEY,
            period_key,
        ):
            return "skipped_already_sent"

    async with session_factory() as session:
        async with session.begin():
            sent_jobs = SentJobsStore(session)
            if await sent_jobs.already_sent(
                owner_telegram_user_id,
                KHATA_REMINDERS_JOB_KEY,
                period_key,
            ):
                return "skipped_already_sent"

            khata = KhataService(session)
            scan = await khata.list_customers_above_threshold(threshold_paise)
            if not isinstance(scan, ListCustomersAboveThresholdResult):
                return "skipped_no_threshold"

            digest = format_khata_reminders_digest(
                threshold_paise=threshold_paise,
                customers=list(scan.customers),
            )
            await message_sender.send_text(chat_id=chat_id, text=digest)
            await sent_jobs.record_sent(
                owner_telegram_user_id,
                KHATA_REMINDERS_JOB_KEY,
                period_key,
            )
            return "sent"
