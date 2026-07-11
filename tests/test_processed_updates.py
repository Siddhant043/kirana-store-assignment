"""Tests for ProcessedUpdatesStore idempotency seam."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.processed_updates import ProcessedUpdatesStore, RecordUpdateResult


@pytest.mark.asyncio
async def test_try_record_returns_recorded_for_new_update_id(
    db_session: AsyncSession,
) -> None:
    store = ProcessedUpdatesStore(db_session)

    result = await store.try_record(42)

    assert result is RecordUpdateResult.RECORDED


@pytest.mark.asyncio
async def test_try_record_returns_duplicate_for_redelivered_update_id(
    db_session: AsyncSession,
) -> None:
    store = ProcessedUpdatesStore(db_session)
    await store.try_record(99)

    result = await store.try_record(99)

    assert result is RecordUpdateResult.DUPLICATE
