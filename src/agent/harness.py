"""Claude Agent SDK harness for owner messages."""

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

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INVENTORY_SKILL_PATH = PROJECT_ROOT / "docs" / "agents" / "inventory.md"

BASE_SYSTEM_PROMPT = (
    "You are a helpful assistant for an Indian kirana (grocery) store owner. "
    "The owner messages you from Telegram in plain language. "
    "Reply concisely and helpfully using the inventory tools when relevant."
)


def load_inventory_skill_prompt() -> str:
    skill_text = INVENTORY_SKILL_PATH.read_text(encoding="utf-8")
    return f"{BASE_SYSTEM_PROMPT}\n\n{skill_text}"


class AgentHarness(Protocol):
    async def reply(self, chat_id: int, owner_message: str) -> str: ...


class ClaudeAgentHarness:
    def __init__(
        self,
        model_id: str,
        anthropic_api_key: str,
        *,
        mcp_servers: dict[str, Any] | None = None,
        allowed_tools: list[str] | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._model_id = model_id
        self._anthropic_api_key = anthropic_api_key
        self._mcp_servers = mcp_servers or {}
        self._allowed_tools = allowed_tools or []
        self._system_prompt = system_prompt or load_inventory_skill_prompt()
        self._session_ids: dict[int, str] = {}

    async def reply(self, chat_id: int, owner_message: str) -> str:
        options = ClaudeAgentOptions(
            model=self._model_id,
            system_prompt=self._system_prompt,
            mcp_servers=self._mcp_servers,
            allowed_tools=self._allowed_tools,
            env={"ANTHROPIC_API_KEY": self._anthropic_api_key},
        )
        session_id = self._session_ids.get(chat_id)
        if session_id is not None:
            options.resume = session_id

        reply_text = ""
        async for message in self._stream_messages(owner_message, options):
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

    async def _stream_messages(
        self,
        owner_message: str,
        options: ClaudeAgentOptions,
    ) -> AsyncIterator[object]:
        async for message in query(prompt=owner_message, options=options):
            yield message


def _text_from_assistant(message: AssistantMessage) -> str:
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            parts.append(block.text)
    return "\n".join(parts)
