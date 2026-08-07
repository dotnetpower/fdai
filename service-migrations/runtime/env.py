"""Alembic environment for one service-owned migration branch."""

from __future__ import annotations

import hashlib
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool, text

config = context.config
target_metadata = None

service_id = config.get_main_option("service_id")
version_table = config.get_main_option("version_table")
if not service_id or not version_table:
    raise RuntimeError("service_id and version_table are required in the Alembic config")

database_url = os.environ.get("FDAI_DATABASE_URL", "").strip()
if not database_url:
    raise RuntimeError("FDAI_DATABASE_URL is required for service migrations")
if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
    print("FDAI_DATABASE_URL must be a PostgreSQL URL", file=sys.stderr)
    raise SystemExit(2)
if database_url.startswith("postgresql://"):
    database_url = "postgresql+psycopg://" + database_url[len("postgresql://") :]
config.set_main_option("sqlalchemy.url", database_url)

lock_digest = hashlib.sha256(f"fdai-migration:{service_id}".encode()).digest()
migration_lock_key = int.from_bytes(lock_digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


def run_migrations_offline() -> None:
    """Render only the selected service branch as SQL."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=version_table,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply the selected service branch under its PostgreSQL advisory lock."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=version_table,
        )
        with context.begin_transaction():
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": migration_lock_key},
            )
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
