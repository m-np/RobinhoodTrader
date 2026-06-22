"""Add stock_discoveries table

Revision ID: 006
Revises: 005
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_discoveries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("confidence", sa.String(), nullable=True),
        sa.Column("source_summary", sa.String(), nullable=True),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("added_to_watchlist", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_stock_discoveries_ticker", "stock_discoveries", ["ticker"])
    op.create_index("ix_stock_discoveries_created_at", "stock_discoveries", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_stock_discoveries_created_at", "stock_discoveries")
    op.drop_index("ix_stock_discoveries_ticker", "stock_discoveries")
    op.drop_table("stock_discoveries")
