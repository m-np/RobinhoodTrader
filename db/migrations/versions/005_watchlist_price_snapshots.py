"""Add watchlist_price_snapshots table

Revision ID: 005
Revises: 004
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_price_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_watchlist_price_snapshots_ticker", "watchlist_price_snapshots", ["ticker"])
    op.create_index("ix_watchlist_price_snapshots_recorded_at", "watchlist_price_snapshots", ["recorded_at"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_price_snapshots_recorded_at", "watchlist_price_snapshots")
    op.drop_index("ix_watchlist_price_snapshots_ticker", "watchlist_price_snapshots")
    op.drop_table("watchlist_price_snapshots")
