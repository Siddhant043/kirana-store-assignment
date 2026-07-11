"""Inventory tables, pg_trgm, and seed Products with Aliases."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "002_inventory_grounding"
down_revision: str | Sequence[str] | None = "001_baseline_processed_updates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_PRODUCTS: list[dict[str, object]] = [
    {
        "name": "Maggi Noodles 70g",
        "brand": "Nestle",
        "mrp_paise": 1400,
        "cost_price_paise": 1200,
        "gst_slab": 12,
        "hsn_code": "19023010",
        "unit_type": "packaged",
        "quantity": 0,
        "reorder_level": 20,
        "aliases": ["maggi"],
    },
    {
        "name": "Amul Butter 100g",
        "brand": "Amul",
        "mrp_paise": 6200,
        "cost_price_paise": 5400,
        "gst_slab": 12,
        "hsn_code": "04051000",
        "unit_type": "packaged",
        "quantity": 10,
        "reorder_level": 5,
        "aliases": ["butter", "amul butter"],
    },
    {
        "name": "Aashirvaad Atta 5kg",
        "brand": "Aashirvaad",
        "mrp_paise": 28500,
        "cost_price_paise": 25000,
        "gst_slab": 5,
        "hsn_code": "11010010",
        "unit_type": "packaged",
        "quantity": 8,
        "reorder_level": 3,
        "aliases": ["atta", "aashirvaad atta"],
    },
    {
        "name": "Loose Atta",
        "brand": None,
        "mrp_paise": 4500,
        "cost_price_paise": 4000,
        "gst_slab": 0,
        "hsn_code": "11010010",
        "unit_type": "loose",
        "quantity": 25.5,
        "reorder_level": 10,
        "aliases": ["atta", "loose atta"],
    },
    {
        "name": "Sugar",
        "brand": None,
        "mrp_paise": 4500,
        "cost_price_paise": 4000,
        "gst_slab": 0,
        "hsn_code": "17019910",
        "unit_type": "loose",
        "quantity": 15,
        "reorder_level": 5,
        "aliases": ["chini", "sugar"],
    },
    {
        "name": "Tata Salt 1kg",
        "brand": "Tata",
        "mrp_paise": 2800,
        "cost_price_paise": 2200,
        "gst_slab": 5,
        "hsn_code": "25010010",
        "unit_type": "packaged",
        "quantity": 12,
        "reorder_level": 4,
        "aliases": ["namak", "salt"],
    },
    {
        "name": "Fortune Sunflower Oil 1L",
        "brand": "Fortune",
        "mrp_paise": 16500,
        "cost_price_paise": 14500,
        "gst_slab": 5,
        "hsn_code": "15121100",
        "unit_type": "packaged",
        "quantity": 6,
        "reorder_level": 2,
        "aliases": ["oil", "sunflower oil"],
    },
    {
        "name": "Parle-G Biscuits",
        "brand": "Parle",
        "mrp_paise": 1000,
        "cost_price_paise": 800,
        "gst_slab": 12,
        "hsn_code": "19053100",
        "unit_type": "packaged",
        "quantity": 30,
        "reorder_level": 10,
        "aliases": ["parle-g", "biscuits"],
    },
    {
        "name": "Surf Excel 1kg",
        "brand": "Surf Excel",
        "mrp_paise": 22000,
        "cost_price_paise": 19000,
        "gst_slab": 18,
        "hsn_code": "34022010",
        "unit_type": "packaged",
        "quantity": 4,
        "reorder_level": 2,
        "aliases": ["surf", "detergent"],
    },
    {
        "name": "Rice",
        "brand": None,
        "mrp_paise": 6000,
        "cost_price_paise": 5200,
        "gst_slab": 0,
        "hsn_code": "10063010",
        "unit_type": "loose",
        "quantity": 20,
        "reorder_level": 8,
        "aliases": ["chawal", "rice"],
    },
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "products",
        sa.Column("product_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("mrp_paise", sa.Integer(), nullable=False),
        sa.Column("cost_price_paise", sa.Integer(), nullable=False),
        sa.Column("gst_slab", sa.Integer(), nullable=False),
        sa.Column("hsn_code", sa.String(length=16), nullable=False),
        sa.Column("unit_type", sa.String(length=16), nullable=False),
        sa.Column(
            "quantity",
            sa.Numeric(precision=12, scale=3),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "reorder_level",
            sa.Numeric(precision=12, scale=3),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "gst_slab IN (0, 5, 12, 18)",
            name="ck_products_gst_slab",
        ),
        sa.CheckConstraint(
            "unit_type IN ('packaged', 'loose')",
            name="ck_products_unit_type",
        ),
        sa.PrimaryKeyConstraint("product_id"),
    )

    op.create_table(
        "aliases",
        sa.Column("alias_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.product_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("alias_id"),
    )

    op.create_table(
        "stock_ledger",
        sa.Column("ledger_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("delta", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("ref_id", sa.BigInteger(), nullable=True),
        sa.Column("balance_after", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason IN ('stock_in', 'sale', 'adjustment')",
            name="ck_stock_ledger_reason",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.product_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ledger_id"),
    )

    op.execute(
        "CREATE INDEX ix_products_name_trgm ON products "
        "USING gin (lower(name) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_products_brand_trgm ON products "
        "USING gin (lower(brand) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_aliases_alias_trgm ON aliases "
        "USING gin (lower(alias) gin_trgm_ops)"
    )

    products_table = sa.table(
        "products",
        sa.column("product_id", sa.BigInteger()),
        sa.column("name", sa.Text()),
        sa.column("brand", sa.Text()),
        sa.column("mrp_paise", sa.Integer()),
        sa.column("cost_price_paise", sa.Integer()),
        sa.column("gst_slab", sa.Integer()),
        sa.column("hsn_code", sa.String()),
        sa.column("unit_type", sa.String()),
        sa.column("quantity", sa.Numeric()),
        sa.column("reorder_level", sa.Numeric()),
    )
    aliases_table = sa.table(
        "aliases",
        sa.column("product_id", sa.BigInteger()),
        sa.column("alias", sa.Text()),
    )

    connection = op.get_bind()
    for seed_row in SEED_PRODUCTS:
        alias_values = seed_row["aliases"]
        product_values = {
            key: value for key, value in seed_row.items() if key != "aliases"
        }
        result = connection.execute(
            products_table.insert()
            .values(**product_values)
            .returning(products_table.c.product_id)
        )
        product_id = result.scalar_one()
        for alias in alias_values:
            connection.execute(
                aliases_table.insert().values(
                    product_id=product_id,
                    alias=alias,
                )
            )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_aliases_alias_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_brand_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_name_trgm")
    op.drop_table("stock_ledger")
    op.drop_table("aliases")
    op.drop_table("products")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
