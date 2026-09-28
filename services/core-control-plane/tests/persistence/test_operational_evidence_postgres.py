"""Loopback PostgreSQL proof of the insert-only operational evidence store and its roles.

Runs only against a loopback validation instance named by ``FDAI_OPERATIONAL_EVIDENCE_TEST_DSN``.
Each test creates and drops its own database; cluster-level role memberships it grants are
revoked before it returns.
"""

from __future__ import annotations

import itertools
import os
import runpy
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from fdai.core.operational_evidence.issuance import (
    OperationalEvidenceVerifierEngine,
    VerifierIdentity,
)
from fdai.core.operational_evidence.readback.test_context_command import (
    OperatorTestContextCommandReadback,
)
from fdai.delivery.operational_evidence_admission import OperationalEvidenceAdmissionProvider
from fdai.delivery.persistence.postgres_operational_evidence import (
    VERIFIER_ROLE,
    PostgresOperationalEvidenceConfig,
    PostgresOperationalProofReader,
    PostgresOperationalProofWriter,
)
from fdai.delivery.persistence.postgres_operational_evidence_grants import (
    read_proof_store_grants,
)
from fdai.delivery.persistence.postgres_operational_evidence_sources import (
    AUDIT_ROW_BOUND,
    MAX_AUDIT_DIGESTS,
    TARGET_ROW_BOUND,
    PostgresTestContextEvidenceSources,
)
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceLocator,
    OperationalEvidenceLookup,
    OperationalEvidenceRejectionRecord,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from tests.core.operational_evidence.support import (
    NOW,
    POLICY,
    REQUESTER,
    REQUESTER_GROUP,
    SCOPE,
    OperatorOutbox,
    anchors,
    command_from_row,
    history,
)

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[4]
_VERSIONS = ROOT / "service-migrations/branches/core-control-plane/versions"
MIGRATION = _VERSIONS / "20260928_core_operational_evidence.py"
SOURCE_FUNCTIONS = _VERSIONS / "20260929_core_operational_evidence_source_functions.py"
_BASE_SCHEMA = """
CREATE TABLE state_kv (
    key TEXT PRIMARY KEY, value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE audit_log (
    seq BIGSERIAL PRIMARY KEY, action_kind TEXT NOT NULL, entry JSONB NOT NULL,
    previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL);
GRANT USAGE ON SCHEMA public TO fdai_core, fdai_operator;
GRANT SELECT, INSERT, UPDATE ON state_kv TO fdai_operator;
GRANT SELECT, INSERT, UPDATE, DELETE ON state_kv, audit_log TO fdai_core;
"""


@pytest.fixture
def database() -> Iterator[str]:
    source = os.environ.get("FDAI_OPERATIONAL_EVIDENCE_TEST_DSN")
    if not source:
        pytest.skip("FDAI_OPERATIONAL_EVIDENCE_TEST_DSN is unset")
    source = source.replace("postgresql+psycopg://", "postgresql://", 1)
    if conninfo_to_dict(source).get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("operational evidence database test requires a loopback-only fixture")
    statements = _statements(MIGRATION, "upgrade") + _statements(SOURCE_FUNCTIONS, "upgrade")
    name = "fdai_operational_evidence_" + uuid4().hex[:12]
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
                connection.execute(_BASE_SCHEMA)
                for statement in statements:
                    connection.execute(statement)
            yield dsn
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _statements(migration: Path, step: str) -> list[str]:
    """Capture one migration step's SQL without an Alembic context."""
    statements: list[str] = []
    module = runpy.run_path(str(migration))
    with patch("alembic.op.execute", side_effect=statements.append):
        module[step]()
    return statements


def _as(dsn: str, role: str) -> str:
    return make_conninfo(dsn, options=f"-c role={role}")


def _rejection(attempt: str = "a" * 32) -> OperationalEvidenceRejectionRecord:
    return OperationalEvidenceRejectionRecord.create(
        attempt_id=attempt,
        lookup_digest="sha256:" + "1" * 64,
        purpose_id="operator-test-context-command",
        rejection_class="partial",  # type: ignore[arg-type]
        reason_codes=("source_record_missing",),
        trust_registry_pin="sha256:" + "2" * 64,
        grant_registry_pin="sha256:" + "3" * 64,
        verifier_id="operational-evidence-verifier",
        verifier_version="1.0.0",
        recorded_at=NOW,
    )


