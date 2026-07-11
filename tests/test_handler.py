"""Tests for UpdateHandler dedup seam."""

from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Chat, Message, Update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.bot.handler import HandleResult, MessageSender, UpdateHandler
from src.db.session import create_session_factory


@dataclass
class FakeAgent:
    reply: AsyncMock = field(default_factory=lambda: AsyncMock(return_value="hello"))


class FakeMessageSender(MessageSender):
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_text(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


def _text_update(update_id: int, chat_id: int, text: str) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=1,
            date=0,
            chat=Chat(id=chat_id, type="private"),
            text=text,
        ),
    )


@pytest.fixture
async def handler_session_factory(
    db_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(db_engine)


@pytest.mark.asyncio
async def test_handler_drops_duplicate_update_without_calling_agent(
    handler_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    agent = FakeAgent()
    sender = FakeMessageSender()
    handler = UpdateHandler(
        session_factory=handler_session_factory,
        agent=agent,
        message_sender=sender,
    )

    first = _text_update(update_id=1001, chat_id=42, text="hi")
    duplicate = _text_update(update_id=1001, chat_id=42, text="hi")

    first_result = await handler.handle(first)
    duplicate_result = await handler.handle(duplicate)

    assert first_result == HandleResult(processed=True, replied=True)
    assert duplicate_result == HandleResult(processed=False, replied=False)
    assert agent.reply.await_count == 1
    assert sender.sent == [(42, "hello")]
