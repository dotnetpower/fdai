from __future__ import annotations

import json
import os
import runpy
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from fdai_operator_service.families.cost_governance.contracts import (
    COST_DISCLOSURE_RETENTION_DAYS,
    CostDisclosureAuditRecord,
)
from fdai_operator_service.postgres_cost_governance import (
    PostgresCostGovernanceConfig,
    PostgresCostGovernanceReader,
)
from psycopg import sql

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = (
    _ROOT
    / "service-migrations/branches/operator-service/versions"
    / "20260912_operator_cost_disclosure_audit.py"
)


def _upgrade_sql() -> str:
    module = runpy.run_path(str(_MIGRATION))
    statements: list[str] = []
    module["upgrade"].__globals__["op"] = SimpleNamespace(execute=statements.append)
    module["upgrade"]()
    return "\n".join(statements)


@pytest.fixture
def disposable_database_url() -> Iterator[str]:
    source = os.environ.get("FDAI_VALIDATION_DATABASE_URL")
    if not source:
        pytest.skip("FDAI_VALIDATION_DATABASE_URL is unset")
    source = source.replace("postgresql+psycopg://", "postgresql://", 1)
    parts = urlsplit(source)
    database = "fdai_cost_disclosure_" + uuid4().hex[:12]
    admin = psycopg.connect(source, dbname="postgres", autocommit=True)
    try:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    except psycopg.errors.InsufficientPrivilege:
        admin.close()
        pytest.skip("validation database principal cannot create a disposable database")
    try:
        database_url = urlunsplit(parts._replace(path=f"/{database}"))
        with psycopg.connect(database_url) as connection:
            connection.execute(
                """
                CREATE FUNCTION fdai_set_cost_governance_enabled(
                    TEXT, TEXT, BOOLEAN, BIGINT, TEXT
                ) RETURNS VOID LANGUAGE SQL AS 'SELECT';
                CREATE FUNCTION fdai_set_cost_governance_enabled_legacy(
                    TEXT, TEXT, BOOLEAN, BIGINT, TEXT
                ) RETURNS VOID LANGUAGE SQL AS 'SELECT';
                REVOKE ALL ON FUNCTION fdai_set_cost_governance_enabled(
                    TEXT, TEXT, BOOLEAN, BIGINT, TEXT
                ) FROM PUBLIC;
                REVOKE ALL ON FUNCTION fdai_set_cost_governance_enabled_legacy(
                    TEXT, TEXT, BOOLEAN, BIGINT, TEXT
                ) FROM PUBLIC;
                GRANT EXECUTE ON FUNCTION fdai_set_cost_governance_enabled_legacy(
                    TEXT, TEXT, BOOLEAN, BIGINT, TEXT
                ) TO fdai_operator;
                """
            )
        yield database_url
    finally:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database))
        )
        admin.close()


async def test_disclosure_audit_is_content_free_and_idempotent(
    disposable_database_url: str,
) -> None:
    with psycopg.connect(disposable_database_url) as connection:
        connection.execute(_upgrade_sql())
    record = CostDisclosureAuditRecord(
        decision_id=f"sha256:{'a' * 64}",
        principal_digest=f"sha256:{'b' * 64}",
        scope_digest=f"sha256:{'c' * 64}",
        surface="resource-efficiency",
        grant_revision=2,
        ceiling_revision=3,
        activation_revision=4,
        disclosure_digest=f"sha256:{'d' * 64}",
        record_count=5,
        suppressed_count=2,
        occurred_at=datetime(2026, 9, 12, tzinfo=UTC),
        retention_until=datetime(2026, 9, 12, tzinfo=UTC)
        + timedelta(days=COST_DISCLOSURE_RETENTION_DAYS),
    )
    reader = PostgresCostGovernanceReader(PostgresCostGovernanceConfig(dsn=disposable_database_url))

    await reader.append_disclosure_audit(record)
    await reader.append_disclosure_audit(record)

    with psycopg.connect(disposable_database_url) as connection:
        row = connection.execute(
            "SELECT *, row_to_json(cost_disclosure_audit)::TEXT AS serialized "
            "FROM cost_disclosure_audit"
        ).fetchone()
    assert row is not None
    assert row[10] is True
    assert row[0] == record.decision_id
    assert "reader-id" not in row[-1]
    assert "subscriptions/" not in row[-1]


