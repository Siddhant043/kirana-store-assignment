"""Table-driven GST pricing tests."""

from decimal import Decimal

import pytest

from src.domain.pricing import (
    BillTotals,
    LinePricing,
    UnitTaxBreakup,
    compute_bill_totals,
    compute_line_pricing,
    compute_unit_tax,
)


@pytest.mark.parametrize(
    ("mrp_paise", "gst_slab", "expected"),
    [
        (4500, 0, UnitTaxBreakup(4500, 0, 0, 0)),
        (10000, 5, UnitTaxBreakup(9524, 238, 238, 476)),
        (1400, 12, UnitTaxBreakup(1250, 75, 75, 150)),
        (999, 18, UnitTaxBreakup(847, 76, 76, 152)),
    ],
)
def test_compute_unit_tax_across_slabs(
    mrp_paise: int,
    gst_slab: int,
    expected: UnitTaxBreakup,
) -> None:
    result = compute_unit_tax(mrp_paise, gst_slab)
    assert result == expected


def test_compute_line_pricing_packaged_maggi() -> None:
    result = compute_line_pricing(1400, Decimal("4"), 12, "packaged")
    assert result == LinePricing(
        line_total_paise=5600,
        taxable_paise=5000,
        cgst_paise=300,
        sgst_paise=300,
        gst_paise=600,
    )


def test_compute_line_pricing_loose_sugar_zero_percent() -> None:
    result = compute_line_pricing(4500, Decimal("2.5"), 0, "loose")
    assert result == LinePricing(
        line_total_paise=11250,
        taxable_paise=11250,
        cgst_paise=0,
        sgst_paise=0,
        gst_paise=0,
    )


def test_compute_bill_totals_applies_round_off_to_nearest_rupee() -> None:
    lines = [
        LinePricing(3333, 3000, 166, 167, 333),
        LinePricing(3334, 3000, 167, 167, 334),
    ]
    totals = compute_bill_totals(lines)
    assert totals == BillTotals(
        subtotal_paise=6667,
        taxable_paise=6000,
        cgst_paise=333,
        sgst_paise=334,
        round_off_paise=33,
        total_paise=6700,
    )
