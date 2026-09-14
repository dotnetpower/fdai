"""Real PostgreSQL transaction and service-role checks on a disposable local database."""

from __future__ import annotations

import os
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.core.human_assignment.request_processor import AssignmentRequestProcessor
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_assignment_receipts import PostgresAssignmentReceiptReader
from fdai.delivery.persistence.postgres_handover_goals import PostgresHandoverGoalReader
from fdai_operator_service.assignment_notice import assignment_notice_from_record
from fdai_operator_service.postgres_assignment_outbox import PostgresAssignmentOutbox
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / (
    "service-migrations/branches/operator-service/versions/20260914_operator_assignment_receipts.py"
)
CORE_MIGRATION = ROOT / (
    "service-migrations/branches/core-control-plane/versions/20260914_core_assignment_receipts.py"
)


@pytest.fixture
def database():
    source = os.environ.get("FDAI_ASSIGNMENT_TEST_DSN")
    if not source:
        pytest.skip("FDAI_ASSIGNMENT_TEST_DSN is unset")
    parameters = conninfo_to_dict(source)
    if parameters.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("assignment database test requires a loopback-only fixture")
    name = "fdai_assignment_" + uuid4().hex[:12]
    statements = []
    for path in (CORE_MIGRATION, MIGRATION):
        module = runpy.run_path(str(path))
        with patch("alembic.op.execute", side_effect=statements.append):
            module["upgrade"]()
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(
            """DO $roles$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fdai_core') THEN
                CREATE ROLE fdai_core NOLOGIN NOSUPERUSER NOBYPASSRLS;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fdai_operator') THEN
                CREATE ROLE fdai_operator NOLOGIN NOSUPERUSER NOBYPASSRLS;
            END IF;
            END; $roles$"""
        )
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        dsn = make_conninfo(source, dbname=name)
        try:
            with psycopg.connect(dsn) as connection:
                connection.execute(
                    """CREATE TABLE state_kv (
                        key TEXT PRIMARY KEY, value JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
                    GRANT USAGE ON SCHEMA public TO fdai_core, fdai_operator;
                    GRANT SELECT, INSERT, UPDATE ON state_kv TO fdai_core, fdai_operator;
                    CREATE TABLE audit_log (
                        seq BIGSERIAL PRIMARY KEY, event_id UUID NOT NULL,
                        correlation_id TEXT, actor TEXT NOT NULL, action_kind TEXT NOT NULL,
                        mode TEXT NOT NULL, entry JSONB NOT NULL, previous_hash TEXT NOT NULL,
                        entry_hash TEXT NOT NULL UNIQUE, created_at TIMESTAMPTZ DEFAULT NOW());
                    GRANT SELECT, INSERT ON audit_log TO fdai_core;
                    GRANT USAGE, SELECT ON SEQUENCE audit_log_seq_seq TO fdai_core;
                    """
                )
                for statement in statements:
                    connection.execute(statement)
            yield dsn
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _role(dsn, role):
    return make_conninfo(dsn, options=f"-c role={role}")


async def _create(database):
    store = PostgresFamilyStore(
        config=PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    )
    stored = await store.append_proposal(
        family="iam",
        operation="assignments.create",
        principal_id="human:owner",
        idempotency_key="assignment:test",
        payload={"principal": {"oid": "human:owner", "roles": ["Owner"]}},
    )
    return store, stored, assignment_notice_from_record(stored.record)


async def test_operator_insert_seals_request_atomically_for_read_only_core(database):
    _store, stored, notice = await _create(database)
    reader = PostgresAssignmentReceiptReader(
        PostgresStateStoreConfig(dsn=_role(database, "fdai_core"))
    )
    receipt = await reader.read_state(notice.proposal_ref)
    assert receipt["request_digest"] == stored.record["request_digest"]
    assert receipt["payload"] == stored.record["payload"]
    with psycopg.connect(_role(database, "fdai_core")) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "INSERT INTO operator_assignment_receipt(proposal_ref, record) VALUES (%s, %s)",
                ("operator-proposal:iam:" + "f" * 64, Jsonb({})),
            )


