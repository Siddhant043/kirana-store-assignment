"""FEFO stock_batches table and backfill from products.quantity."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "011_fefo_batch_tracking"
down_revision: str | Sequence[str] | None = "010_scheduled_weekly_deck"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_batches",
        sa.Column("batch_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("batch_qty", sa.Numeric(12, 3), nullable=False),
        sa.Column("cost_price_paise", sa.Integer(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("batch_qty >= 0", name="ck_stock_batches_batch_qty"),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.product_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("batch_id"),
    )
    op.create_index(
        "ix_stock_batches_product_expiry",
        "stock_batches",
        ["product_id", "expiry_date"],
    )
    op.execute(
        """
        INSERT INTO stock_batches (
            product_id, batch_qty, cost_price_paise, expiry_date, received_at
        )
        SELECT
            product_id,
            quantity,
            cost_price_paise,
            NULL,
            now()
        FROM products
        WHERE quantity > 0
        """
    )


def downgrade() -> None:
    op.drop_index("ix_stock_batches_product_expiry", table_name="stock_batches")
    op.drop_table("stock_batches")
