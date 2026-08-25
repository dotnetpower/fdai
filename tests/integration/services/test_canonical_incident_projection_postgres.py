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
from fdai_operator_service.incident_projection import incident_summary
from fdai_operator_service.postgres_sql import INCIDENT_CURRENT_PAGE_SQL, INCIDENT_PAGE_SQL
from psycopg import sql
from psycopg.rows import dict_row

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATION = (
    REPO_ROOT / "service-migrations/branches/core-control-plane/versions/"
    "20260819_core_incident_projection.py"
)
CANONICAL_MIGRATION = (
    REPO_ROOT / "service-migrations/branches/core-control-plane/versions/"
    "20260825_core_canonical_incident_projection.py"
)


def _migration_sql(path: Path, action: str) -> str:
    statements: list[str] = []
    migration = runpy.run_path(str(path))
    with patch("alembic.op.execute", side_effect=lambda statement: statements.append(statement)):
        migration[action]()
    return "\n".join(statements)


@pytest.fixture
def disposable_database_url() -> Iterator[str]:
    source = os.environ.get("FDAI_VALIDATION_DATABASE_URL")
    if not source:
        pytest.skip("FDAI_VALIDATION_DATABASE_URL is unset")
    source = source.replace("postgresql+psycopg://", "postgresql://", 1)
    parts = urlsplit(source)
    database = "fdai_canonical_incident_" + uuid4().hex[:12]
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


