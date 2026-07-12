"""Claude Agent SDK harness for owner messages."""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.context import (
    current_chat_id,
    current_owner_user_id,
    current_photo_bytes,
    current_photo_media_type,
)
from src.db.models import Product
from src.domain.preferences import (
    DEFAULT_PAYMENT_MODE_KEY,
    PREFERRED_PRODUCT_PREFIX,
    PreferencesService,
)
from src.domain.shop_profile import ShopProfileResult, ShopProfileService

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INVENTORY_SKILL_PATH = PROJECT_ROOT / "docs" / "agents" / "inventory.md"
BILLING_SKILL_PATH = PROJECT_ROOT / "docs" / "agents" / "billing.md"
KHATA_SKILL_PATH = PROJECT_ROOT / "docs" / "agents" / "khata.md"
ANALYTICS_SKILL_PATH = PROJECT_ROOT / "docs" / "agents" / "analytics.md"
DOCUMENTS_SKILL_PATH = PROJECT_ROOT / "docs" / "agents" / "documents.md"
PREFERENCES_SKILL_PATH = PROJECT_ROOT / "docs" / "agents" / "preferences.md"

BASE_SYSTEM_PROMPT = (
    "You are a helpful assistant for an Indian kirana (grocery) store owner. "
    "The owner messages you from Telegram in plain language. "
    "If the owner writes in Hindi, Tamil, or Hinglish, reply in the same "
    "language and style. "
    "Reply concisely and helpfully using inventory, billing, khata, analytics, "
    "documents, and preferences tools when relevant."
)


def load_base_system_prompt() -> str:
    inventory_skill = INVENTORY_SKILL_PATH.read_text(encoding="utf-8")
    billing_skill = BILLING_SKILL_PATH.read_text(encoding="utf-8")
    khata_skill = KHATA_SKILL_PATH.read_text(encoding="utf-8")
    analytics_skill = ANALYTICS_SKILL_PATH.read_text(encoding="utf-8")
    documents_skill = DOCUMENTS_SKILL_PATH.read_text(encoding="utf-8")
    preferences_skill = PREFERENCES_SKILL_PATH.read_text(encoding="utf-8")
    return (
        f"{BASE_SYSTEM_PROMPT}\n\n{inventory_skill}\n\n{billing_skill}\n\n"
        f"{khata_skill}\n\n{analytics_skill}\n\n{documents_skill}\n\n"
        f"{preferences_skill}"
    )


def load_system_prompt() -> str:
    """Backward-compatible alias for the static skills portion of the prompt."""
    return load_base_system_prompt()


async def render_standing_memory(
    session: AsyncSession,
    owner_telegram_user_id: int,
) -> str:
    """Render Preferences + Shop Profile for per-turn system-prompt injection."""
    preferences_service = PreferencesService(session)
    shop_service = ShopProfileService(session)

    listed = await preferences_service.list_preferences(owner_telegram_user_id)
    shop = await shop_service.get_shop_profile(owner_telegram_user_id)

    lines: list[str] = ["## Standing Preferences / Shop Profile"]

    default_payment: str | None = None
    preferred_products: list[str] = []
    for item in listed.preferences:
        if item.preference_key == DEFAULT_PAYMENT_MODE_KEY:
            default_payment = item.preference_value
        elif item.preference_key.startswith(PREFERRED_PRODUCT_PREFIX):
            query_label = item.preference_key[len(PREFERRED_PRODUCT_PREFIX) :]
            product_id = int(item.preference_value)
            product = await session.get(Product, product_id)
            product_name = product.name if product is not None else "unknown"
            preferred_products.append(
                f"- `{query_label}` → product_id={product_id} ({product_name})"
            )

    if default_payment is not None:
        lines.append(f"- Default Payment Mode: `{default_payment}`")
    else:
        lines.append("- Default Payment Mode: (none stored)")

    if preferred_products:
        lines.append("- Preferred Products:")
        lines.extend(preferred_products)
    else:
        lines.append("- Preferred Products: (none stored)")

    if isinstance(shop, ShopProfileResult):
        gstin = shop.gstin or "(none)"
        lines.append(f"- Shop Profile: {shop.shop_name}, GSTIN={gstin}")
        if shop.logo_url:
            lines.append(f"- Shop logo URL: {shop.logo_url}")
        if shop.accent_color:
            lines.append(f"- Shop accent color: {shop.accent_color}")
    else:
        lines.append("- Shop Profile: (not set)")

    lines.append(
        "Use these defaults when the Owner does not override them. "
        "One-Bill Payment Mode overrides do not call set_preference."
    )
    return "\n".join(lines)


