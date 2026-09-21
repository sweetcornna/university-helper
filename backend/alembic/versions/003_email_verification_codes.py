"""email verification codes

One row per (email, scene): a resend UPSERTs over the previous code, which
bounds the number of rows per address and invalidates the old code for free.

Revision ID: 003
Revises: 002
Create Date: 2026-07-26
"""
from alembic import op

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS email_verification_codes (
            email VARCHAR(255) NOT NULL,
            scene VARCHAR(32) NOT NULL,
            code_hash CHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            attempts INT NOT NULL DEFAULT 0,
            last_sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (email, scene)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_email_verification_codes_expires_at "
        "ON email_verification_codes (expires_at)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_email_verification_codes_expires_at")
    op.execute("DROP TABLE IF EXISTS email_verification_codes")
