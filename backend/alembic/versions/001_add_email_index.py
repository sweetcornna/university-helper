"""baseline: ensure users.email index exists

The users table already has email UNIQUE which gives an implicit index, so
this baseline is intentionally idempotent — fresh DBs no-op, existing prod
DBs without the named index gain one.

This is the ROOT of the *main_db* migration branch (users / rate_limit_counters).
It targets the MAIN database only and MUST NOT be applied to tenant DBs, which
have no `users` table. The tenant schema lives on a separate branch
(branch_labels=('tenant_db',), revision t001). Run main-DB migrations with
`alembic upgrade main_db@head` and tenant migrations with
`alembic upgrade tenant_db@head` (scripts/migrate_tenants.py does the latter).

Revision ID: 001
Revises:
Create Date: 2026-02-17
"""
from alembic import op

revision = '001'
down_revision = None
branch_labels = ('main_db',)
depends_on = None


def upgrade():
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_users_email")
