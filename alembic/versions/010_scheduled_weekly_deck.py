"""Sent jobs table for scheduler idempotency (weekly analysis deck)."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "010_scheduled_weekly_deck"
down_revision: str | Sequence[str] | None = "009_shop_branding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sent_jobs",
        sa.Column("owner_telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("job_key", sa.Text(), nullable=False),
        sa.Column("period_key", sa.Text(), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "owner_telegram_user_id",
            "job_key",
            "period_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("sent_jobs")
