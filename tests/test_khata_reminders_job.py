"""Khata reminders job integration tests (no APScheduler clock)."""

from datetime import datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.db.models import Customer, KhataEntry
from src.db.session import create_session_factory
from src.domain.preferences import (
    KHATA_REMINDER_SCHEDULE_KEY,
    KHATA_REMINDER_THRESHOLD_PAISE_KEY,
    OWNER_CHAT_ID_KEY,
    PreferencesService,
)
from src.domain.shop_time import SHOP_TZ
from src.scheduler.khata_reminders import run_khata_reminders_job

OWNER_ID = 9501
CHAT_ID = 9501


class FakeMessageSender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_text(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))

    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption: str | None = None,
    ) -> None:
        del chat_id, filename, data, caption


@pytest.fixture
async def job_session_factory(
    db_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(db_engine)


async def _seed_prefs(
    session_factory: async_sessionmaker[AsyncSession],
    owner_id: int,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            prefs = PreferencesService(session)
            await prefs.set_preference(
                owner_id,
                KHATA_REMINDER_SCHEDULE_KEY,
                "09:00",
            )
            await prefs.set_preference(
                owner_id,
                KHATA_REMINDER_THRESHOLD_PAISE_KEY,
                "50000",
            )
            await prefs.set_preference(owner_id, OWNER_CHAT_ID_KEY, str(CHAT_ID))


async def _seed_customer_above_threshold(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    name: str,
) -> int:
    async with session_factory() as session:
        async with session.begin():
            customer = Customer(name=name, phone="9999999999")
            session.add(customer)
            await session.flush()
            session.add(
                KhataEntry(
                    customer_id=customer.customer_id,
                    entry_type="charge",
                    amount_paise=75_000,
                )
            )
            return customer.customer_id


async def _delete_customer(
    session_factory: async_sessionmaker[AsyncSession],
    customer_id: int,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                delete(KhataEntry).where(KhataEntry.customer_id == customer_id)
            )
            await session.execute(
                delete(Customer).where(Customer.customer_id == customer_id)
            )


@pytest.mark.asyncio
async def test_khata_reminders_job_sends_once_then_skips(
    job_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_prefs(job_session_factory, OWNER_ID)
    customer_id = await _seed_customer_above_threshold(
        job_session_factory,
        name="Reminder Idempotent Ramesh",
    )
    sender = FakeMessageSender()
    clock = lambda: datetime(2026, 7, 12, 9, 0, tzinfo=SHOP_TZ)  # noqa: E731

    try:
        first = await run_khata_reminders_job(
            session_factory=job_session_factory,
            message_sender=sender,
            owner_telegram_user_id=OWNER_ID,
            clock=clock,
        )
        second = await run_khata_reminders_job(
            session_factory=job_session_factory,
            message_sender=sender,
            owner_telegram_user_id=OWNER_ID,
            clock=clock,
        )
    finally:
        await _delete_customer(job_session_factory, customer_id)

    assert first == "sent"
    assert second == "skipped_already_sent"
    assert len(sender.sent) == 1


@pytest.mark.asyncio
async def test_khata_reminders_job_digest_includes_above_threshold_customers(
    job_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_prefs(job_session_factory, OWNER_ID + 1)
    customer_id = await _seed_customer_above_threshold(
        job_session_factory,
        name="Reminder Digest Ramesh",
    )
    sender = FakeMessageSender()

    try:
        outcome = await run_khata_reminders_job(
            session_factory=job_session_factory,
            message_sender=sender,
            owner_telegram_user_id=OWNER_ID + 1,
            clock=lambda: datetime(2026, 7, 12, 9, 0, tzinfo=SHOP_TZ),
        )
    finally:
        await _delete_customer(job_session_factory, customer_id)

    assert outcome == "sent"
    assert len(sender.sent) == 1
    chat_id, text = sender.sent[0]
    assert chat_id == CHAT_ID
    assert "Reminder Digest Ramesh" in text
    assert "750.00" in text
    assert "9999999999" in text


@pytest.mark.asyncio
async def test_khata_reminders_job_skips_without_threshold(
    job_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with job_session_factory() as session:
        async with session.begin():
            prefs = PreferencesService(session)
            await prefs.set_preference(
                OWNER_ID + 2,
                KHATA_REMINDER_SCHEDULE_KEY,
                "10:00",
            )
            await prefs.set_preference(
                OWNER_ID + 2,
                OWNER_CHAT_ID_KEY,
                str(CHAT_ID),
            )

    outcome = await run_khata_reminders_job(
        session_factory=job_session_factory,
        message_sender=FakeMessageSender(),
        owner_telegram_user_id=OWNER_ID + 2,
        clock=lambda: datetime(2026, 7, 12, 10, 0, tzinfo=SHOP_TZ),
    )
    assert outcome == "skipped_no_threshold"
