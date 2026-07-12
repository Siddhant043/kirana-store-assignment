"""Telegram update handler with transport-level idempotency."""

from dataclasses import dataclass
from typing import Protocol

from aiogram.types import Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.agent.harness import AgentHarness
from src.db.processed_updates import ProcessedUpdatesStore, RecordUpdateResult
from src.db.session import session_scope
from src.domain.preferences import OWNER_CHAT_ID_KEY, PreferencesService


class MessageSender(Protocol):
    async def send_text(self, chat_id: int, text: str) -> None: ...

    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption: str | None = None,
    ) -> None: ...


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
    ) -> None:
        self._session_factory = session_factory
        self._agent = agent
        self._message_sender = message_sender

    async def handle(self, update: Update) -> HandleResult:
        if update.update_id is None:
            return HandleResult(processed=False, replied=False)

        message = update.message
        if message is None or message.text is None or message.chat is None:
            return HandleResult(processed=False, replied=False)

        async with session_scope(self._session_factory) as session:
            store = ProcessedUpdatesStore(session)
            record_result = await store.try_record(update.update_id)
            if record_result is RecordUpdateResult.DUPLICATE:
                return HandleResult(processed=False, replied=False)

        owner_telegram_user_id = (
            message.from_user.id if message.from_user is not None else message.chat.id
        )

        async with session_scope(self._session_factory) as session:
            preferences = PreferencesService(session)
            await preferences.set_preference(
                owner_telegram_user_id,
                OWNER_CHAT_ID_KEY,
                str(message.chat.id),
            )

        if message.text.strip().lower() == "/new":
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
            owner_message=message.text,
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
