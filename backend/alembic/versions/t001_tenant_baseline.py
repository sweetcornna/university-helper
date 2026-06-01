"""tenant baseline: todos / attachments / sessions

This is the ROOT of the *tenant_db* migration branch. Tenant databases are
cloned from database/templates/tenant_template.sql (todos / attachments /
sessions) and have NO `users` table, so the main-DB migrations (001/002) must
NEVER run against them. Keeping the tenant schema on its own branch
(branch_labels=('tenant_db',)) lets scripts/migrate_tenants.py run
`alembic upgrade tenant_db@head` against tenant DBs without touching the
main-DB DDL.

Every statement is idempotent (IF NOT EXISTS) so stamping/upgrading an
already-cloned tenant DB is a safe no-op; only genuinely new tenant-schema
changes (added as descendants of this revision) do real work.

Revision ID: t001
Revises:
Create Date: 2026-05-31
"""
from alembic import op

revision = 't001'
down_revision = None
branch_labels = ('tenant_db',)
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS todos (
            id SERIAL PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            status VARCHAR(20) DEFAULT 'pending'
                CHECK (status IN ('pending', 'in_progress', 'completed')),
            priority INT DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_todos_created_at ON todos(created_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS attachments (
            id SERIAL PRIMARY KEY,
            todo_id INT REFERENCES todos(id) ON DELETE CASCADE,
            file_name VARCHAR(255) NOT NULL,
            file_path TEXT NOT NULL,
            file_size BIGINT,
            mime_type VARCHAR(100),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_attachments_todo_id ON attachments(todo_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id SERIAL PRIMARY KEY,
            session_token VARCHAR(255) UNIQUE NOT NULL,
            user_agent TEXT,
            ip_address INET,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS update_todos_updated_at ON todos")
    op.execute(
        """
        CREATE TRIGGER update_todos_updated_at
        BEFORE UPDATE ON todos
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column()
        """
    )


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS update_todos_updated_at ON todos")
    op.execute("DROP TABLE IF EXISTS attachments")
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS todos")
