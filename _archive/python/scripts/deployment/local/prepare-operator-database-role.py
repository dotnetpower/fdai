#!/usr/bin/env python3
"""Apply the canonical Operator runtime-role migration to local PostgreSQL."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Protocol, cast

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = (
    REPO_ROOT
    / "service-migrations/branches/operator-service/versions/20260808_operator_runtime_role.py"
)
MIGRATION_LOCK_KEY = 0x464441494F50524C


class RuntimeRoleMigration(Protocol):
    """Describe the canonical migration members used by local preparation."""

    op: object

    def upgrade(self) -> None: ...


class LocalOperations:
    """Adapt the migration's Alembic operation to an existing local connection."""

    def __init__(self, connection: psycopg.Connection[object]) -> None:
        self._connection = connection

    def execute(self, statement: str) -> None:
        """Execute one trusted SQL statement from the canonical migration."""
        self._connection.execute(statement)


def _load_migration() -> RuntimeRoleMigration:
    spec = importlib.util.spec_from_file_location("fdai_local_operator_role", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Operator runtime-role migration could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(RuntimeRoleMigration, module)


def _psycopg_dsn(value: str) -> str:
    prefix = "postgresql+psycopg://"
    return f"postgresql://{value[len(prefix) :]}" if value.startswith(prefix) else value


def main() -> int:
    """Apply the idempotent role migration under a transaction advisory lock."""
    database_url = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("FDAI_DATABASE_URL MUST be configured")

    migration = _load_migration()
    with psycopg.connect(_psycopg_dsn(database_url)) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_KEY,))
        migration.op = LocalOperations(connection)
        migration.upgrade()
    print("local Operator Service database role is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
