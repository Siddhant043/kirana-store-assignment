"""Baseline migration: processed_updates table for transport idempotency."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "001_baseline_processed_updates"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processed_updates",
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("update_id"),
    )


def downgrade() -> None:
    op.drop_table("processed_updates")
