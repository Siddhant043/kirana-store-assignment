"""Barcode scan (pyzbar) + exact Product lookup tests."""

from io import BytesIO
from unittest.mock import patch

import pytest
from barcode import Code128
from barcode.writer import ImageWriter
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.barcode import (
    decode_barcode_from_image,
    scan_barcode_image,
    serialize_scan_barcode_result,
)
from src.domain.inventory import InventoryService

AMUL_BARCODE = "8901262010016"


def _render_code128_png(payload: str) -> bytes:
    buffer = BytesIO()
    Code128(payload, writer=ImageWriter()).write(buffer)
    return buffer.getvalue()


def _zbar_available() -> bool:
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode

        image = Image.open(BytesIO(_render_code128_png("TEST123")))
        pyzbar_decode(image)
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_scan_barcode_image_missing_photo_refuses(
    inventory_session: AsyncSession,
) -> None:
    service = InventoryService(inventory_session)
    result = await scan_barcode_image(service, None)
    assert result.status == "refused"
    assert result.reason == "photo_missing"


@pytest.mark.asyncio
async def test_scan_barcode_image_garbage_undecodable(
    inventory_session: AsyncSession,
) -> None:
    service = InventoryService(inventory_session)
    # Minimal invalid JPEG-ish bytes — not a barcode.
    result = await scan_barcode_image(service, b"not-an-image")
    assert result.status == "refused"
    assert result.reason == "barcode_undecodable"


@pytest.mark.asyncio
async def test_scan_barcode_resolves_seeded_product_via_decode(
    inventory_session: AsyncSession,
) -> None:
    service = InventoryService(inventory_session)
    with patch(
        "src.domain.barcode.decode_barcode_from_image",
        return_value=AMUL_BARCODE,
    ):
        result = await scan_barcode_image(service, b"fake-image-bytes")

    assert result.status == "ok"
    assert result.confirmation_required is False
    assert result.barcode == AMUL_BARCODE
    assert result.name == "Amul Butter 100g"
    payload = serialize_scan_barcode_result(result)
    assert payload["confirmation_required"] is False
    assert payload["product_id"] == result.product_id


@pytest.mark.asyncio
async def test_scan_barcode_unknown_code_refuses(
    inventory_session: AsyncSession,
) -> None:
    service = InventoryService(inventory_session)
    with patch(
        "src.domain.barcode.decode_barcode_from_image",
        return_value="0000000000000",
    ):
        result = await scan_barcode_image(service, b"fake-image-bytes")

    assert result.status == "refused"
    assert result.reason == "barcode_not_found"
    assert result.details == {"barcode": "0000000000000"}


@pytest.mark.skipif(not _zbar_available(), reason="libzbar not installed locally")
def test_decode_barcode_from_synthesized_code128_image() -> None:
    png = _render_code128_png(AMUL_BARCODE)
    assert decode_barcode_from_image(png) == AMUL_BARCODE


@pytest.mark.asyncio
@pytest.mark.skipif(not _zbar_available(), reason="libzbar not installed locally")
async def test_scan_barcode_end_to_end_from_synthesized_image(
    inventory_session: AsyncSession,
) -> None:
    service = InventoryService(inventory_session)
    png = _render_code128_png(AMUL_BARCODE)
    result = await scan_barcode_image(service, png)
    assert result.status == "ok"
    assert result.name == "Amul Butter 100g"
    assert result.confirmation_required is False
