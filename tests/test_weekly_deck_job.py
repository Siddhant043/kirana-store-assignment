"""Weekly analysis deck job integration tests (no APScheduler clock)."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.db.session import create_session_factory
from src.domain.analysis_deck_delivery import AnalysisDeckDeliveryResult
from src.domain.preferences import (
    OWNER_CHAT_ID_KEY,
    WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
    PreferencesService,
)
from src.domain.shop_time import SHOP_TZ
from src.scheduler.weekly_deck import run_weekly_analysis_deck_job

OWNER_ID = 9301
CHAT_ID = 9301


class FakeMessageSender:
    def __init__(self) -> None:
        self.documents: list[tuple[int, str, bytes, str | None]] = []

    async def send_text(self, chat_id: int, text: str) -> None:
        return None

    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption: str | None = None,
    ) -> None:
        self.documents.append((chat_id, filename, data, caption))


@pytest.fixture
async def job_session_factory(
    db_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(db_engine)


@pytest.mark.asyncio
async def test_weekly_deck_job_sends_once_then_skips(
    job_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with job_session_factory() as session:
        async with session.begin():
            prefs = PreferencesService(session)
            await prefs.set_preference(
                OWNER_ID,
                WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
                "mon 09:00",
            )
            await prefs.set_preference(OWNER_ID, OWNER_CHAT_ID_KEY, str(CHAT_ID))

    sender = FakeMessageSender()
    clock = lambda: datetime(2026, 7, 13, 9, 0, tzinfo=SHOP_TZ)  # noqa: E731

    fake_delivery = AnalysisDeckDeliveryResult(
        status="ok",
        filename="analysis-fake.pptx",
        period_start="2026-07-07",
        period_end="2026-07-13",
        bill_count=0,
        total_sales_paise=0,
    )

    with patch(
        "src.scheduler.weekly_deck.send_weekly_analysis_deck_to_chat",
        new_callable=AsyncMock,
        return_value=fake_delivery,
    ) as send_mock:
        first = await run_weekly_analysis_deck_job(
            session_factory=job_session_factory,
            message_sender=sender,
            owner_telegram_user_id=OWNER_ID,
            clock=clock,
        )
        second = await run_weekly_analysis_deck_job(
            session_factory=job_session_factory,
            message_sender=sender,
            owner_telegram_user_id=OWNER_ID,
            clock=clock,
        )

    assert first == "sent"
    assert second == "skipped_already_sent"
    assert send_mock.await_count == 1


@pytest.mark.asyncio
async def test_weekly_deck_job_skips_without_chat_id(
    job_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with job_session_factory() as session:
        async with session.begin():
            prefs = PreferencesService(session)
            await prefs.set_preference(
                OWNER_ID + 1,
                WEEKLY_ANALYSIS_DECK_SCHEDULE_KEY,
                "tue 10:00",
            )

    outcome = await run_weekly_analysis_deck_job(
        session_factory=job_session_factory,
        message_sender=FakeMessageSender(),
        owner_telegram_user_id=OWNER_ID + 1,
        clock=lambda: datetime(2026, 7, 14, 10, 0, tzinfo=SHOP_TZ),
    )
    assert outcome == "skipped_missing_chat"
