"""Shop Profile table for invoice header identity."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "006_shop_profile"
down_revision: str | Sequence[str] | None = "004_khata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shop_profile",
        sa.Column("owner_telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("shop_name", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("gstin", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("owner_telegram_user_id"),
    )


def downgrade() -> None:
    op.drop_table("shop_profile")
