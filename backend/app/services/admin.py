"""Who counts as an administrator on the server edition.

There is no role column. Administrators are the accounts whose email is listed
in ``ADMIN_EMAILS`` (comma separated, case-insensitive). When that setting is
empty, the first account ever registered (smallest ``users.id``) is the
administrator, which matches a typical self-hosted install where the operator
signs up first.
"""

from __future__ import annotations

from app import config
from app.db.session import get_db_session


def admin_emails() -> set[str]:
    return {email.lower() for email in config.split_csv(config.settings.ADMIN_EMAILS)}


def is_admin_user(user_id: int) -> bool:
    configured = admin_emails()
    with get_db_session() as conn, conn.cursor() as cur:
        if configured:
            cur.execute("SELECT email FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return bool(row) and str(row["email"]).lower() in configured
        cur.execute("SELECT MIN(id) AS id FROM users")
        row = cur.fetchone()
        return bool(row) and row["id"] is not None and int(row["id"]) == int(user_id)
