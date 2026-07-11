"""Claude Agent SDK harness for owner messages."""

from collections.abc import AsyncIterator
from typing import Protocol

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

SYSTEM_PROMPT = (
    "You are a helpful assistant for an Indian kirana (grocery) store owner. "
    "The owner messages you from Telegram in plain language. "
    "Reply concisely and helpfully. Domain tools are not available yet."
)


class AgentHarness(Protocol):
    async def reply(self, chat_id: int, owner_message: str) -> str: ...


class ClaudeAgentHarness:
    def __init__(self, model_id: str, anthropic_api_key: str) -> None:
        self._model_id = model_id
        self._anthropic_api_key = anthropic_api_key
        self._session_ids: dict[int, str] = {}

    async def reply(self, chat_id: int, owner_message: str) -> str:
        options = ClaudeAgentOptions(
            model=self._model_id,
            system_prompt=SYSTEM_PROMPT,
            allowed_tools=[],
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
