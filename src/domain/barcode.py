"""Barcode decode helpers (pyzbar) for photo identification."""

from dataclasses import dataclass
from io import BytesIO
from typing import Literal

from PIL import Image

from src.domain.inventory import FindProductResult, InventoryService, ProductCandidate


@dataclass(frozen=True)
class ScanBarcodeOkResult:
    status: Literal["ok"]
    barcode: str
    product_id: int
    name: str
    brand: str | None
    mrp_paise: int
    confirmation_required: Literal[False]
    candidates: list[ProductCandidate]


@dataclass(frozen=True)
class ScanBarcodeRefusedResult:
    status: Literal["refused"]
    reason: Literal["barcode_undecodable", "barcode_not_found", "photo_missing"]
    details: dict[str, object]


def decode_barcode_from_image(image_bytes: bytes) -> str | None:
    """Return the first decoded barcode payload, or None if undecodable."""
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
    except ImportError:
        return None

    try:
        image = Image.open(BytesIO(image_bytes))
    except OSError:
        return None
    decoded = pyzbar_decode(image)
    if not decoded:
        return None
    raw = decoded[0].data
    try:
        return raw.decode("utf-8").strip() or None
    except UnicodeDecodeError:
        return None


async def scan_barcode_image(
    service: InventoryService,
    image_bytes: bytes | None,
) -> ScanBarcodeOkResult | ScanBarcodeRefusedResult:
    if image_bytes is None or not image_bytes:
        return ScanBarcodeRefusedResult(
            status="refused",
            reason="photo_missing",
            details={},
        )

    barcode = decode_barcode_from_image(image_bytes)
    if barcode is None:
        return ScanBarcodeRefusedResult(
            status="refused",
            reason="barcode_undecodable",
            details={},
        )

    lookup = await service.find_product_by_barcode(barcode)
    if lookup.status != "ok" or not lookup.candidates:
        return ScanBarcodeRefusedResult(
            status="refused",
            reason="barcode_not_found",
            details={"barcode": barcode},
        )

    candidate = lookup.candidates[0]
    return ScanBarcodeOkResult(
        status="ok",
        barcode=barcode,
        product_id=candidate.product_id,
        name=candidate.name,
        brand=candidate.brand,
        mrp_paise=candidate.mrp_paise,
        confirmation_required=False,
        candidates=list(lookup.candidates),
    )


def serialize_scan_barcode_result(
    result: ScanBarcodeOkResult | ScanBarcodeRefusedResult | FindProductResult,
) -> dict[str, object]:
    if isinstance(result, ScanBarcodeOkResult):
        return {
            "status": result.status,
            "barcode": result.barcode,
            "product_id": result.product_id,
            "name": result.name,
            "brand": result.brand,
            "mrp_paise": result.mrp_paise,
            "confirmation_required": False,
            "candidates": [
                {
                    "product_id": c.product_id,
                    "name": c.name,
                    "brand": c.brand,
                    "mrp_paise": c.mrp_paise,
                    "cost_price_paise": c.cost_price_paise,
                    "gst_slab": c.gst_slab,
                    "hsn_code": c.hsn_code,
                    "unit_type": c.unit_type,
                    "quantity": c.quantity,
                    "reorder_level": c.reorder_level,
                    "match_score": c.match_score,
                }
                for c in result.candidates
            ],
        }
    if isinstance(result, ScanBarcodeRefusedResult):
        return {
            "status": result.status,
            "reason": result.reason,
            "details": result.details,
        }
    return {
        "status": result.status,
        "ambiguous": result.ambiguous,
        "candidates": [],
    }
