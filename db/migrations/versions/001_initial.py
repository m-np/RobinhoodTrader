"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("asset_class", sa.String(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price_usd", sa.Float(), nullable=False),
        sa.Column("total_usd", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending_approval"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("mirror_source", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "watchlist",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("ticker", sa.String(), unique=True, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "blocklist",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("ticker", sa.String(), unique=True, nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "config_knobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("key", sa.String(), unique=True, nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "mirror_sources",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), unique=True, nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("scale_factor", sa.Float(), nullable=False, server_default="0.02"),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("ticker", sa.String(), nullable=True),
        sa.Column("alert_type", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False, server_default="info"),
        sa.Column("acknowledged", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("trade_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("pnl_usd", sa.Float(), nullable=True),
        sa.Column("pnl_pct", sa.Float(), nullable=True),
        sa.Column("report_type", sa.String(), nullable=False, server_default="weekly"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("reports")
    op.drop_table("alerts")
    op.drop_table("mirror_sources")
    op.drop_table("config_knobs")
    op.drop_table("blocklist")
    op.drop_table("watchlist")
    op.drop_table("trades")
