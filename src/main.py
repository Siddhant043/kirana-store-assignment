"""Composition root: migrations, bot startup, long-polling."""

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.types import Message, Update
from alembic.config import Config

from alembic import command
from src.agent.harness import ClaudeAgentHarness
from src.bot.handler import TelegramMessageSender, UpdateHandler
from src.config import Settings, load_settings
from src.db.session import create_engine, create_session_factory
from src.tools.mcp_server import (
    ALL_STORE_ALLOWED_TOOLS,
    create_billing_mcp_server,
    create_inventory_mcp_server,
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


def build_handler(settings: Settings) -> tuple[Bot, UpdateHandler]:
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    bot = Bot(token=settings.telegram_bot_token)
    inventory_server = create_inventory_mcp_server(session_factory)
    billing_server = create_billing_mcp_server(session_factory)
    agent = ClaudeAgentHarness(
        model_id=settings.claude_model_id,
        anthropic_api_key=settings.anthropic_api_key,
        mcp_servers={
            "inventory": inventory_server,
            "billing": billing_server,
        },
        allowed_tools=ALL_STORE_ALLOWED_TOOLS,
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

    await bot.delete_webhook(drop_pending_updates=False)
    logger.info(
        "Starting Telegram long-polling (model=%s)",
        settings.claude_model_id,
    )
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
