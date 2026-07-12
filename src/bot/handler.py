"""Telegram update handler with transport-level idempotency."""

from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from aiogram.types import Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.agent.harness import AgentHarness
from src.db.processed_updates import ProcessedUpdatesStore, RecordUpdateResult
from src.db.session import session_scope
from src.domain.voice import VoiceTranscriber

VOICE_TRANSCRIPTION_FAILURE_MESSAGE = (
    "Sorry — I could not understand that voice note. "
    "Please try again, or type the order as text."
)


class MessageSender(Protocol):
    async def send_text(self, chat_id: int, text: str) -> None: ...

    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption: str | None = None,
    ) -> None: ...


class VoiceAudioDownloader(Protocol):
    async def download_voice(self, file_id: str) -> bytes: ...


@dataclass(frozen=True)
class HandleResult:
    processed: bool
    replied: bool


class UpdateHandler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        agent: AgentHarness,
        message_sender: MessageSender,
        voice_downloader: VoiceAudioDownloader,
        transcriber: VoiceTranscriber,
    ) -> None:
        self._session_factory = session_factory
        self._agent = agent
        self._message_sender = message_sender
        self._voice_downloader = voice_downloader
        self._transcriber = transcriber

    async def handle(self, update: Update) -> HandleResult:
        if update.update_id is None:
            return HandleResult(processed=False, replied=False)

        message = update.message
        if message is None or message.chat is None:
            return HandleResult(processed=False, replied=False)
        if message.text is None and message.voice is None:
            return HandleResult(processed=False, replied=False)

        async with session_scope(self._session_factory) as session:
            store = ProcessedUpdatesStore(session)
            record_result = await store.try_record(update.update_id)
            if record_result is RecordUpdateResult.DUPLICATE:
                return HandleResult(processed=False, replied=False)

        owner_telegram_user_id = (
            message.from_user.id if message.from_user is not None else message.chat.id
        )

        owner_message: str | None
        if message.voice is not None:
            audio_bytes = await self._voice_downloader.download_voice(
                message.voice.file_id
            )
            transcription = await self._transcriber.transcribe(audio_bytes)
            if transcription.status != "ok" or transcription.text is None:
                await self._message_sender.send_text(
                    chat_id=message.chat.id,
                    text=VOICE_TRANSCRIPTION_FAILURE_MESSAGE,
                )
                return HandleResult(processed=True, replied=True)
            owner_message = transcription.text
        else:
            # Text path: early guard requires text or voice.
            owner_message = message.text or ""

        if owner_message.strip().lower() == "/new":
            self._agent.clear_session(message.chat.id)
            await self._message_sender.send_text(
                chat_id=message.chat.id,
                text=(
                    "Started a fresh session. "
                    "Your Preferences and Shop Profile are unchanged."
                ),
            )
            return HandleResult(processed=True, replied=True)

        reply_text = await self._agent.reply(
            chat_id=message.chat.id,
            owner_message=owner_message,
            owner_telegram_user_id=owner_telegram_user_id,
        )
        await self._message_sender.send_text(
            chat_id=message.chat.id,
            text=reply_text,
        )
        return HandleResult(processed=True, replied=True)


class TelegramMessageSender:
    def __init__(self, bot: object) -> None:
        self._bot = bot

    async def send_text(self, chat_id: int, text: str) -> None:
        from aiogram import Bot

        if isinstance(self._bot, Bot):
            await self._bot.send_message(chat_id=chat_id, text=text)

    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption: str | None = None,
    ) -> None:
        from aiogram import Bot
        from aiogram.types import BufferedInputFile

        if isinstance(self._bot, Bot):
            document = BufferedInputFile(file=data, filename=filename)
            await self._bot.send_document(
                chat_id=chat_id,
                document=document,
                caption=caption,
            )


class TelegramVoiceDownloader:
    def __init__(self, bot: object) -> None:
        self._bot = bot

    async def download_voice(self, file_id: str) -> bytes:
        from aiogram import Bot

        if not isinstance(self._bot, Bot):
            msg = "TelegramVoiceDownloader requires an aiogram Bot"
            raise TypeError(msg)
        file = await self._bot.get_file(file_id)
        if file.file_path is None:
            msg = "Telegram voice file path is missing"
            raise ValueError(msg)
        buffer = BytesIO()
        await self._bot.download_file(file.file_path, destination=buffer)
        return buffer.getvalue()