async def test_disclosure_retention_honors_legal_hold_before_tombstone(
    disposable_database_url: str,
) -> None:
    with psycopg.connect(disposable_database_url) as connection:
        connection.execute(_upgrade_sql())
    occurred_at = datetime(2026, 9, 12, tzinfo=UTC)
    record = CostDisclosureAuditRecord(
        decision_id=f"sha256:{'1' * 64}",
        principal_digest=f"sha256:{'2' * 64}",
        scope_digest=f"sha256:{'3' * 64}",
        surface="overview",
        grant_revision=2,
        ceiling_revision=3,
        activation_revision=4,
        disclosure_digest=f"sha256:{'4' * 64}",
        record_count=1,
        suppressed_count=0,
        occurred_at=occurred_at,
        retention_until=occurred_at + timedelta(days=COST_DISCLOSURE_RETENTION_DAYS),
    )
    reader = PostgresCostGovernanceReader(PostgresCostGovernanceConfig(dsn=disposable_database_url))
    await reader.append_disclosure_audit(record)

    assert await reader.set_disclosure_legal_hold(
        decision_id=record.decision_id,
        expected_revision=1,
        legal_hold_ref="legal-hold:case-001",
        recorded_at=occurred_at + timedelta(days=1),
        idempotency_key="hold:case-001",
    )
    assert (
        await reader.purge_disclosure_audit(
            now=occurred_at + timedelta(days=431),
            limit=10,
        )
        == ()
    )
    assert await reader.set_disclosure_legal_hold(
        decision_id=record.decision_id,
        expected_revision=2,
        legal_hold_ref=None,
        recorded_at=occurred_at + timedelta(days=2),
        idempotency_key="release:case-001",
    )
    assert await reader.purge_disclosure_audit(
        now=occurred_at + timedelta(days=431),
        limit=10,
    ) == (record.decision_id,)

    with psycopg.connect(disposable_database_url) as connection:
        retention = connection.execute(
            """
            SELECT revision, legal_hold, legal_hold_ref, purged_at
              FROM cost_disclosure_audit_retention
             WHERE decision_id = %s
            """,
            (record.decision_id,),
        ).fetchone()
        events = connection.execute(
            """
            SELECT event_kind
              FROM cost_disclosure_audit_retention_event
             WHERE decision_id = %s
             ORDER BY revision
            """,
            (record.decision_id,),
        ).fetchall()
        receipt_count = connection.execute(
            "SELECT COUNT(*) FROM cost_disclosure_audit WHERE decision_id = %s",
            (record.decision_id,),
        ).fetchone()
    assert retention is not None
    assert retention[:3] == (4, False, None)
    assert retention[3] is not None
    assert events == [("created",), ("hold-applied",), ("hold-released",), ("purged",)]
    assert receipt_count == (1,)


def test_disclosure_audit_migration_is_operator_owned_and_append_only() -> None:
    module = runpy.run_path(str(_MIGRATION))
    source = _MIGRATION.read_text(encoding="utf-8")

    assert module["migration_owner"] == "operator-service"
    assert set(module["owned_tables"]) == {
        "cost_disclosure_audit",
        "cost_disclosure_audit_retention",
        "cost_disclosure_audit_retention_event",
    }
    assert "GRANT SELECT, INSERT ON TABLE cost_disclosure_audit TO fdai_operator" in source
    assert "ON TABLE cost_disclosure_audit_retention TO fdai_operator" in source
    assert "GRANT DELETE" not in source


def test_disclosure_migration_moves_operator_execute_to_hardened_wrapper(
    disposable_database_url: str,
) -> None:
    with psycopg.connect(disposable_database_url) as connection:
        connection.execute(_upgrade_sql())
        privileges = connection.execute(
            """
            SELECT has_function_privilege(
                       'fdai_operator',
                       'fdai_set_cost_governance_enabled(text,text,boolean,bigint,text)',
                       'EXECUTE'
                   ),
                   has_function_privilege(
                       'fdai_operator',
                       'fdai_set_cost_governance_enabled_legacy(text,text,boolean,bigint,text)',
                       'EXECUTE'
                   )
            """
        ).fetchone()

    assert privileges == (True, False)


def test_disclosure_retention_matches_w7_policy() -> None:
    policy = json.loads((_ROOT / "config/cost-governance-w7-policy.json").read_text())

    assert policy["retention_days"] == COST_DISCLOSURE_RETENTION_DAYS