def _insert_rejection(
    connection: psycopg.Connection, record: OperationalEvidenceRejectionRecord
) -> None:
    connection.execute(
        "INSERT INTO operational_evidence_rejection (record_key, pins_digest, lookup_digest, "
        "purpose_id, attempt_id, rejection_class, record_digest, record, recorded_at, "
        "valid_until) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            "4" * 64 + "/" + "1" * 64 + "/0000000000001-" + record.record_digest[7:],
            "sha256:" + "4" * 64,
            record.lookup_digest,
            record.purpose_id,
            record.attempt_id,
            record.rejection_class.value,
            record.record_digest,
            Jsonb(record.model_dump(mode="json")),
            record.recorded_at,
            record.valid_until,
        ),
    )


def test_only_the_verifier_role_writes_and_nobody_mutates_proofs(database: str) -> None:
    with psycopg.connect(_as(database, "fdai_core")) as core:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _insert_rejection(core, _rejection())
    with psycopg.connect(database) as owner:
        with pytest.raises(psycopg.errors.RaiseException, match="only the operational evidence"):
            _insert_rejection(owner, _rejection())
    with psycopg.connect(_as(database, VERIFIER_ROLE)) as verifier:
        _insert_rejection(verifier, _rejection())
    for statement in (
        "UPDATE operational_evidence_rejection SET purpose_id = purpose_id",
        "DELETE FROM operational_evidence_rejection",
    ):
        with psycopg.connect(_as(database, VERIFIER_ROLE)) as verifier:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                verifier.execute(statement)
        with psycopg.connect(database) as owner:
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                owner.execute(statement)
    with psycopg.connect(database) as owner:
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            owner.execute("TRUNCATE operational_evidence_rejection")
    with psycopg.connect(_as(database, "fdai_core")) as core:
        assert core.execute("SELECT count(*) FROM operational_evidence_rejection").fetchone() == (
            1,
        )
    with psycopg.connect(_as(database, "fdai_operator")) as operator:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            operator.execute("SELECT count(*) FROM operational_evidence_rejection")
    for statement in ("SELECT count(*) FROM state_kv", "INSERT INTO state_kv VALUES ('k', '{}')"):
        with psycopg.connect(_as(database, VERIFIER_ROLE)) as verifier:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                verifier.execute(statement)


def _operator_row(outbox: OperatorOutbox, **values: object) -> tuple[str, dict[str, object]]:
    row = outbox.add(
        "propose",
        principal=REQUESTER,
        group=REQUESTER_GROUP,
        roles=("Contributor",),
        expected_revision=0,
        **values,  # type: ignore[arg-type]
    )
    value = {
        **row.record,
        "dispatch_status": "pending",
        "mode": "shadow",
        "authentication_receipt": row.authentication_receipt,
    }
    return row.key, value


def test_operator_command_rows_are_operator_inserted_and_request_immutable(database: str) -> None:
    key, value = _operator_row(OperatorOutbox(), accepted_at=NOW - timedelta(minutes=1))
    with psycopg.connect(_as(database, "fdai_core")) as core:
        with pytest.raises(psycopg.errors.RaiseException, match="only Operator"):
            core.execute("INSERT INTO state_kv (key, value) VALUES (%s, %s)", (key, Jsonb(value)))
    with psycopg.connect(_as(database, "fdai_operator")) as operator:
        operator.execute("INSERT INTO state_kv (key, value) VALUES (%s, %s)", (key, Jsonb(value)))
        operator.execute(
            "UPDATE state_kv SET value = jsonb_set(value, '{dispatch_status}', '\"published\"') "
            "WHERE key = %s",
            (key,),
        )
    for field in ("principal_id", "authentication_receipt", "payload"):
        with psycopg.connect(_as(database, "fdai_operator")) as operator:
            with pytest.raises(psycopg.errors.RaiseException, match="request is immutable"):
                operator.execute(
                    "UPDATE state_kv SET value = jsonb_set(value, %s, '\"forged\"') WHERE key = %s",
                    ("{" + field + "}", key),
                )
    with psycopg.connect(_as(database, "fdai_core")) as core:
        with pytest.raises(psycopg.errors.RaiseException, match="source identity is immutable"):
            core.execute("DELETE FROM state_kv WHERE key = %s", (key,))
    with psycopg.connect(_as(database, "fdai_core")) as core:
        core.execute(
            "INSERT INTO state_kv (key, value) VALUES (%s, %s)",
            ("operator-proposal:conversation:" + "0" * 64, Jsonb({"operation": "chat.exchange"})),
        )
    with psycopg.connect(_as(database, "fdai_core")) as core:
        with pytest.raises(psycopg.errors.RaiseException, match="only be inserted by Operator"):
            core.execute(
                "UPDATE state_kv SET value = jsonb_set(value, '{operation}', "
                "'\"test-context.propose\"') WHERE key = %s",
                ("operator-proposal:conversation:" + "0" * 64,),
            )
    with psycopg.connect(_as(database, VERIFIER_ROLE)) as verifier:
        row = verifier.execute(
            "SELECT dispatch_status, authentication_receipt, record "
            "FROM fdai_operational_evidence_commands_for_key(%s)",
            (value["idempotency_key"],),
        ).fetchone()
    assert row is not None and row[0] == "published"
    assert row[1]["token_retained"] is False
    assert set(row[2]) == {
        "family",
        "operation",
        "principal_id",
        "idempotency_key",
        "payload",
        "kind",
        "proposal_id",
        "request_digest",
        "accepted_at",
    }


