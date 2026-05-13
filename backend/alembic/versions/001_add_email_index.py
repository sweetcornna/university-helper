"""baseline: ensure users.email index exists

The users table already has email UNIQUE which gives an implicit index, so
this baseline is intentionally idempotent — fresh DBs no-op, existing prod
DBs without the named index gain one.

Revision ID: 001
Revises:
Create Date: 2026-02-17
"""
from alembic import op

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_users_email")
