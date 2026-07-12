"""Analytics views and bill finalized_at index."""

from collections.abc import Sequence

from alembic import op

revision: str = "005_analytics"
down_revision: str | Sequence[str] | None = "004_khata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_bills_finalized_at", "bills", ["finalized_at"], unique=False)

    op.execute(
        """
        CREATE VIEW daily_summary AS
        SELECT
            (b.finalized_at AT TIME ZONE 'Asia/Kolkata')::date AS business_date,
            b.payment_mode,
            COUNT(*)::bigint AS bill_count,
            SUM(b.total_paise)::bigint AS total_paise,
            SUM(b.subtotal_paise)::bigint AS subtotal_paise,
            SUM(b.cgst_paise)::bigint AS cgst_paise,
            SUM(b.sgst_paise)::bigint AS sgst_paise,
            SUM(b.round_off_paise)::bigint AS round_off_paise
        FROM bills b
        GROUP BY business_date, b.payment_mode
        """
    )

    op.execute(
        """
        CREATE VIEW sales_report AS
        SELECT
            (b.finalized_at AT TIME ZONE 'Asia/Kolkata')::date AS business_date,
            bl.product_id,
            p.name AS product_name,
            SUM(bl.quantity) AS quantity,
            SUM(bl.line_total_paise)::bigint AS revenue_paise,
            COUNT(DISTINCT b.bill_id)::bigint AS bill_count
        FROM bill_lines bl
        JOIN bills b ON b.bill_id = bl.bill_id
        JOIN products p ON p.product_id = bl.product_id
        GROUP BY business_date, bl.product_id, p.name
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS sales_report")
    op.execute("DROP VIEW IF EXISTS daily_summary")
    op.drop_index("ix_bills_finalized_at", table_name="bills")