async def test_grants_readback_reports_self_verified_for_foreign_writers(database: str) -> None:
    config = PostgresOperationalEvidenceConfig(
        dsn=_as(database, VERIFIER_ROLE), expected_role=VERIFIER_ROLE
    )
    assert (await read_proof_store_grants(config)).self_verified_reasons() == ()
    with psycopg.connect(database, autocommit=True) as admin:
        admin.execute("GRANT INSERT ON operational_evidence_admission TO fdai_core")
        assert (
            "foreign_insert_grant"
            in (await read_proof_store_grants(config)).self_verified_reasons()
        )
        admin.execute("REVOKE INSERT ON operational_evidence_admission FROM fdai_core")
        admin.execute(
            "ALTER TABLE operational_evidence_admission "
            "DISABLE TRIGGER operational_evidence_admission_writer"
        )
        assert (
            "immutability_guard_missing"
            in (await read_proof_store_grants(config)).self_verified_reasons()
        )
        admin.execute(
            "ALTER TABLE operational_evidence_admission "
            "ENABLE TRIGGER operational_evidence_admission_writer"
        )
        admin.execute("GRANT fdai_operational_evidence_verifier TO fdai_core")
        try:
            reasons = (await read_proof_store_grants(config)).self_verified_reasons()
        finally:
            admin.execute("REVOKE fdai_operational_evidence_verifier FROM fdai_core")
    assert {"consumer_holds_writer_role", "foreign_writer_membership"} <= set(reasons)
    assert (await read_proof_store_grants(config)).self_verified_reasons() == ()


def _request(command: dict[str, object], key: str) -> OperationalEvidenceIssuanceRequest:
    return OperationalEvidenceIssuanceRequest(
        attempt_id="b" * 32,
        lookup=OperationalEvidenceLookup(
            evidence_digest=content_digest(command),
            scope_digest="sha256:" + SCOPE,
            purpose_id="operator-test-context-command",
            source_revision=POLICY,
        ),
        locator=OperationalEvidenceLocator(
            purpose_id="operator-test-context-command", coordinates={"idempotency_key": key}
        ),
        producer_id="core-control-plane",
        producer_version="1.0.0",
        requested_at=NOW,
    )


