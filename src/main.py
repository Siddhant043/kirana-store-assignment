"""Composition root: migrations, bot startup, long-polling."""

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from alembic.config import Config

from alembic import command
from src.agent.harness import ClaudeAgentHarness
from src.bot.handler import TelegramMessageSender, UpdateHandler
from src.config import Settings, load_settings
from src.db.session import create_engine, create_session_factory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migrations(database_url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    os.environ["DATABASE_URL"] = database_url
    command.upgrade(config, "head")
    logger.info("Alembic migrations applied")


def build_handler(settings: Settings) -> tuple[Bot, UpdateHandler]:
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    bot = Bot(token=settings.telegram_bot_token)
    agent = ClaudeAgentHarness(
        model_id=settings.claude_model_id,
        anthropic_api_key=settings.anthropic_api_key,
    )
    handler = UpdateHandler(
        session_factory=session_factory,
        agent=agent,
        message_sender=TelegramMessageSender(bot),
    )
    return bot, handler


async def run_bot(settings: Settings) -> None:
    bot, handler = build_handler(settings)
    dispatcher = Dispatcher()

    @dispatcher.update()
    async def on_update(update: object) -> None:
        from aiogram.types import Update as TelegramUpdate

        if isinstance(update, TelegramUpdate):
            await handler.handle(update)

    logger.info("Starting Telegram long-polling")
    await dispatcher.start_polling(bot)


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
