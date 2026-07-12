"""SentJobsStore idempotency tests against Postgres."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.sent_jobs import RecordSentJobResult, SentJobsStore
from src.domain.preferences import WEEKLY_ANALYSIS_DECK_JOB_KEY

OWNER_ID = 9201
PERIOD = "2026-W29"


@pytest.mark.asyncio
async def test_record_sent_then_already_sent(
    inventory_session: AsyncSession,
) -> None:
    store = SentJobsStore(inventory_session)
    assert not await store.already_sent(
        OWNER_ID,
        WEEKLY_ANALYSIS_DECK_JOB_KEY,
        PERIOD,
    )
    first = await store.record_sent(
        OWNER_ID,
        WEEKLY_ANALYSIS_DECK_JOB_KEY,
        PERIOD,
    )
    assert first is RecordSentJobResult.RECORDED
    await inventory_session.flush()
    assert await store.already_sent(
        OWNER_ID,
        WEEKLY_ANALYSIS_DECK_JOB_KEY,
        PERIOD,
    )


@pytest.mark.asyncio
async def test_second_record_sent_is_duplicate(
    inventory_session: AsyncSession,
) -> None:
    store = SentJobsStore(inventory_session)
    await store.record_sent(OWNER_ID, WEEKLY_ANALYSIS_DECK_JOB_KEY, PERIOD)
    await inventory_session.flush()
    second = await store.record_sent(
        OWNER_ID,
        WEEKLY_ANALYSIS_DECK_JOB_KEY,
        PERIOD,
    )
    assert second is RecordSentJobResult.DUPLICATE
