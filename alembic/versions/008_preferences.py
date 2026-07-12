"""Owner Preferences key/value store."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "008_preferences"
down_revision: str | Sequence[str] | None = "007_merge_analytics_shop_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "preferences",
        sa.Column("owner_telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("preference_key", sa.Text(), nullable=False),
        sa.Column("preference_value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("owner_telegram_user_id", "preference_key"),
    )


def downgrade() -> None:
    op.drop_table("preferences")
