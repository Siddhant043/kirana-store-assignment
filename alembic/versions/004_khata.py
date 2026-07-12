"""Khata tables for Customers and Khata Entries."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004_khata"
down_revision: str | Sequence[str] | None = "003_billing_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("customer_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("customer_id"),
    )
    op.create_index("ix_customers_name", "customers", ["name"], unique=False)

    op.create_table(
        "khata_entries",
        sa.Column(
            "khata_entry_id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("entry_type", sa.String(length=16), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("bill_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entry_type IN ('charge', 'payment')",
            name="ck_khata_entries_entry_type",
        ),
        sa.CheckConstraint("amount_paise > 0", name="ck_khata_entries_amount_positive"),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.customer_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["bill_id"],
            ["bills.bill_id"],
        ),
        sa.PrimaryKeyConstraint("khata_entry_id"),
    )
    op.create_index(
        "ix_khata_entries_customer_id",
        "khata_entries",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        "uq_khata_entries_bill_id",
        "khata_entries",
        ["bill_id"],
        unique=True,
        postgresql_where=sa.text("bill_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_khata_entries_bill_id", table_name="khata_entries")
    op.drop_index("ix_khata_entries_customer_id", table_name="khata_entries")
    op.drop_table("khata_entries")
    op.drop_index("ix_customers_name", table_name="customers")
    op.drop_table("customers")
