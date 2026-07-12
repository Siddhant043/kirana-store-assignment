"""Per-request Telegram chat and Owner context for tools."""

from contextvars import ContextVar

current_chat_id: ContextVar[int | None] = ContextVar("current_chat_id", default=None)
current_owner_user_id: ContextVar[int | None] = ContextVar(
    "current_owner_user_id",
    default=None,
)


def require_chat_id() -> int:
    chat_id = current_chat_id.get()
    if chat_id is None:
        msg = "chat_id is not set in request context"
        raise RuntimeError(msg)
    return chat_id


def require_owner_user_id() -> int:
    owner_user_id = current_owner_user_id.get()
    if owner_user_id is None:
        msg = "owner_telegram_user_id is not set in request context"
        raise RuntimeError(msg)
    return owner_user_id
