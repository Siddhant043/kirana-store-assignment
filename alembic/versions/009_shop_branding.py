"""Add Shop Profile logo_url and accent_color branding columns."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "009_shop_branding"
down_revision: str | Sequence[str] | None = "008_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shop_profile",
        sa.Column("logo_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "shop_profile",
        sa.Column("accent_color", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shop_profile", "accent_color")
    op.drop_column("shop_profile", "logo_url")