def test_canonical_projection_excludes_audit_only_correlations_and_pins_identity(
    disposable_database_url: str,
) -> None:
    with psycopg.connect(disposable_database_url, row_factory=dict_row) as connection:
        connection.execute(
            """
            CREATE TABLE audit_log (
                seq BIGSERIAL PRIMARY KEY,
                event_id TEXT NOT NULL,
                correlation_id TEXT,
                actor TEXT NOT NULL,
                action_kind TEXT NOT NULL,
                mode TEXT NOT NULL,
                entry JSONB NOT NULL,
                previous_hash TEXT NOT NULL DEFAULT '',
                entry_hash TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        connection.execute(_migration_sql(BASE_MIGRATION, "upgrade"))
        connection.execute(
            """
            INSERT INTO audit_log (
                event_id, correlation_id, actor, action_kind, mode, entry
            ) VALUES (
                'audit-only-event', 'audit-only', 'fdai.core.control_loop',
                'risk_gate.unified', 'shadow', '{"decision":"hil"}'::jsonb
            )
            """
        )
        pre_open_row = connection.execute(
            """
            INSERT INTO audit_log (
                event_id, correlation_id, actor, action_kind, mode, entry
            ) VALUES (
                'incident-before-open', 'incident-correlation',
                'fdai.core.control_loop', 'risk_gate.unified', 'shadow',
                '{"decision":"hil"}'::jsonb
            ) RETURNING seq
            """
        ).fetchone()
        assert pre_open_row is not None
        pre_open_snapshot = pre_open_row["seq"]
        connection.execute(
            """
            CREATE FUNCTION fdai_stale_canonical_incident_trigger()
            RETURNS TRIGGER LANGUAGE plpgsql AS $function$
            BEGIN
                RETURN NEW;
            END;
            $function$;
            CREATE TRIGGER audit_log_zz_operator_incident_canonical
                AFTER INSERT ON audit_log
                FOR EACH ROW
                EXECUTE FUNCTION fdai_stale_canonical_incident_trigger();
            """
        )
        connection.execute(_migration_sql(CANONICAL_MIGRATION, "upgrade"))
        trigger_definition = connection.execute(
            """
            SELECT pg_get_triggerdef(trigger.oid, TRUE) AS definition
              FROM pg_trigger AS trigger
             WHERE trigger.tgrelid = 'audit_log'::regclass
               AND trigger.tgname = 'audit_log_zz_operator_incident_canonical'
               AND NOT trigger.tgisinternal
            """
        ).fetchone()
        connection.execute(
            """
            INSERT INTO audit_log (
                event_id, correlation_id, actor, action_kind, mode, entry
            ) VALUES (
                'incident-event', 'incident-correlation', 'Huginn',
                'incident.open', 'shadow',
                '{
                    "kind":"incident.open",
                    "incident_id":"incident-1",
                    "incident_number":"INC-202608-0001",
                    "opened_at":"2026-08-25T00:00:00+00:00",
                    "state":"open"
                }'::jsonb
            )
            """
        )
        connection.execute(
            """
            INSERT INTO audit_log (
                event_id, correlation_id, actor, action_kind, mode, entry
            ) VALUES (
                'incident-ticket', 'incident-correlation', 'Var',
                'incident.ticket', 'shadow',
                '{"kind":"incident.ticket","ticket_id":"ticket-1"}'::jsonb
            )
            """
        )
        connection.execute(
            """
            INSERT INTO audit_log (
                event_id, correlation_id, actor, action_kind, mode, entry
            ) VALUES (
                'incident-transition', 'incident-correlation', 'Huginn',
                'incident.transition', 'shadow',
                '{"kind":"incident.transition","to_state":"triaging"}'::jsonb
            )
            """
        )
        for sequence in range(101):
            connection.execute(
                """
                INSERT INTO audit_log (
                    event_id, correlation_id, actor, action_kind, mode, entry
                ) VALUES (%s, 'incident-correlation', 'fdai.core.control_loop',
                    'risk_gate.unified', 'shadow', '{"decision":"hil"}'::jsonb)
                """,
                (f"incident-progress-{sequence}",),
            )

        rows = connection.execute(
            INCIDENT_CURRENT_PAGE_SQL,
            {
                "snapshot_seq": None,
                "before_seq": None,
                "status": "all",
                "search": None,
                "vertical": None,
                "severity": None,
                "correlation_id": None,
                "fetch": 25,
                "history_limit": 100,
            },
        ).fetchall()
        pre_open_rows = connection.execute(
            INCIDENT_PAGE_SQL,
            {
                "snapshot_seq": pre_open_snapshot,
                "before_seq": None,
                "status": "all",
                "search": None,
                "vertical": None,
                "severity": None,
                "correlation_id": "incident-correlation",
                "fetch": 25,
                "history_limit": 100,
            },
        ).fetchall()
        audit_only = connection.execute(
            """
            SELECT has_canonical_incident
              FROM operator_incident_projection
             WHERE correlation_id = 'audit-only' AND valid_to_seq IS NULL
            """
        ).fetchone()
        canonical_projection = connection.execute(
            """
            SELECT has_canonical_incident,
                   canonical_incident_id,
                   canonical_incident_number,
                   canonical_ticket_id,
                   canonical_opened_at,
                   projected_state
              FROM operator_incident_projection
             WHERE correlation_id = 'incident-correlation' AND valid_to_seq IS NULL
            """
        ).fetchone()

    assert audit_only == {"has_canonical_incident": False}
    assert trigger_definition is not None
    assert (
        "fdai_mark_operator_incident_projection_canonical_trigger()"
        in (trigger_definition["definition"])
    )
    assert "fdai_stale_canonical_incident_trigger()" not in trigger_definition["definition"]
    assert canonical_projection == {
        "has_canonical_incident": True,
        "canonical_incident_id": "incident-1",
        "canonical_incident_number": "INC-202608-0001",
        "canonical_ticket_id": "ticket-1",
        "canonical_opened_at": "2026-08-25T00:00:00+00:00",
        "projected_state": "triaging",
    }
    assert pre_open_rows == []
    assert len(rows) == 100
    assert all(row["normalized_correlation_id"] == "incident-correlation" for row in rows)
    assert rows[0]["matched_groups"] == 1
    assert all(row["entry"].get("kind") is None for row in rows)
    summary = incident_summary(rows)
    assert summary["incident_id"] == "incident-1"
    assert summary["incident_number"] == "INC-202608-0001"
    assert summary["ticket_id"] == "ticket-1"
    assert summary["opened_at"] == "2026-08-25T00:00:00+00:00"
    assert summary["status"] == "in_progress"
    assert summary["status_source"] == "incident_lifecycle"
    assert summary["lifecycle_state"] == "triaging"
