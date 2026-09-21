"""Live PostgreSQL checks for bounded inventory progress hot replay."""

from __future__ import annotations

import os
import runpy
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPO_ROOT
    / "service-migrations/branches/core-control-plane/versions/"
    / "20260921_core_inventory_progress_retention.py"
)


@pytest.fixture
def disposable_database_url() -> Iterator[str]:
    source = os.environ.get("FDAI_VALIDATION_DATABASE_URL")
    if not source:
        pytest.skip("FDAI_VALIDATION_DATABASE_URL is unset")
    source = source.replace("postgresql+psycopg://", "postgresql://", 1)
    parts = urlsplit(source)
    database = "fdai_inventory_progress_" + uuid4().hex[:12]
    admin = psycopg.connect(source, dbname="postgres", autocommit=True)
    try:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    except psycopg.errors.InsufficientPrivilege:
        admin.close()
        pytest.skip("validation database principal cannot create a disposable database")
    try:
        yield urlunsplit(parts._replace(path=f"/{database}"))
    finally:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database))
        )
        admin.close()


def _migration_sql(action: str) -> str:
    statements: list[str] = []
    migration = runpy.run_path(str(MIGRATION))
    with patch("alembic.op.execute", side_effect=lambda statement: statements.append(statement)):
        migration[action]()
    return "\n".join(statements)


def _upgrade_function_sql() -> str:
    return _migration_sql("upgrade").replace(
        "GRANT EXECUTE ON FUNCTION fdai_prune_inventory_progress(INTEGER) TO fdai_core;",
        "",
    )


def test_retention_keeps_active_and_newest_terminal_attempts(
    disposable_database_url: str,
) -> None:
    with psycopg.connect(disposable_database_url) as connection:
        connection.execute(
            """
            CREATE TABLE inventory_progress_event (
                event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                run_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                sequence BIGINT NOT NULL,
                state TEXT NOT NULL,
                payload JSONB NOT NULL
            )
            """
        )
        connection.execute(_upgrade_function_sql())
        for index in range(18):
            connection.execute(
                "INSERT INTO inventory_progress_event "
                "(run_id, attempt_id, sequence, state, payload) VALUES "
                "(%s, %s, 1, 'running', '{\"deadline_at\":\"2999-01-01T00:00:00Z\"}'), "
                "(%s, %s, 2, 'complete', '{\"deadline_at\":\"2999-01-01T00:00:00Z\"}')",
                (f"run.{index}", "attempt.1", f"run.{index}", "attempt.1"),
            )
        connection.execute(
            "INSERT INTO inventory_progress_event "
            "(run_id, attempt_id, sequence, state, payload) VALUES "
            "('run.active', 'attempt.1', 1, 'running', "
            '\'{"deadline_at":"2999-01-01T00:00:00Z"}\'), '
            "('run.expired', 'attempt.1', 1, 'running', "
            '\'{"deadline_at":"2000-01-01T00:00:00Z"}\'), '
            "('run.expired', 'attempt.1', 2, 'running', "
            '\'{"deadline_at":"2000-01-01T00:00:00Z"}\')'
        )

        deleted = connection.execute("SELECT fdai_prune_inventory_progress(16)").fetchone()
        retained = connection.execute(
            "SELECT COUNT(*) AS rows, COUNT(DISTINCT (run_id, attempt_id)) AS attempts "
            "FROM inventory_progress_event"
        ).fetchone()
        active = connection.execute(
            "SELECT COUNT(*) FROM inventory_progress_event WHERE run_id='run.active'"
        ).fetchone()

    assert deleted == (6,)
    assert retained == (33, 17)
    assert active == (1,)


def test_retention_rejects_invalid_bound(disposable_database_url: str) -> None:
    with psycopg.connect(disposable_database_url) as connection:
        connection.execute(
            "CREATE TABLE inventory_progress_event ("
            "event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
            "run_id TEXT NOT NULL, attempt_id TEXT NOT NULL, "
            "sequence BIGINT NOT NULL, state TEXT NOT NULL, payload JSONB NOT NULL)"
        )
        connection.execute(_upgrade_function_sql())
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            connection.execute("SELECT fdai_prune_inventory_progress(0)")


def test_migration_grants_only_guarded_function_execution_to_core() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "pg_advisory_xact_lock" in source
    assert "GRANT EXECUTE ON FUNCTION fdai_prune_inventory_progress(INTEGER) TO fdai_core" in source
    assert "GRANT DELETE ON TABLE inventory_progress_event" not in source
