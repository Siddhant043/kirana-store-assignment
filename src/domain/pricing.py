"""GST pricing: MRP tax-inclusive, integer paise, CGST/SGST split."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

PAISE_PER_RUPEE = 100


@dataclass(frozen=True)
class UnitTaxBreakup:
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    gst_paise: int


@dataclass(frozen=True)
class LinePricing:
    line_total_paise: int
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    gst_paise: int


@dataclass(frozen=True)
class BillTotals:
    subtotal_paise: int
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    round_off_paise: int
    total_paise: int


def round_half_up_paise(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_unit_tax(mrp_paise: int, gst_slab_percent: int) -> UnitTaxBreakup:
    if gst_slab_percent == 0:
        return UnitTaxBreakup(
            taxable_paise=mrp_paise,
            cgst_paise=0,
            sgst_paise=0,
            gst_paise=0,
        )

    slab_multiplier = Decimal(1) + (Decimal(gst_slab_percent) / Decimal(100))
    taxable_paise = round_half_up_paise(Decimal(mrp_paise) / slab_multiplier)
    gst_paise = mrp_paise - taxable_paise
    cgst_paise = round_half_up_paise(Decimal(gst_paise) / Decimal(2))
    sgst_paise = gst_paise - cgst_paise
    return UnitTaxBreakup(
        taxable_paise=taxable_paise,
        cgst_paise=cgst_paise,
        sgst_paise=sgst_paise,
        gst_paise=gst_paise,
    )


def compute_line_total_paise(
    mrp_paise: int,
    quantity: Decimal,
    unit_type: str,
) -> int:
    if unit_type == "packaged":
        return mrp_paise * int(quantity)
    return round_half_up_paise(Decimal(mrp_paise) * quantity)


def compute_line_pricing(
    mrp_paise: int,
    quantity: Decimal,
    gst_slab_percent: int,
    unit_type: str,
) -> LinePricing:
    unit_tax = compute_unit_tax(mrp_paise, gst_slab_percent)
    line_total_paise = compute_line_total_paise(mrp_paise, quantity, unit_type)

    if unit_type == "packaged":
        packaged_quantity = int(quantity)
        taxable_paise = unit_tax.taxable_paise * packaged_quantity
        cgst_paise = unit_tax.cgst_paise * packaged_quantity
        sgst_paise = unit_tax.sgst_paise * packaged_quantity
        gst_paise = unit_tax.gst_paise * packaged_quantity
    else:
        taxable_paise = round_half_up_paise(Decimal(unit_tax.taxable_paise) * quantity)
        gst_paise = round_half_up_paise(Decimal(unit_tax.gst_paise) * quantity)
        cgst_paise = round_half_up_paise(Decimal(gst_paise) / Decimal(2))
        sgst_paise = gst_paise - cgst_paise
        line_total_paise = taxable_paise + gst_paise

    return LinePricing(
        line_total_paise=line_total_paise,
        taxable_paise=taxable_paise,
        cgst_paise=cgst_paise,
        sgst_paise=sgst_paise,
        gst_paise=gst_paise,
    )


def compute_bill_totals(lines: list[LinePricing]) -> BillTotals:
    subtotal_paise = sum(line.line_total_paise for line in lines)
    taxable_paise = sum(line.taxable_paise for line in lines)
    cgst_paise = sum(line.cgst_paise for line in lines)
    sgst_paise = sum(line.sgst_paise for line in lines)

    total_before_round_off = subtotal_paise
    rounded_total = (
        round_half_up_paise(Decimal(total_before_round_off) / Decimal(PAISE_PER_RUPEE))
        * PAISE_PER_RUPEE
    )
    round_off_paise = rounded_total - total_before_round_off

    return BillTotals(
        subtotal_paise=subtotal_paise,
        taxable_paise=taxable_paise,
        cgst_paise=cgst_paise,
        sgst_paise=sgst_paise,
        round_off_paise=round_off_paise,
        total_paise=rounded_total,
    )
