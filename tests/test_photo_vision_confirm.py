"""Photo vision confirmation gate (no live Vision API)."""

from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.harness import ClaudeAgentHarness, _multimodal_user_prompt
from src.bot.context import current_photo_bytes, current_photo_media_type
from src.db.models import DraftLine
from src.domain.billing import BillingService
from src.domain.inventory import (
    InventoryService,
    PreparePhotoProductOkResult,
    PreparePhotoProductRequiresConfirmation,
)


async def _product_id_for(session: AsyncSession, query: str) -> int:
    result = await InventoryService(session).find_product(query)
    assert result.candidates
    return result.candidates[0].product_id


@pytest.mark.asyncio
async def test_prepare_photo_product_unconfirmed_requires_confirmation(
    inventory_session: AsyncSession,
) -> None:
    product_id = await _product_id_for(inventory_session, "amul butter")
    service = InventoryService(inventory_session)

    result = await service.prepare_photo_product(product_id, confirm=False)

    assert isinstance(result, PreparePhotoProductRequiresConfirmation)
    assert result.status == "requires_confirmation"
    assert result.reason == "photo_vision_confirm"
    assert result.product_id == product_id
    assert "Amul" in result.name


@pytest.mark.asyncio
async def test_prepare_photo_product_confirm_then_add_line(
    inventory_session: AsyncSession,
) -> None:
    """Vision guess string → find_product → confirm → add_line succeeds."""
    guess = "Amul Butter"
    found = await InventoryService(inventory_session).find_product(guess)
    assert found.status == "ok"
    product_id = found.candidates[0].product_id

    inventory = InventoryService(inventory_session)
    gated = await inventory.prepare_photo_product(product_id, confirm=False)
    assert gated.status == "requires_confirmation"

    confirmed = await inventory.prepare_photo_product(product_id, confirm=True)
    assert isinstance(confirmed, PreparePhotoProductOkResult)
    assert confirmed.confirmed is True
    assert confirmed.product_id == product_id

    billing = BillingService(inventory_session, chat_id=9201)
    await billing.open_draft_bill()
    added = await billing.add_line(confirmed.product_id, Decimal("1"))
    assert added.status == "ok"

    lines = (
        await inventory_session.execute(
            select(DraftLine).where(DraftLine.product_id == product_id)
        )
    ).scalars().all()
    assert len(lines) == 1


@pytest.mark.asyncio
async def test_prepare_photo_product_reject_leaves_draft_empty(
    inventory_session: AsyncSession,
) -> None:
    product_id = await _product_id_for(inventory_session, "amul butter")
    inventory = InventoryService(inventory_session)
    billing = BillingService(inventory_session, chat_id=9202)
    opened = await billing.open_draft_bill()

    # Owner rejects: never confirm=true, never add_line.
    gated = await inventory.prepare_photo_product(product_id, confirm=False)
    assert gated.status == "requires_confirmation"

    lines = (
        await inventory_session.execute(
            select(DraftLine).where(DraftLine.draft_bill_id == opened.draft_bill_id)
        )
    ).scalars().all()
    assert lines == []


@pytest.mark.asyncio
async def test_prepare_photo_product_unknown_product_refuses(
    inventory_session: AsyncSession,
) -> None:
    service = InventoryService(inventory_session)
    result = await service.prepare_photo_product(999_999_999, confirm=False)
    assert result.status == "refused"
    assert result.reason == "product_not_found"


@pytest.mark.asyncio
async def test_harness_reply_with_image_uses_streaming_prompt_and_photo_context() -> (
    None
):
    harness = ClaudeAgentHarness(
        model_id="test-model",
        anthropic_api_key="test-key",
        system_prompt="test",
    )
    captured: dict[str, object] = {}

    async def fake_stream(
        owner_message: str,
        options: object,
        *,
        image_bytes: bytes | None = None,
        media_type: str = "image/jpeg",
    ):
        captured["owner_message"] = owner_message
        captured["image_bytes"] = image_bytes
        captured["media_type"] = media_type
        captured["photo_ctx"] = current_photo_bytes.get()
        captured["media_ctx"] = current_photo_media_type.get()
        if False:  # pragma: no cover — make this an async generator
            yield None

    with patch.object(harness, "_stream_messages", side_effect=fake_stream):
        reply = await harness.reply(
            chat_id=42,
            owner_message="Identify this",
            owner_telegram_user_id=42,
            image_bytes=b"jpeg-bytes",
            media_type="image/jpeg",
        )

    assert reply == "I could not generate a reply."
    assert captured["image_bytes"] == b"jpeg-bytes"
    assert captured["media_type"] == "image/jpeg"
    assert captured["photo_ctx"] == b"jpeg-bytes"
    assert captured["media_ctx"] == "image/jpeg"
    assert current_photo_bytes.get() is None


@pytest.mark.asyncio
async def test_multimodal_user_prompt_shape() -> None:
    chunks: list[dict[str, Any]] = []
    async for chunk in _multimodal_user_prompt(
        "what is this?",
        b"abc",
        "image/jpeg",
    ):
        chunks.append(chunk)

    assert len(chunks) == 1
    message = chunks[0]["message"]
    assert isinstance(message, dict)
    content = message["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "what is this?"}
    image_block = content[1]
    assert isinstance(image_block, dict)
    assert image_block["type"] == "image"
    source = image_block["source"]
    assert isinstance(source, dict)
    assert source["type"] == "base64"
    assert source["media_type"] == "image/jpeg"
    assert source["data"]  # base64 of b"abc"
