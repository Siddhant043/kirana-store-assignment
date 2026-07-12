"""Composition root: migrations, bot startup, long-polling, scheduler."""

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.types import Message, Update
from alembic.config import Config
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from src.agent.harness import ClaudeAgentHarness
from src.bot.handler import (
    MessageSender,
    TelegramMessageSender,
    TelegramPhotoDownloader,
    TelegramVoiceDownloader,
    UpdateHandler,
)
from src.config import Settings, load_settings
from src.db.session import create_engine, create_session_factory
from src.domain.voice import WhisperTranscriber
from src.scheduler.lifecycle import (
    create_scheduler,
    refresh_scheduled_jobs,
    shutdown_scheduler,
    start_scheduler,
)
from src.tools.mcp_server import (
    ALL_STORE_ALLOWED_TOOLS,
    create_analytics_mcp_server,
    create_billing_mcp_server,
    create_documents_mcp_server,
    create_inventory_mcp_server,
    create_khata_mcp_server,
    create_preferences_mcp_server,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )


def run_migrations(database_url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    os.environ["DATABASE_URL"] = database_url
    command.upgrade(config, "head")
    configure_logging()
    logger.info("Alembic migrations applied")


def build_handler(
    settings: Settings,
) -> tuple[
    Bot,
    UpdateHandler,
    AsyncIOScheduler,
    async_sessionmaker[AsyncSession],
    MessageSender,
]:
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    bot = Bot(token=settings.telegram_bot_token)
    message_sender = TelegramMessageSender(bot)
    scheduler = create_scheduler()
    voice_downloader = TelegramVoiceDownloader(bot)
    photo_downloader = TelegramPhotoDownloader(bot)
    transcriber = WhisperTranscriber(
        api_key=settings.whisper_api_key,
        api_base_url=settings.whisper_api_base_url,
        model=settings.whisper_model,
    )

    async def on_schedule_changed() -> None:
        await refresh_scheduled_jobs(scheduler, session_factory, message_sender)

    inventory_server = create_inventory_mcp_server(session_factory)
    billing_server = create_billing_mcp_server(session_factory)
    khata_server = create_khata_mcp_server(session_factory)
    analytics_server = create_analytics_mcp_server(session_factory)
    documents_server = create_documents_mcp_server(session_factory, message_sender)
    preferences_server = create_preferences_mcp_server(
        session_factory,
        on_schedule_changed=on_schedule_changed,
    )
    agent = ClaudeAgentHarness(
        model_id=settings.claude_model_id,
        anthropic_api_key=settings.anthropic_api_key,
        session_factory=session_factory,
        mcp_servers={
            "inventory": inventory_server,
            "billing": billing_server,
            "khata": khata_server,
            "analytics": analytics_server,
            "documents": documents_server,
            "preferences": preferences_server,
        },
        allowed_tools=ALL_STORE_ALLOWED_TOOLS,
    )
    handler = UpdateHandler(
        session_factory=session_factory,
        agent=agent,
        message_sender=message_sender,
        voice_downloader=voice_downloader,
        transcriber=transcriber,
        photo_downloader=photo_downloader,
    )
    return bot, handler, scheduler, session_factory, message_sender


async def run_bot(settings: Settings) -> None:
    bot, handler, scheduler, session_factory, message_sender = build_handler(settings)
    dispatcher = Dispatcher()

    @dispatcher.message()
    async def on_message(message: Message, event_update: Update) -> None:
        try:
            result = await handler.handle(event_update)
            if result.replied:
                logger.info(
                    "Replied to update_id=%s chat_id=%s",
                    event_update.update_id,
                    message.chat.id,
                )
            elif result.processed:
                logger.info(
                    "Processed update_id=%s without reply",
                    event_update.update_id,
                )
            else:
                logger.info(
                    "Skipped update_id=%s (duplicate or non-text)",
                    event_update.update_id,
                )
        except Exception:
            logger.exception(
                "Failed to handle update_id=%s chat_id=%s",
                event_update.update_id,
                message.chat.id,
            )

    await refresh_scheduled_jobs(scheduler, session_factory, message_sender)
    start_scheduler(scheduler)

    await bot.delete_webhook(drop_pending_updates=False)
    logger.info(
        "Starting Telegram long-polling (model=%s)",
        settings.claude_model_id,
    )
    try:
        await dispatcher.start_polling(bot)
    finally:
        shutdown_scheduler(scheduler)


def main() -> None:
    settings = load_settings()
    os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    run_migrations(settings.database_url)
    try:
        asyncio.run(run_bot(settings))
    except KeyboardInterrupt:
        logger.info("Bot stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