async def test_real_roles_issue_admit_and_replay_under_an_advancing_clock(database: str) -> None:
    outbox = OperatorOutbox()
    key, value = _operator_row(outbox, accepted_at=NOW - timedelta(minutes=1))
    stale_key, stale_value = _operator_row(
        outbox, accepted_at=NOW - timedelta(minutes=20), key="context-stale"
    )
    with psycopg.connect(_as(database, "fdai_operator")) as operator:
        for item_key, item_value in ((key, value), (stale_key, stale_value)):
            operator.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s)", (item_key, Jsonb(item_value))
            )
    verifier = PostgresOperationalEvidenceConfig(
        dsn=_as(database, VERIFIER_ROLE), expected_role=VERIFIER_ROLE
    )
    registry = history()
    ticks = itertools.count()
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=lambda: registry,
        anchors=anchors(),
        readbacks=(
            OperatorTestContextCommandReadback(
                commands=PostgresTestContextEvidenceSources(verifier)
            ),
        ),
        writer=PostgresOperationalProofWriter(verifier),
        lineage=PostgresOperationalProofReader(verifier),
        clock=lambda: NOW + timedelta(seconds=next(ticks)),
    )
    command = command_from_row(outbox.rows[0]).model_dump(mode="json")
    request = _request(command, str(value["idempotency_key"]))
    first = await engine.issue(request, caller_principal="fdai_core")
    replay = await engine.issue(request, caller_principal="fdai_core")
    assert first.status is OperationalEvidenceIssuanceStatus.ISSUED
    assert replay == first
    consumer = OperationalEvidenceAdmissionProvider(
        reader=PostgresOperationalProofReader(
            PostgresOperationalEvidenceConfig(
                dsn=_as(database, "fdai_core"), expected_role="fdai_core"
            )
        ),
        history=lambda: registry,
        anchors=anchors(),
        verifier_id="operational-evidence-verifier",
        clock=lambda: NOW + timedelta(minutes=1),
    )
    admission = await consumer.admit(**request.lookup.model_dump(mode="json"))
    assert admission is not None and admission.execution_authority is False
    stale_command = command_from_row(outbox.rows[1]).model_dump(mode="json")
    stale_request = _request(stale_command, "context-stale").model_copy(
        update={"attempt_id": "c" * 32}
    )
    rejected = await engine.issue(stale_request, caller_principal="fdai_core")
    assert rejected.status is OperationalEvidenceIssuanceStatus.REJECTED
    record = await consumer.outcome(rejected, lookup=stale_request.lookup)
    assert record is not None and record.rejection_class.value == "stale"
    with psycopg.connect(_as(database, "fdai_core")) as core:
        counts = core.execute(
            "SELECT (SELECT count(*) FROM operational_evidence_admission), "
            "(SELECT count(*) FROM operational_evidence_readback), "
            "(SELECT count(*) FROM operational_evidence_bundle), "
            "(SELECT count(*) FROM operational_evidence_authentication), "
            "(SELECT count(*) FROM operational_evidence_rejection)"
        ).fetchone()
    assert counts == (1, 1, 1, 1, 1)


class _RacingWriter(PostgresOperationalProofWriter):
    """A writer whose replay pre-check always misses, as when a concurrent attempt commits later."""

    async def attempt_outcome(self, attempt_id: str) -> None:
        return None


async def test_writer_keeps_the_stored_outcome_when_a_concurrent_attempt_won(
    database: str,
) -> None:
    outbox = OperatorOutbox()
    key, value = _operator_row(outbox, accepted_at=NOW - timedelta(minutes=1))
    stale_key, stale_value = _operator_row(
        outbox, accepted_at=NOW - timedelta(minutes=20), key="context-stale"
    )
    with psycopg.connect(_as(database, "fdai_operator")) as operator:
        for item_key, item_value in ((key, value), (stale_key, stale_value)):
            operator.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s)", (item_key, Jsonb(item_value))
            )
    verifier = PostgresOperationalEvidenceConfig(
        dsn=_as(database, VERIFIER_ROLE), expected_role=VERIFIER_ROLE
    )
    registry = history()
    ticks = itertools.count()
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=lambda: registry,
        anchors=anchors(),
        readbacks=(
            OperatorTestContextCommandReadback(
                commands=PostgresTestContextEvidenceSources(verifier)
            ),
        ),
        writer=_RacingWriter(verifier),
        lineage=PostgresOperationalProofReader(verifier),
        clock=lambda: NOW + timedelta(seconds=next(ticks)),
    )
    request = _request(
        command_from_row(outbox.rows[0]).model_dump(mode="json"), str(value["idempotency_key"])
    )
    stale_request = _request(
        command_from_row(outbox.rows[1]).model_dump(mode="json"), "context-stale"
    ).model_copy(update={"attempt_id": "c" * 32})
    first = await engine.issue(request, caller_principal="fdai_core")
    raced = await engine.issue(request, caller_principal="fdai_core")
    rejected = await engine.issue(stale_request, caller_principal="fdai_core")
    raced_rejection = await engine.issue(stale_request, caller_principal="fdai_core")
    assert first.status is OperationalEvidenceIssuanceStatus.ISSUED
    assert raced == first
    assert rejected.status is OperationalEvidenceIssuanceStatus.REJECTED
    assert raced_rejection == rejected
    with psycopg.connect(_as(database, "fdai_core")) as core:
        counts = core.execute(
            "SELECT (SELECT count(*) FROM operational_evidence_admission), "
            "(SELECT count(*) FROM operational_evidence_rejection)"
        ).fetchone()
    assert counts == (1, 1)