class AgentHarness(Protocol):
    async def reply(
        self,
        chat_id: int,
        owner_message: str,
        *,
        owner_telegram_user_id: int | None = None,
        image_bytes: bytes | None = None,
        media_type: str = "image/jpeg",
    ) -> str: ...

    def clear_session(self, chat_id: int) -> None: ...


class ClaudeAgentHarness:
    def __init__(
        self,
        model_id: str,
        anthropic_api_key: str,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        mcp_servers: dict[str, Any] | None = None,
        allowed_tools: list[str] | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._model_id = model_id
        self._anthropic_api_key = anthropic_api_key
        self._session_factory = session_factory
        self._mcp_servers = mcp_servers or {}
        self._allowed_tools = allowed_tools or []
        self._base_system_prompt = system_prompt or load_base_system_prompt()
        self._session_ids: dict[int, str] = {}

    def clear_session(self, chat_id: int) -> None:
        self._session_ids.pop(chat_id, None)

    async def reply(
        self,
        chat_id: int,
        owner_message: str,
        *,
        owner_telegram_user_id: int | None = None,
        image_bytes: bytes | None = None,
        media_type: str = "image/jpeg",
    ) -> str:
        owner_id = (
            owner_telegram_user_id if owner_telegram_user_id is not None else chat_id
        )
        system_prompt = await self._build_system_prompt(owner_id)
        options = ClaudeAgentOptions(
            model=self._model_id,
            system_prompt=system_prompt,
            mcp_servers=self._mcp_servers,
            allowed_tools=self._allowed_tools,
            env={"ANTHROPIC_API_KEY": self._anthropic_api_key},
        )
        session_id = self._session_ids.get(chat_id)
        if session_id is not None:
            options.resume = session_id

        chat_token = current_chat_id.set(chat_id)
        owner_token = current_owner_user_id.set(owner_id)
        photo_token = current_photo_bytes.set(image_bytes)
        media_token = current_photo_media_type.set(
            media_type if image_bytes is not None else None
        )
        try:
            reply_text = ""
            async for message in self._stream_messages(
                owner_message,
                options,
                image_bytes=image_bytes,
                media_type=media_type,
            ):
                if (
                    hasattr(message, "subtype")
                    and getattr(message, "subtype", None) == "init"
                    and hasattr(message, "data")
                ):
                    data = message.data
                    if isinstance(data, dict) and "session_id" in data:
                        self._session_ids[chat_id] = str(data["session_id"])
                if isinstance(message, AssistantMessage):
                    reply_text = _text_from_assistant(message)
                if isinstance(message, ResultMessage) and message.result:
                    reply_text = message.result

            return reply_text or "I could not generate a reply."
        finally:
            current_photo_media_type.reset(media_token)
            current_photo_bytes.reset(photo_token)
            current_owner_user_id.reset(owner_token)
            current_chat_id.reset(chat_token)

    async def _build_system_prompt(self, owner_telegram_user_id: int) -> str:
        if self._session_factory is None:
            return self._base_system_prompt
        async with self._session_factory() as session:
            memory_block = await render_standing_memory(
                session,
                owner_telegram_user_id,
            )
        return f"{self._base_system_prompt}\n\n{memory_block}"

    async def _stream_messages(
        self,
        owner_message: str,
        options: ClaudeAgentOptions,
        *,
        image_bytes: bytes | None = None,
        media_type: str = "image/jpeg",
    ) -> AsyncIterator[object]:
        if image_bytes is None:
            async for message in query(prompt=owner_message, options=options):
                yield message
            return

        prompt = _multimodal_user_prompt(owner_message, image_bytes, media_type)
        async for message in query(prompt=prompt, options=options):
            yield message


def _multimodal_user_prompt(
    owner_message: str,
    image_bytes: bytes,
    media_type: str,
) -> AsyncIterator[dict[str, Any]]:
    encoded = base64.standard_b64encode(image_bytes).decode("ascii")

    async def _one_shot() -> AsyncIterator[dict[str, Any]]:
        yield {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": owner_message},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": encoded,
                        },
                    },
                ],
            },
            "parent_tool_use_id": None,
            "session_id": "default",
        }

    return _one_shot()


def _text_from_assistant(message: AssistantMessage) -> str:
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            parts.append(block.text)
    return "\n".join(parts)
