"""Seed native-script Product Aliases for Hindi and Tamil grounding."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.sql import column, table

from alembic import op

revision: str = "012_multilingual_aliases"
down_revision: str | Sequence[str] | None = "011_fefo_batch_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Native-script aliases only — Latin transliterations already seeded in 002.
NATIVE_ALIASES: list[tuple[str, str]] = [
    ("Sugar", "चीनी"),
    ("Sugar", "சர்க்கரை"),
    ("Tata Salt 1kg", "नमक"),
    ("Tata Salt 1kg", "உப்பு"),
    ("Rice", "चावल"),
    ("Rice", "அரிசி"),
    ("Aashirvaad Atta 5kg", "आटा"),
    ("Maggi Noodles 70g", "मैगी"),
    ("Maggi Noodles 70g", "மேகி"),
    ("Fortune Sunflower Oil 1L", "तेल"),
    ("Fortune Sunflower Oil 1L", "எண்ணெய்"),
    ("Amul Butter 100g", "मक्खन"),
    ("Parle-G Biscuits", "बिस्कुट"),
    ("Surf Excel 1kg", "डिटर्जेंट"),
]


def upgrade() -> None:
    connection = op.get_bind()
    aliases = table(
        "aliases",
        column("product_id", sa.BigInteger),
        column("alias", sa.Text),
    )
    for product_name, alias in NATIVE_ALIASES:
        product_id = connection.execute(
            sa.text("SELECT product_id FROM products WHERE name = :name"),
            {"name": product_name},
        ).scalar_one()
        connection.execute(
            aliases.insert().values(product_id=product_id, alias=alias)
        )


def downgrade() -> None:
    aliases_to_remove = [alias for _, alias in NATIVE_ALIASES]
    for alias in aliases_to_remove:
        op.execute(
            sa.text("DELETE FROM aliases WHERE alias = :alias").bindparams(
                alias=alias
            )
        )
