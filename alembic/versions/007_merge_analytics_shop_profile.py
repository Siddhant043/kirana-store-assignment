"""Merge analytics views and shop_profile migration heads."""

from collections.abc import Sequence

from alembic import op

revision: str = "007_merge_analytics_shop_profile"
down_revision: str | Sequence[str] | None = ("005_analytics", "006_shop_profile")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
