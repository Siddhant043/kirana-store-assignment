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
    cleared_sessions: list[int] = field(default_factory=list)

    def clear_session(self, chat_id: int) -> None:
        self.cleared_sessions.append(chat_id)


class FakeMessageSender(MessageSender):
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.documents: list[tuple[int, str, bytes, str | None]] = []

    async def send_text(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))

    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption: str | None = None,
    ) -> None:
        self.documents.append((chat_id, filename, data, caption))


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


@pytest.mark.asyncio
async def test_new_clears_session_without_calling_agent(
    handler_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    agent = FakeAgent()
    sender = FakeMessageSender()
    handler = UpdateHandler(
        session_factory=handler_session_factory,
        agent=agent,
        message_sender=sender,
    )

    result = await handler.handle(_text_update(update_id=2001, chat_id=42, text="/new"))

    assert result == HandleResult(processed=True, replied=True)
    assert agent.reply.await_count == 0
    assert agent.cleared_sessions == [42]
    assert len(sender.sent) == 1
    assert sender.sent[0][0] == 42
    assert "Preferences" in sender.sent[0][1]