@pytest.mark.parametrize("role", ["fdai_operator", "fdai_core"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
async def test_receipts_cannot_be_rewritten_by_either_runtime(database, role, operation):
    _store, _stored, notice = await _create(database)
    with psycopg.connect(_role(database, role)) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            query = (
                "UPDATE operator_assignment_receipt SET record='{}' WHERE proposal_ref=%s"
                if operation == "UPDATE"
                else "DELETE FROM operator_assignment_receipt WHERE proposal_ref=%s"
            )
            connection.execute(query, (notice.proposal_ref,))


async def test_operator_cannot_forge_or_edit_canonical_case_state(database):
    with psycopg.connect(_role(database, "fdai_operator")) as connection:
        with pytest.raises(psycopg.errors.RaiseException, match="only Core"):
            connection.execute(
                "INSERT INTO state_kv(key,value) VALUES ('human_assignment:case:example','{}')"
            )
    with psycopg.connect(_role(database, "fdai_core")) as connection:
        connection.execute(
            "INSERT INTO state_kv(key,value) VALUES ('human_assignment:case:example','{}')"
        )
    with psycopg.connect(_role(database, "fdai_operator")) as connection:
        with pytest.raises(psycopg.errors.RaiseException, match="only Core"):
            connection.execute(
                "UPDATE state_kv SET value='{}' WHERE key='human_assignment:case:example'"
            )


async def test_source_payload_is_immutable_but_lease_metadata_can_change(database):
    _store, _stored, notice = await _create(database)
    outbox = PostgresAssignmentOutbox(
        PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    )
    claim = await outbox.claim()
    assert claim is not None and claim.key == notice.proposal_ref
    with psycopg.connect(_role(database, "fdai_operator")) as connection:
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            connection.execute(
                "UPDATE state_kv SET value = value || '{\"payload\":{}}'::jsonb WHERE key=%s",
                (notice.proposal_ref,),
            )
    assert await outbox.finish(claim)
    assert await outbox.claim() is None


async def test_failed_source_insert_leaves_no_receipt(database):
    _store, _stored, notice = await _create(database)
    with psycopg.connect(_role(database, "fdai_operator")) as connection:
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                "INSERT INTO state_kv(key,value) SELECT key,value FROM state_kv WHERE key=%s",
                (notice.proposal_ref,),
            )
    with psycopg.connect(_role(database, "fdai_core")) as connection:
        assert (
            connection.execute("SELECT count(*) FROM operator_assignment_receipt").fetchone()[0]
            == 1
        )


async def test_lease_steal_fences_the_original_closure(database):
    _store, _stored, notice = await _create(database)
    outbox = PostgresAssignmentOutbox(
        PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    )
    first = await outbox.claim()
    assert first is not None
    assert await outbox.claim() is None
    with psycopg.connect(_role(database, "fdai_operator")) as connection:
        connection.execute(
            "UPDATE state_kv SET value=value || jsonb_build_object("
            "'claim_expires_at', NOW()-interval '1 second') WHERE key=%s",
            (notice.proposal_ref,),
        )
    replacement = await outbox.claim()
    assert replacement is not None
    assert replacement.claim_id != first.claim_id
    assert not await outbox.finish(first)
    assert await outbox.finish(replacement)


async def test_submit_waits_for_core_revision_instead_of_overtaking_create(database):
    store, stored, notice = await _create(database)
    await store.append_proposal(
        family="iam",
        operation="assignments.submit",
        principal_id="human:owner",
        idempotency_key="assignment:test:submit",
        payload={
            "principal": {"oid": "human:owner", "roles": ["Owner"]},
            "case_id": notice.case_id,
            "expected_revision": 1,
        },
    )
    outbox = PostgresAssignmentOutbox(
        PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    )
    first = await outbox.claim()
    assert first is not None
    assert await outbox.finish(first)
    assert await outbox.claim() is None
    with psycopg.connect(_role(database, "fdai_core")) as connection:
        connection.execute(
            "INSERT INTO state_kv(key,value) VALUES (%s,%s),(%s,%s)",
            (
                f"human_assignment:operator-case:{notice.case_id}",
                Jsonb({"case_id": "case-example"}),
                "human_assignment:case:case-example",
                Jsonb({"revision": 1}),
            ),
        )
    second = await outbox.claim()
    assert second is not None
    assert second.record["operation"] == "assignments.submit"
    assert second.record["proposal_id"] != stored.record["proposal_id"]


async def test_real_operator_receipt_and_core_case_audit_transaction(database):
    operator = PostgresFamilyStore(
        config=PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    )
    core_config = PostgresStateStoreConfig(dsn=_role(database, "fdai_core"))
    core = PostgresStateStore(config=core_config)
    processor = AssignmentRequestProcessor(
        intake=AssignmentRequestIntake(
            receipts=PostgresAssignmentReceiptReader(core_config), store=core
        ),
        cases=AssignmentCaseService(core),
    )
    creation = await operator.append_proposal(
        family="iam",
        operation="assignments.create",
        principal_id="human:owner",
        idempotency_key="case:real-test",
        payload={
            "principal": {"oid": "human:owner", "roles": ["Owner"]},
            "idempotency_key": "case:real-test",
            "subject_provider": "entra",
            "subject_id": "human:subject",
            "requested_role": "Reader",
            "goal_refs": [],
            "duty_bindings": [
                {"agent_name": "Thor", "duty": "backup", "scope_ref": "scope:platform"}
            ],
            "justification": "Synthetic transaction test.",
        },
    )
    notice = assignment_notice_from_record(creation.record)
    with psycopg.connect(database) as connection:
        connection.execute("ALTER TABLE audit_log ADD CONSTRAINT test_audit_failure CHECK (FALSE)")
    with pytest.raises(psycopg.errors.CheckViolation):
        await processor.apply(notice, at=notice.accepted_at)
    assert not await core.read_states("human_assignment:case:", limit=5)
    with psycopg.connect(database) as connection:
        connection.execute("ALTER TABLE audit_log DROP CONSTRAINT test_audit_failure")
    draft = await processor.apply(notice, at=notice.accepted_at)
    case_id = draft["case_id"]
    for operation, actor, revision, extra in [
        ("assignments.submit", "human:owner", 1, {}),
        ("assignments.review", "human:reviewer", 2, {"decision": "approve"}),
    ]:
        stored = await operator.append_proposal(
            family="iam",
            operation=operation,
            principal_id=actor,
            idempotency_key=f"case:real-test:{operation}",
            payload={
                "principal": {"oid": actor, "roles": ["Owner"]},
                "case_id": notice.case_id,
                "expected_revision": revision,
                **extra,
            },
        )
        command = assignment_notice_from_record(stored.record)
        result = await processor.apply(command, at=command.accepted_at)
    assert result["state"] == "approved"
    assert result["case_id"] == case_id
    snapshot = await core.read_state(f"human_assignment:case:{case_id}")
    assert len(snapshot["command_receipts"]) == 3
    assert not snapshot["effect_receipts"]
    with psycopg.connect(_role(database, "fdai_core")) as connection:
        assert connection.execute("SELECT count(*) FROM audit_log").fetchone()[0] >= 3


async def test_core_reads_redacted_operator_goals_but_cannot_modify_them(database):
    goal = {
        "goal_id": "goal:example",
        "agent_name": "Muninn",
        "scope_ref": "scope:platform",
        "prompt_ref": "prompt:runbook",
        "priority": 50,
        "state": "ready_for_review",
        "revision": 2,
        "subject_ref": "private-subject",
        "raw_answer": "Private answer must not cross the port.",
        "evidence": [
            {
                "evidence_ref": "doc:example:v1",
                "digest": "a" * 64,
                "kind": "document_span",
                "private": "private-evidence",
            }
        ],
    }
    with psycopg.connect(_role(database, "fdai_operator")) as connection:
        connection.execute(
            "INSERT INTO state_kv(key,value) VALUES ('operator-handover-goal:example',%s)",
            (Jsonb(goal),),
        )
    reader = PostgresHandoverGoalReader(PostgresStateStoreConfig(dsn=_role(database, "fdai_core")))
    rows, total = await reader.read_page(limit=5, offset=0)
    assert total == 1
    assert rows[0]["goal_id"] == goal["goal_id"]
    assert "private" not in str(rows).lower()
    with psycopg.connect(_role(database, "fdai_core")) as connection:
        with pytest.raises(psycopg.errors.RaiseException, match="only Operator"):
            connection.execute(
                "UPDATE state_kv SET value='{}' WHERE key='operator-handover-goal:example'"
            )


def _run_migration(connection, path, operation):
    def execute(statement):
        cursor = connection.execute(str(statement))
        return SimpleNamespace(scalar_one=lambda: cursor.fetchone()[0])

    migration = runpy.run_path(str(path))
    with (
        patch("alembic.op.get_bind", return_value=SimpleNamespace(execute=execute)),
        patch("alembic.op.execute", side_effect=connection.execute),
    ):
        migration[operation]()


def test_empty_migration_can_rollback_and_upgrade_without_changing_service_owners(database):
    with psycopg.connect(database) as connection:
        _run_migration(connection, MIGRATION, "downgrade")
        _run_migration(connection, CORE_MIGRATION, "downgrade")
        _run_migration(connection, CORE_MIGRATION, "upgrade")
        _run_migration(connection, MIGRATION, "upgrade")
        row = connection.execute(
            "SELECT has_table_privilege('fdai_operator','operator_assignment_receipt','INSERT'), "
            "has_table_privilege('fdai_core','operator_assignment_receipt','INSERT')"
        ).fetchone()
        assert row == (True, False)


async def test_schema_rollback_cannot_delete_retained_authenticated_requests(database):
    _store, _stored, notice = await _create(database)
    with psycopg.connect(database) as connection:
        with pytest.raises(RuntimeError, match="preserved"):
            _run_migration(connection, CORE_MIGRATION, "downgrade")
        assert (
            connection.execute(
                "SELECT count(*) FROM operator_assignment_receipt WHERE proposal_ref=%s",
                (notice.proposal_ref,),
            ).fetchone()[0]
            == 1
        )


def test_core_receipt_schema_does_not_require_operator_role_to_exist(database):
    with psycopg.connect(database) as connection:
        try:
            _run_migration(connection, CORE_MIGRATION, "downgrade")
            # This disposable cluster has no runtime users. Roll back the temporary role
            # rename and schema together, even when migration execution fails.
            connection.execute("ALTER ROLE fdai_operator RENAME TO fdai_operator_not_created")
            assert (
                connection.execute(
                    "SELECT count(*) FROM pg_roles WHERE rolname='fdai_operator'"
                ).fetchone()[0]
                == 0
            )
            _run_migration(connection, CORE_MIGRATION, "upgrade")
            assert (
                connection.execute(
                    "SELECT has_table_privilege('fdai_core','operator_assignment_receipt','SELECT')"
                ).fetchone()[0]
                is True
            )
        finally:
            connection.rollback()