def test_source_views_are_security_barriers_that_leak_no_other_rows(database: str) -> None:
    key, value = _operator_row(OperatorOutbox(), accepted_at=NOW - timedelta(minutes=1))
    with psycopg.connect(_as(database, "fdai_operator")) as operator:
        operator.execute("INSERT INTO state_kv (key, value) VALUES (%s, %s)", (key, Jsonb(value)))
    with psycopg.connect(database, autocommit=True) as owner:
        owner.execute(
            "INSERT INTO state_kv (key, value) VALUES ('private-row-key', '{\"secret\": 1}')"
        )
        owner.execute(
            "CREATE VIEW leaky_history AS SELECT key, value FROM public.state_kv "
            "WHERE starts_with(key, 'test-context-target:v1:')"
        )
        owner.execute(f"GRANT SELECT ON leaky_history TO {VERIFIER_ROLE}")
        barriers = owner.execute(
            "SELECT relname FROM pg_class "
            "WHERE starts_with(relname, 'operational_evidence_test_context_') "
            "AND relkind = 'v' AND 'security_barrier=true' = ANY(reloptions)"
        ).fetchall()
        explicit_temp = owner.execute(
            "SELECT count(*) FROM pg_database, aclexplode(datacl) acl "
            "WHERE datname = current_database() AND acl.grantee = %s::regrole "
            "AND acl.privilege_type = 'TEMPORARY'",
            (VERIFIER_ROLE,),
        ).fetchone()
    assert {row[0] for row in barriers} == set(_SOURCE_VIEWS)
    assert explicit_temp == (0,)
    seen: list[str] = []
    with psycopg.connect(_as(database, VERIFIER_ROLE), autocommit=True) as verifier:
        verifier.add_notice_handler(lambda notice: seen.append(str(notice.message_primary)))
        verifier.execute(
            "CREATE FUNCTION pg_temp.probe(k text) RETURNS boolean LANGUAGE plpgsql "
            "COST 0.0000001 AS $probe$ BEGIN RAISE NOTICE 'seen %', k; RETURN true; END $probe$"
        )
        verifier.execute("SELECT count(*) FROM leaky_history WHERE pg_temp.probe(key)")
        leaked = [message for message in seen if "private-row-key" in message]
        seen.clear()
        verifier.execute(
            "SELECT count(*) FROM fdai_operational_evidence_commands_for_key(%s) "
            "WHERE pg_temp.probe(key)",
            (value["idempotency_key"],),
        )
    assert leaked, "the non-barrier twin must demonstrate the probe is sensitive"
    assert seen and all("private-row-key" not in message for message in seen)
    assert any(key in message for message in seen)


_SOURCE_VIEWS = (
    "operational_evidence_test_context_audit",
    "operational_evidence_test_context_command",
    "operational_evidence_test_context_history",
)
_SOURCE_FUNCTIONS = (
    "fdai_operational_evidence_commands_for_key(text)",
    "fdai_operational_evidence_commands_for_target(text,text)",
    "fdai_operational_evidence_context_history(text)",
    "fdai_operational_evidence_transition_audit(text[])",
)


def _plan_shape(plan: object) -> list[tuple[str, object, object]]:
    """Flatten an EXPLAIN (ANALYZE, FORMAT JSON) plan into its node types and row counts."""
    nodes: list[tuple[str, object, object]] = []
    pending = [plan[0]["Plan"]] if isinstance(plan, list) else []
    while pending:
        node = pending.pop()
        assert "Relation Name" not in node, "the verifier plan must not scan a source relation"
        nodes.append((node["Node Type"], node["Plan Rows"], node["Actual Rows"]))
        pending.extend(node.get("Plans", ()))
    return nodes


