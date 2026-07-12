"""Serialized CPU-bound document generation (ADR-0014)."""

import asyncio
from collections.abc import Callable

_DOC_GEN_LOCK = asyncio.Lock()


async def run_cpu_bound[T](function: Callable[..., T], *args: object) -> T:
    """Run sync CPU work off the event loop, serialized with other doc renders."""
    async with _DOC_GEN_LOCK:
        return await asyncio.to_thread(function, *args)
