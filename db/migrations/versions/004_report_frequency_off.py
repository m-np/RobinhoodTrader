"""Set report_frequency default to off

Revision ID: 004
Revises: 003
Create Date: 2026-06-12
"""
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Migrate the old "weekly" seeded default to "off".
    # Only touches rows that still have the original seeded value
    # so any user who explicitly chose "weekly" keeps it.
    op.execute(
        "UPDATE config_knobs "
        "SET value = '\"off\"', updated_at = CURRENT_TIMESTAMP "
        "WHERE key = 'report_frequency' AND value = '\"weekly\"'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE config_knobs "
        "SET value = '\"weekly\"', updated_at = CURRENT_TIMESTAMP "
        "WHERE key = 'report_frequency' AND value = '\"off\"'"
    )
