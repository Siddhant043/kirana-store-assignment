"""Add nullable unique Product.barcode and seed packaged SKU barcodes."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "013_product_barcode"
down_revision: str | Sequence[str] | None = "012_multilingual_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Packaged seed SKUs only — loose items stay NULL.
PACKAGED_BARCODES: list[tuple[str, str]] = [
    ("Maggi Noodles 70g", "8901058000151"),
    ("Amul Butter 100g", "8901262010016"),
    ("Aashirvaad Atta 5kg", "8901725001234"),
    ("Tata Salt 1kg", "8901042956123"),
    ("Fortune Sunflower Oil 1L", "8901030865123"),
    ("Parle-G Biscuits", "8901030865999"),
    ("Surf Excel 1kg", "8901030654321"),
]


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("barcode", sa.String(length=32), nullable=True),
    )
    op.create_index("ix_products_barcode", "products", ["barcode"], unique=True)

    connection = op.get_bind()
    for product_name, barcode in PACKAGED_BARCODES:
        connection.execute(
            sa.text(
                "UPDATE products SET barcode = :barcode WHERE name = :name"
            ),
            {"barcode": barcode, "name": product_name},
        )


def downgrade() -> None:
    op.drop_index("ix_products_barcode", table_name="products")
    op.drop_column("products", "barcode")
