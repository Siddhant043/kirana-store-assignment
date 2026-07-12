"""Tests for UpdateHandler dedup seam and voice-note transcription path."""

from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Chat, Message, Update, User, Voice
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.bot.handler import HandleResult, MessageSender, UpdateHandler
from src.db.session import create_session_factory
from src.domain.voice import TranscriptionResult


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


class FakeVoiceDownloader:
    def __init__(self, audio: bytes = b"ogg-bytes") -> None:
        self.audio = audio
        self.downloaded_file_ids: list[str] = []

    async def download_voice(self, file_id: str) -> bytes:
        self.downloaded_file_ids.append(file_id)
        return self.audio


class FakeTranscriber:
    def __init__(
        self,
        result: TranscriptionResult | None = None,
    ) -> None:
        self.result = result or TranscriptionResult(
            status="ok",
            text="2kg sugar, 4 Maggi, UPI",
            reason=None,
        )
        self.calls: list[bytes] = []

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        filename: str = "voice.ogg",
    ) -> TranscriptionResult:
        del filename
        self.calls.append(audio_bytes)
        return self.result


def _text_update(update_id: int, chat_id: int, text: str) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=1,
            date=0,
            chat=Chat(id=chat_id, type="private"),
            from_user=User(id=chat_id, is_bot=False, first_name="Owner"),
            text=text,
        ),
    )


def _voice_update(
    update_id: int,
    chat_id: int,
    file_id: str = "voice-file-1",
) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=2,
            date=0,
            chat=Chat(id=chat_id, type="private"),
            from_user=User(id=chat_id, is_bot=False, first_name="Owner"),
            voice=Voice(
                file_id=file_id,
                file_unique_id=f"unique-{file_id}",
                duration=3,
            ),
        ),
    )


def _build_handler(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    agent: FakeAgent | None = None,
    sender: FakeMessageSender | None = None,
    downloader: FakeVoiceDownloader | None = None,
    transcriber: FakeTranscriber | None = None,
) -> tuple[
    UpdateHandler,
    FakeAgent,
    FakeMessageSender,
    FakeVoiceDownloader,
    FakeTranscriber,
]:
    resolved_agent = agent or FakeAgent()
    resolved_sender = sender or FakeMessageSender()
    resolved_downloader = downloader or FakeVoiceDownloader()
    resolved_transcriber = transcriber or FakeTranscriber()
    handler = UpdateHandler(
        session_factory=session_factory,
        agent=resolved_agent,
        message_sender=resolved_sender,
        voice_downloader=resolved_downloader,
        transcriber=resolved_transcriber,
    )
    return (
        handler,
        resolved_agent,
        resolved_sender,
        resolved_downloader,
        resolved_transcriber,
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
    handler, agent, sender, _, _ = _build_handler(handler_session_factory)

    first = _text_update(update_id=1001, chat_id=42, text="hi")
    duplicate = _text_update(update_id=1001, chat_id=42, text="hi")

    first_result = await handler.handle(first)
    duplicate_result = await handler.handle(duplicate)

    assert first_result == HandleResult(processed=True, replied=True)
    assert duplicate_result == HandleResult(processed=False, replied=False)
    assert agent.reply.await_count == 1
    assert sender.sent == [(42, "hello")]


@pytest.mark.asyncio
async def test_handler_persists_owner_chat_id(
    handler_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from src.domain.preferences import (
        OWNER_CHAT_ID_KEY,
        GetPreferenceResult,
        PreferencesService,
    )

    agent = FakeAgent()
    sender = FakeMessageSender()
    handler, _, _, _, _ = _build_handler(
        handler_session_factory,
        agent=agent,
        sender=sender,
    )
    await handler.handle(_text_update(update_id=3001, chat_id=777, text="hi"))

    async with handler_session_factory() as session:
        prefs = PreferencesService(session)
        # Owner id equals chat id when from_user is absent.
        got = await prefs.get_preference(777, OWNER_CHAT_ID_KEY)
    assert isinstance(got, GetPreferenceResult)
    assert got.preference_value == "777"


@pytest.mark.asyncio
async def test_new_clears_session_without_calling_agent(
    handler_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    handler, agent, sender, _, _ = _build_handler(handler_session_factory)

    result = await handler.handle(_text_update(update_id=2001, chat_id=42, text="/new"))

    assert result == HandleResult(processed=True, replied=True)
    assert agent.reply.await_count == 0
    assert agent.cleared_sessions == [42]
    assert len(sender.sent) == 1
    assert sender.sent[0][0] == 42
    assert "Preferences" in sender.sent[0][1]


@pytest.mark.asyncio
async def test_voice_note_reaches_same_agent_reply_path_as_text(
    handler_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    agent = FakeAgent()
    sender = FakeMessageSender()
    downloader = FakeVoiceDownloader(audio=b"voice-bytes")
    transcriber = FakeTranscriber(
        TranscriptionResult(
            status="ok",
            text="2kg sugar, 4 Maggi, UPI",
            reason=None,
        )
    )
    handler, _, _, _, _ = _build_handler(
        handler_session_factory,
        agent=agent,
        sender=sender,
        downloader=downloader,
        transcriber=transcriber,
    )

    text_result = await handler.handle(
        _text_update(update_id=3001, chat_id=42, text="2kg sugar, 4 Maggi, UPI")
    )
    text_kwargs = agent.reply.await_args.kwargs

    agent.reply.reset_mock()
    sender.sent.clear()

    voice_result = await handler.handle(
        _voice_update(update_id=3002, chat_id=42, file_id="voice-abc")
    )
    voice_kwargs = agent.reply.await_args.kwargs

    assert text_result == HandleResult(processed=True, replied=True)
    assert voice_result == HandleResult(processed=True, replied=True)
    assert downloader.downloaded_file_ids == ["voice-abc"]
    assert transcriber.calls == [b"voice-bytes"]
    assert voice_kwargs["chat_id"] == text_kwargs["chat_id"] == 42
    assert voice_kwargs["owner_message"] == text_kwargs["owner_message"]
    assert (
        voice_kwargs["owner_telegram_user_id"]
        == text_kwargs["owner_telegram_user_id"]
        == 42
    )
    assert agent.reply.await_count == 1
    assert sender.sent == [(42, "hello")]


@pytest.mark.asyncio
async def test_voice_transcription_failure_sends_error_without_agent_reply(
    handler_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    agent = FakeAgent()
    sender = FakeMessageSender()
    transcriber = FakeTranscriber(
        TranscriptionResult(
            status="failed",
            text=None,
            reason="transcription was empty or unclear",
        )
    )
    handler, _, _, _, _ = _build_handler(
        handler_session_factory,
        agent=agent,
        sender=sender,
        transcriber=transcriber,
    )

    result = await handler.handle(_voice_update(update_id=4001, chat_id=42))

    assert result == HandleResult(processed=True, replied=True)
    assert agent.reply.await_count == 0
    assert len(sender.sent) == 1
    assert sender.sent[0][0] == 42
    assert "could not understand" in sender.sent[0][1].lower() or (
        "transcription" in sender.sent[0][1].lower()
    )
