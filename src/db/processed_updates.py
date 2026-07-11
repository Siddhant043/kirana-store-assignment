"""Transport-level idempotency: dedupe Telegram update_id at the edge."""

from enum import Enum

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ProcessedUpdate


class RecordUpdateResult(Enum):
    RECORDED = "recorded"
    DUPLICATE = "duplicate"


class ProcessedUpdatesStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def try_record(self, update_id: int) -> RecordUpdateResult:
        stmt = (
            pg_insert(ProcessedUpdate)
            .values(update_id=update_id)
            .on_conflict_do_nothing(index_elements=["update_id"])
            .returning(ProcessedUpdate.update_id)
        )
        result = await self._session.execute(stmt)
        inserted_row = result.scalar_one_or_none()
        if inserted_row is None:
            return RecordUpdateResult.DUPLICATE
        return RecordUpdateResult.RECORDED
