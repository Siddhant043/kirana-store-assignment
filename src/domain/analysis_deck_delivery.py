"""Shared analysis deck generation and Telegram delivery (on-request + scheduled)."""

from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.analysis_deck import (
    compose_insights,
    gather_analysis_deck_data,
    generate_analysis_deck,
)
from src.domain.doc_gen import run_cpu_bound


class DocumentDelivery(Protocol):
    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption: str | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class AnalysisDeckDeliveryResult:
    status: Literal["ok"]
    filename: str
    period_start: str
    period_end: str
    bill_count: int
    total_sales_paise: int


async def send_weekly_analysis_deck_to_chat(
    session: AsyncSession,
    message_sender: DocumentDelivery,
    chat_id: int,
    *,
    day_count: int = 7,
) -> AnalysisDeckDeliveryResult:
    """Gather, render (via run_cpu_bound), and send the analysis deck."""
    deck_data = await gather_analysis_deck_data(session, day_count=day_count)
    insights_text = compose_insights(deck_data)
    pptx_bytes = await run_cpu_bound(
        generate_analysis_deck,
        deck_data,
        insights_text,
    )
    filename = f"analysis-{deck_data.period_start}-to-{deck_data.period_end}.pptx"
    await message_sender.send_document(
        chat_id=chat_id,
        filename=filename,
        data=pptx_bytes,
        caption=(f"Analysis deck {deck_data.period_start} to {deck_data.period_end}"),
    )
    return AnalysisDeckDeliveryResult(
        status="ok",
        filename=filename,
        period_start=deck_data.period_start,
        period_end=deck_data.period_end,
        bill_count=deck_data.bill_count,
        total_sales_paise=deck_data.total_sales_paise,
    )
