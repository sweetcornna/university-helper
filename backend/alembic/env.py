"""Alembic environment.

We don't have a SQLAlchemy ORM in this project — migrations are written as
raw DDL through `op.execute`/`op.create_index`. So `target_metadata` stays
None and autogenerate is disabled by design.

DB URL is built from the same env vars the app reads (app/config.py),
so `alembic upgrade head` works inside the container without duplicating config.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _db_url() -> str:
    override = os.getenv("ALEMBIC_DB_URL")
    if override:
        return override
    user = os.getenv("MAIN_DB_USER") or "postgres"
    password = os.getenv("MAIN_DB_PASSWORD") or ""
    host = os.getenv("MAIN_DB_HOST") or "localhost"
    port = os.getenv("MAIN_DB_PORT") or "5432"
    name = os.getenv("MAIN_DB_NAME") or "main_db"
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _db_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
