"""Durable record of scheduled job deliveries (idempotency)."""

from enum import Enum

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import SentJob


class RecordSentJobResult(Enum):
    RECORDED = "recorded"
    DUPLICATE = "duplicate"


class SentJobsStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def already_sent(
        self,
        owner_telegram_user_id: int,
        job_key: str,
        period_key: str,
    ) -> bool:
        result = await self._session.execute(
            select(SentJob).where(
                SentJob.owner_telegram_user_id == owner_telegram_user_id,
                SentJob.job_key == job_key,
                SentJob.period_key == period_key,
            )
        )
        return result.scalar_one_or_none() is not None

    async def record_sent(
        self,
        owner_telegram_user_id: int,
        job_key: str,
        period_key: str,
    ) -> RecordSentJobResult:
        stmt = (
            pg_insert(SentJob)
            .values(
                owner_telegram_user_id=owner_telegram_user_id,
                job_key=job_key,
                period_key=period_key,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "owner_telegram_user_id",
                    "job_key",
                    "period_key",
                ]
            )
            .returning(SentJob.owner_telegram_user_id)
        )
        result = await self._session.execute(stmt)
        inserted = result.scalar_one_or_none()
        if inserted is None:
            return RecordSentJobResult.DUPLICATE
        return RecordSentJobResult.RECORDED