def test_verifier_cannot_probe_source_keys_through_planner_statistics(database: str) -> None:
    history_key = "test-context-target:v1:" + "a" * 64
    with psycopg.connect(database, autocommit=True) as owner:
        owner.execute(
            "INSERT INTO state_kv (key, value) VALUES ('private-row-key', '{\"secret\": 1}'), "
            "(%s, '{\"revision\": 1}')",
            (history_key,),
        )
        owner.execute("ANALYZE state_kv")
        definitions = owner.execute(
            "SELECT p.oid::regprocedure::text, p.prosecdef, l.lanname, p.proconfig, "
            "has_function_privilege(%s, p.oid, 'EXECUTE'), "
            "has_function_privilege('fdai_core', p.oid, 'EXECUTE') "
            "FROM pg_proc p JOIN pg_language l ON l.oid = p.prolang "
            "WHERE p.proname LIKE 'fdai\\_operational\\_evidence\\_%%' "
            "AND p.pronamespace = 'public'::regnamespace AND p.prokind = 'f' "
            "AND p.prorettype <> 'trigger'::regtype ORDER BY 1",
            (VERIFIER_ROLE,),
        ).fetchall()
        view_reads = owner.execute(
            "SELECT bool_or(has_table_privilege(%s, relname, 'SELECT')) "
            "FROM unnest(%s::text[]) relname",
            (VERIFIER_ROLE, list(_SOURCE_VIEWS)),
        ).fetchone()
    assert [row[0] for row in definitions] == list(_SOURCE_FUNCTIONS)
    for _name, definer, language, config, verifier_may, core_may in definitions:
        assert definer is True and language == "sql"
        assert config == ["search_path=pg_catalog, pg_temp"]
        assert verifier_may is True and core_may is False
    assert view_reads == (False,)
    with psycopg.connect(_as(database, VERIFIER_ROLE), autocommit=True) as verifier:
        for relation in ("state_kv", "audit_log", *_SOURCE_VIEWS):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                verifier.execute(f"EXPLAIN SELECT 1 FROM public.{relation}")  # noqa: S608
        shapes = [
            _plan_shape(
                verifier.execute(
                    "EXPLAIN (ANALYZE, FORMAT JSON) "
                    "SELECT * FROM fdai_operational_evidence_commands_for_key(%s)",
                    (probe,),
                ).fetchone()[0]  # type: ignore[index]
            )
            for probe in ("private-row-key", "absent-row-key")
        ]
        histories = [
            verifier.execute(
                "SELECT fdai_operational_evidence_context_history(%s)", (probe,)
            ).fetchone()
            for probe in ("private-row-key", "test-context-target:v1:" + "b" * 64, history_key)
        ]
    assert shapes[0] == shapes[1]
    assert shapes[0][0][0] == "Function Scan" and shapes[0][0][2] == 0
    assert histories == [(None,), (None,), ({"revision": 1},)]


async def test_source_health_reports_each_declared_source(database: str) -> None:
    sources = PostgresTestContextEvidenceSources(
        PostgresOperationalEvidenceConfig(
            dsn=_as(database, VERIFIER_ROLE), expected_role=VERIFIER_ROLE
        )
    )
    assert await sources.source_health() == {
        "core-control-plane.test-context-store": "healthy",
        "operator-service.test-context-outbox": "healthy",
    }
    with psycopg.connect(database, autocommit=True) as owner:
        owner.execute(
            "REVOKE EXECUTE ON FUNCTION fdai_operational_evidence_context_history(TEXT) "
            f"FROM {VERIFIER_ROLE}"
        )
    assert await sources.source_health() == {
        "core-control-plane.test-context-store": "unavailable",
        "operator-service.test-context-outbox": "healthy",
    }


def test_source_function_downgrade_restores_view_reads_symmetrically(database: str) -> None:
    def verifier_access(owner: psycopg.Connection) -> tuple[object, ...]:
        row = owner.execute(
            "SELECT bool_and(has_table_privilege(%s, relname, 'SELECT')) "
            "FROM unnest(%s::text[]) relname",
            (VERIFIER_ROLE, list(_SOURCE_VIEWS)),
        ).fetchone()
        functions = owner.execute(
            "SELECT count(*) FROM unnest(%s::text[]) signature "
            "WHERE to_regprocedure(signature) IS NOT NULL",
            (list(_SOURCE_FUNCTIONS),),
        ).fetchone()
        assert row is not None and functions is not None
        return (row[0], functions[0])

    with psycopg.connect(database, autocommit=True) as owner:
        assert verifier_access(owner) == (False, 4)
        for statement in _statements(SOURCE_FUNCTIONS, "downgrade"):
            owner.execute(statement)
        assert verifier_access(owner) == (True, 0)
        for statement in _statements(SOURCE_FUNCTIONS, "upgrade"):
            owner.execute(statement)
        assert verifier_access(owner) == (False, 4)


def test_source_function_bounds_match_the_reader_bounds() -> None:
    text = SOURCE_FUNCTIONS.read_text(encoding="utf-8")
    assert f"LIMIT {TARGET_ROW_BOUND}\n" in text and f"LIMIT {AUDIT_ROW_BOUND}\n" in text
    assert f"BETWEEN 1 AND {MAX_AUDIT_DIGESTS}" in text
    assert "plpgsql" not in text.lower() and "format(" not in text
