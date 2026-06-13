"""Add portfolio_snapshots table

Revision ID: 003
Revises: 002
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("total_value", sa.Float(), nullable=False),
        sa.Column("equity_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cash", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_portfolio_snapshots_created_at", "portfolio_snapshots", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_portfolio_snapshots_created_at", "portfolio_snapshots")
    op.drop_table("portfolio_snapshots")
