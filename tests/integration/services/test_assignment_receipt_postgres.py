"""Real PostgreSQL transaction and service-role checks on a disposable local database."""

from __future__ import annotations

import asyncio
import os
import runpy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from fdai.core.human_assignment.model import (
    AssignmentCase,
    AssignmentIntent,
    AssignmentState,
    DutyBinding,
    EffectKind,
    EffectReceipt,
    ProviderSubject,
)
from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.core.human_assignment.request_processor import AssignmentRequestProcessor
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_assignment_receipts import PostgresAssignmentReceiptReader
from fdai.delivery.persistence.postgres_handover_admission import PostgresHandoverSourceReader
from fdai.delivery.persistence.postgres_handover_goals import PostgresHandoverGoalReader
from fdai_operator_service.assignment_notice import assignment_notice_from_record
from fdai_operator_service.families.conversation.contracts import (
    ConversationProposal,
    PrincipalScope,
)
from fdai_operator_service.families.iam.contracts import AssignmentCreateCommand, IamPrincipal
from fdai_operator_service.families.iam.errors import IamConflictError
from fdai_operator_service.families.iam.handover_contribution import (
    PostgresHandoverContributionGuard,
)
from fdai_operator_service.families.iam.handover_session_budget import HandoverSessionBudget
from fdai_operator_service.postgres_assignment_outbox import PostgresAssignmentOutbox
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_operator_service.postgres_iam import PostgresIamAdapters, _command_payload
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.handover_knowledge import notice_for_source
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
KNOWLEDGE_MIGRATION = ROOT / (
    "service-migrations/branches/core-control-plane/versions/20260914_core_handover_admission.py"
)
OPERATOR_DOCUMENT_MIGRATION = ROOT / (
    "service-migrations/branches/operator-service/versions/20260905_operator_handover_document_read.py"
)
REVIEWER_MIGRATION = ROOT / (
    "service-migrations/branches/operator-service/versions/20260914_operator_handover_admission.py"
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
    for path in (
        CORE_MIGRATION,
        MIGRATION,
        KNOWLEDGE_MIGRATION,
        OPERATOR_DOCUMENT_MIGRATION,
        REVIEWER_MIGRATION,
    ):
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
                    CREATE TABLE document_version (
                        document_id UUID NOT NULL, version_id UUID PRIMARY KEY,
                        state TEXT NOT NULL, active BOOLEAN NOT NULL, payload JSONB NOT NULL);
                    """
                )
                for statement in statements:
                    connection.execute(statement)
            yield dsn
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _role(dsn, role):
    return make_conninfo(dsn, options=f"-c role={role}")


async def test_legacy_grant_replay_keeps_its_original_payload_digest(database):
    operator = PostgresFamilyStore(
        config=PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    )
    command = AssignmentCreateCommand(
        principal=IamPrincipal("human:owner", frozenset({OperatorRole.OWNER})),
        idempotency_key="legacy-grant-replay",
        subject_provider="entra",
        subject_id="human:subject",
        requested_role=OperatorRole.READER,
        duty_bindings=({"agent_name": "Thor", "duty": "backup", "scope_ref": "scope:platform"},),
        goal_refs=(),
        justification="Synthetic replay of a grant recorded before revocation support.",
    )
    legacy = _command_payload(command)
    legacy.pop("revocation", None)
    first = await operator.append_proposal(
        family="iam",
        operation="assignments.create",
        principal_id=command.principal.oid,
        idempotency_key=command.idempotency_key,
        payload=legacy,
    )
    replay = await PostgresIamAdapters(operator).create_case(command)
    assert replay["case_id"] == first.record["proposal_id"]
    assert "revocation" not in first.record["payload"]


async def test_real_postgres_budget_serializes_concurrent_turns_and_survives_restart(database):
    config = PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    now = datetime(2026, 9, 14, tzinfo=UTC)
    proposals = [
        ConversationProposal(
            operation="chat.stream",
            scope=PrincipalScope("human:subject", frozenset({"Reader"})),
            idempotency_key=f"turn-{index}",
            body={"session_id": "session-one", "prompt": f"Synthetic request {index}."},
        )
        for index in range(4)
    ]
    results = await asyncio.gather(
        *(
            HandoverSessionBudget(PostgresFamilyStore(config=config)).claim(
                proposal,
                goal_id="goal:test",
                now=now,
            )
            for proposal in proposals
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, str) for result in results) == 3
    assert sum(isinstance(result, IamConflictError) for result in results) == 1
    winner = next(index for index, result in enumerate(results) if isinstance(result, str))
    assert (
        await HandoverSessionBudget(PostgresFamilyStore(config=config)).claim(
            proposals[winner],
            goal_id="goal:test",
            now=now,
        )
        == results[winner]
    )


async def test_operator_reads_core_revocation_hold_without_obtaining_write_authority(database):
    core = PostgresStateStore(config=PostgresStateStoreConfig(dsn=_role(database, "fdai_core")))
    value = {
        "intent": {
            "subject": {"subject_id": "human:subject"},
            "duty_bindings": [{"agent_name": "Muninn"}],
        },
        "state": "degraded",
        "revocation_case_id": "removal",
    }
    guard = PostgresHandoverContributionGuard(_role(database, "fdai_operator"))
    await core.write_state("humanXassignment:case:wrong-namespace", value)
    assert await guard.may_contribute(subject_ref="human:subject", agent_name="Muninn")
    await core.write_state("human_assignment:case:original", value)
    assert not await guard.may_contribute(subject_ref="human:subject", agent_name="Muninn")
    assert await guard.may_contribute(subject_ref="human:other", agent_name="Muninn")
    assert await guard.may_contribute(subject_ref="human:subject", agent_name="Thor")


async def test_core_document_admission_is_source_bound_boolean_only_and_current(database):
    document_id, version_id = uuid4(), uuid4()
    reference = f"doc:{document_id}:{version_id}"
    goal = {
        "goal_id": "goal:sql",
        "revision": 1,
        "state": "ready_for_review",
        "subject_ref": "human:subject",
        "evidence": [{"evidence_ref": reference, "digest": "a" * 64}],
    }
    document = {
        "uploader_id": "human:subject",
        "source_sha256": "a" * 64,
        "available": True,
        "disposition": "governed_knowledge",
        "index_state": "active",
        "retention_state": "live",
    }
    with psycopg.connect(_role(database, "fdai_operator")) as operator:
        operator.execute(
            "INSERT INTO state_kv (key, value) VALUES (%s, %s)",
            ("operator-handover-goal:goal:sql", Jsonb(goal)),
        )
    with psycopg.connect(database) as admin:
        admin.execute(
            "INSERT INTO document_version VALUES (%s, %s, 'ready', true, %s)",
            (document_id, version_id, Jsonb(document)),
        )
    reader = PostgresHandoverSourceReader(
        PostgresStateStoreConfig(dsn=_role(database, "fdai_core"))
    )
    notice = notice_for_source(goal, source="operator", at=datetime.now(UTC))
    assert await reader.read(notice) == goal
    assert await reader.document_admitted(notice, evidence_ref=reference, digest="a" * 64)
    assert not await reader.document_admitted(notice, evidence_ref=reference, digest="b" * 64)
    assert not await reader.document_admitted(
        notice.model_copy(update={"goal_revision": 2}),
        evidence_ref=reference,
        digest="a" * 64,
    )
    for role in ("fdai_core", "fdai_operator"):
        with psycopg.connect(_role(database, role)) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT payload FROM document_version")
    with psycopg.connect(_role(database, "fdai_operator")) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT fdai_verify_handover_source_document(%s, 1, %s, %s, %s)",
                (notice.source_key, document_id, version_id, "a" * 64),
            )
    for field, changed in (
        ("available", False),
        ("retention_state", "purged"),
        ("index_state", "tombstoned"),
        ("uploader_id", "human:other"),
    ):
        with psycopg.connect(database) as admin:
            admin.execute(
                "UPDATE document_version SET payload = %s",
                (Jsonb({**document, field: changed}),),
            )
        assert not await reader.document_admitted(notice, evidence_ref=reference, digest="a" * 64)
    wrong_role = PostgresHandoverSourceReader(
        PostgresStateStoreConfig(dsn=_role(database, "fdai_operator"))
    )
    with pytest.raises(PermissionError):
        await wrong_role.read(notice)


async def _contribution_fixture(database, source):
    now = datetime(2026, 9, 14, tzinfo=UTC)
    config = PostgresStateStoreConfig(dsn=_role(database, "fdai_core"))
    core = PostgresStateStore(config=config)
    reader = PostgresHandoverSourceReader(config)
    active = AssignmentCase(
        case_id="grant-new",
        intent=AssignmentIntent(
            idempotency_key="new-grant",
            subject=ProviderSubject("entra", "human:subject"),
            requested_role=Role.READER,
            duty_bindings=(DutyBinding("Muninn", Duty.PRIMARY, "scope:platform"),),
            goal_refs=(),
            requester_ref="human:owner",
            justification="Synthetic contribution check.",
        ),
        state=AssignmentState.ACTIVE,
        effect_receipts=tuple(
            EffectReceipt(kind, f"effect:{kind.value}", "a" * 64, now) for kind in EffectKind
        ),
    )
    goal = {
        "goal_id": "goal:contribution",
        "revision": 1,
        "state": "ready_for_review",
        "subject_ref": "human:subject",
        "agent_name": "Muninn",
        "scope_ref": "scope:platform",
        "assignment_case_id": active.case_id,
        "source_revision": "ownership:1",
        "evidence": [],
    }
    notice = notice_for_source(goal, source=source, at=now)
    writer = "fdai_core" if source == "core" else "fdai_operator"
    with psycopg.connect(_role(database, writer)) as connection:
        connection.execute(
            "INSERT INTO state_kv (key,value) VALUES (%s,%s)", (notice.source_key, Jsonb(goal))
        )
    projection = {
        "_revision": "ownership:1",
        "map": {
            "agents": [
                {
                    "name": "Muninn",
                    "stewards": [
                        {"kind": "user", "id": "human:subject", "responsibility": "accountable"}
                    ],
                }
            ]
        },
    }
    await core.write_state("operator-projection:operations:stewardship.coverage", projection)
    return core, reader, notice, active


@pytest.mark.parametrize("source", ["core", "operator"])
async def test_source_contribution_requires_exact_notice_and_current_assignment(database, source):
    core, reader, notice, active = await _contribution_fixture(database, source)
    if source == "core":
        assert not await reader.contribution_current(notice)
    await core.write_state("human_assignment:case:grant-new", active.to_dict())
    assert await reader.contribution_current(notice)
    assert not await reader.contribution_current(notice.model_copy(update={"goal_revision": 2}))
    assert not await reader.contribution_current(
        notice.model_copy(update={"source_digest": "b" * 64})
    )


@pytest.mark.parametrize("source", ["core", "operator"])
async def test_closed_removal_does_not_block_a_separately_active_new_assignment(database, source):
    core, reader, notice, active = await _contribution_fixture(database, source)
    removed = replace(
        active,
        case_id="grant-old",
        state=AssignmentState.SUPERSEDED,
        revocation_case_id="removal",
        superseded_by="removal",
    )
    await core.write_state("human_assignment:case:grant-old", removed.to_dict())
    assert not await reader.contribution_current(notice)
    await core.write_state("human_assignment:case:grant-new", active.to_dict())
    assert await reader.contribution_current(notice)
    ongoing = replace(removed, state=AssignmentState.DEGRADED, superseded_by=None)
    await core.write_state("human_assignment:case:grant-old", ongoing.to_dict())
    assert not await reader.contribution_current(notice)


async def test_operator_source_requires_exact_current_ownership_revision(database):
    core, reader, notice, _active = await _contribution_fixture(database, "operator")
    key = "operator-projection:operations:stewardship.coverage"
    assert await reader.contribution_current(notice)
    await core.write_state(key, {"_revision": "ownership:2", "map": {"agents": []}})
    assert not await reader.contribution_current(notice)
    await core.write_state(key, {"_revision": "ownership:1", "map": {"agents": []}})
    assert not await reader.contribution_current(notice)


async def test_contribution_keeps_case_prefix_and_scope_exact(database):
    core, reader, notice, active = await _contribution_fixture(database, "core")
    await core.write_state("human_assignment:case:grant-new", active.to_dict())
    held = replace(
        active, case_id="grant-old", state=AssignmentState.DEGRADED, revocation_case_id="removal"
    )
    await core.write_state("humanXassignment:case:grant-old", held.to_dict())
    assert await reader.contribution_current(notice)
    held = replace(
        held,
        intent=replace(
            held.intent, duty_bindings=(DutyBinding("Muninn", Duty.PRIMARY, "scope:other"),)
        ),
    )
    await core.write_state("human_assignment:case:grant-old", held.to_dict())
    assert await reader.contribution_current(notice)


async def test_contribution_refuses_truncated_case_evidence(database):
    core, reader, notice, active = await _contribution_fixture(database, "core")
    for index in range(101):
        await core.write_state(
            f"human_assignment:case:grant-{index}",
            replace(active, case_id=f"grant-{index}").to_dict(),
        )
    with pytest.raises(ValueError, match="read bound"):
        await reader.contribution_current(notice)


async def test_operator_global_map_cannot_prove_scoped_contribution(database):
    _core, reader, notice, _active = await _contribution_fixture(database, "operator")
    goal = dict(await reader.read(notice))
    goal["scope_ref"] = "scope:other"
    with psycopg.connect(_role(database, "fdai_operator")) as connection:
        connection.execute(
            "UPDATE state_kv SET value=%s WHERE key=%s", (Jsonb(goal), notice.source_key)
        )
    scoped_notice = notice_for_source(goal, source="operator", at=datetime(2026, 9, 14, tzinfo=UTC))
    assert not await reader.contribution_current(scoped_notice)


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


@pytest.mark.parametrize("removal", [False, True])
async def test_real_operator_receipt_and_core_case_audit_transaction(database, removal):
    operator = PostgresFamilyStore(
        config=PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    )
    core_config = PostgresStateStoreConfig(dsn=_role(database, "fdai_core"))
    core = PostgresStateStore(config=core_config)
    processor = AssignmentRequestProcessor(
        intake=AssignmentRequestIntake(
            receipts=PostgresAssignmentReceiptReader(core_config),
            store=core,
        ),
        cases=AssignmentCaseService(core),
    )
    if removal:
        original = AssignmentCase(
            case_id="original-grant",
            intent=AssignmentIntent(
                idempotency_key="original-grant",
                subject=ProviderSubject("entra", "human:subject"),
                requested_role=Role.READER,
                duty_bindings=(DutyBinding("Thor", Duty.BACKUP, "scope:platform"),),
                goal_refs=(),
                requester_ref="human:original-requester",
                justification="Synthetic existing assignment for the SQL role boundary.",
            ),
            state=AssignmentState.ACTIVE,
            revision=7,
            effect_receipts=tuple(
                EffectReceipt(
                    kind,
                    f"synthetic:{kind.value}",
                    "a" * 64,
                    datetime(2026, 9, 14, tzinfo=UTC),
                )
                for kind in (EffectKind.OWNERSHIP, EffectKind.IAM)
            ),
        )
        await core.write_state("human_assignment:case:original-grant", original.to_dict())
    revocation = {
        "case_id": "original-grant",
        "revision": 7,
        "replacement_revisions": {"primary": 7, "backup": 7},
    }
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
            **({"revocation": revocation} if removal else {}),
        },
    )
    notice = assignment_notice_from_record(creation.record)
    with psycopg.connect(database) as connection:
        connection.execute("ALTER TABLE audit_log ADD CONSTRAINT test_audit_failure CHECK (FALSE)")
    with pytest.raises(psycopg.errors.CheckViolation):
        await processor.apply(notice, at=notice.accepted_at)
    assert len(await core.read_states("human_assignment:case:", limit=5)) == int(removal)
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
    if removal:
        assert result["schema_version"] == notice.schema_version == "1.1.0"
        assert snapshot["intent"]["revocation"] == revocation
        assert AssignmentCase.from_dict(snapshot).intent.revocation is not None
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
