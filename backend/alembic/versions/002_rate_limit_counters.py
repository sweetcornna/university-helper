"""rate limit counters

Revision ID: 002
Revises: 001
Create Date: 2026-04-16

"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rate_limit_counters (
            client_id TEXT NOT NULL,
            window_start TIMESTAMPTZ NOT NULL,
            count INT NOT NULL DEFAULT 0,
            PRIMARY KEY (client_id, window_start)
        )
        """
    )
    op.create_index(
        'ix_rate_limit_counters_window_start',
        'rate_limit_counters',
        ['window_start'],
    )


def downgrade():
    op.drop_index(
        'ix_rate_limit_counters_window_start',
        table_name='rate_limit_counters',
    )
    op.drop_table('rate_limit_counters')
