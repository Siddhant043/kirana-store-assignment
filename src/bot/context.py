"""Per-request Telegram chat context for billing tools."""

from contextvars import ContextVar

current_chat_id: ContextVar[int | None] = ContextVar("current_chat_id", default=None)


def require_chat_id() -> int:
    chat_id = current_chat_id.get()
    if chat_id is None:
        msg = "chat_id is not set in request context"
        raise RuntimeError(msg)
    return chat_id
