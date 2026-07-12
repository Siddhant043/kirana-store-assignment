"""Billing tables for Draft Bills, Bills, and invoice numbering."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003_billing_core"
down_revision: str | Sequence[str] | None = "002_inventory_grounding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "draft_bills",
        sa.Column("draft_bill_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('open', 'finalized')",
            name="ck_draft_bills_status",
        ),
        sa.PrimaryKeyConstraint("draft_bill_id"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_draft_bills_one_open_per_chat "
        "ON draft_bills (chat_id) WHERE status = 'open'"
    )

    op.create_table(
        "draft_lines",
        sa.Column("draft_line_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("draft_bill_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.ForeignKeyConstraint(
            ["draft_bill_id"],
            ["draft_bills.draft_bill_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.product_id"],
        ),
        sa.PrimaryKeyConstraint("draft_line_id"),
        sa.UniqueConstraint(
            "draft_bill_id",
            "product_id",
            name="uq_draft_lines_draft_product",
        ),
    )

    op.create_table(
        "bills",
        sa.Column("bill_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("draft_bill_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("invoice_number", sa.String(length=32), nullable=False),
        sa.Column("payment_mode", sa.String(length=16), nullable=False),
        sa.Column("subtotal_paise", sa.Integer(), nullable=False),
        sa.Column("cgst_paise", sa.Integer(), nullable=False),
        sa.Column("sgst_paise", sa.Integer(), nullable=False),
        sa.Column("round_off_paise", sa.Integer(), nullable=False),
        sa.Column("total_paise", sa.Integer(), nullable=False),
        sa.Column(
            "finalized_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "payment_mode IN ('cash', 'upi', 'card', 'khata')",
            name="ck_bills_payment_mode",
        ),
        sa.ForeignKeyConstraint(
            ["draft_bill_id"],
            ["draft_bills.draft_bill_id"],
        ),
        sa.PrimaryKeyConstraint("bill_id"),
        sa.UniqueConstraint("draft_bill_id"),
        sa.UniqueConstraint("invoice_number"),
    )

    op.add_column(
        "draft_bills",
        sa.Column("bill_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_draft_bills_bill_id",
        "draft_bills",
        "bills",
        ["bill_id"],
        ["bill_id"],
    )

    op.create_table(
        "bill_lines",
        sa.Column("bill_line_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bill_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("mrp_paise", sa.Integer(), nullable=False),
        sa.Column("cost_price_paise", sa.Integer(), nullable=False),
        sa.Column("gst_slab", sa.Integer(), nullable=False),
        sa.Column("hsn_code", sa.String(length=16), nullable=False),
        sa.Column("line_total_paise", sa.Integer(), nullable=False),
        sa.Column("taxable_paise", sa.Integer(), nullable=False),
        sa.Column("cgst_paise", sa.Integer(), nullable=False),
        sa.Column("sgst_paise", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["bill_id"],
            ["bills.bill_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.product_id"],
        ),
        sa.PrimaryKeyConstraint("bill_line_id"),
    )

    op.create_table(
        "invoice_counters",
        sa.Column("counter_date", sa.Date(), nullable=False),
        sa.Column("last_seq", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("counter_date"),
    )


def downgrade() -> None:
    op.drop_table("invoice_counters")
    op.drop_table("bill_lines")
    op.drop_constraint("fk_draft_bills_bill_id", "draft_bills", type_="foreignkey")
    op.drop_column("draft_bills", "bill_id")
    op.drop_table("bills")
    op.drop_table("draft_lines")
    op.execute("DROP INDEX IF EXISTS uq_draft_bills_one_open_per_chat")
    op.drop_table("draft_bills")
