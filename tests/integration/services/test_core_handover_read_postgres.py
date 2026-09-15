"""Real task-only Core SQL admission, current reviewers, retrieval, and role boundaries."""

from __future__ import annotations

import runpy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from fdai.core.human_assignment.goals import (
    GoalEvidence,
    HandoverGoal,
    HandoverGoalService,
    HandoverGoalState,
)
from fdai.core.human_assignment.knowledge_handover import HandoverKnowledgeAccessContext
from fdai.core.human_assignment.model import (
    AssignmentCase,
    AssignmentIntent,
    AssignmentState,
    DutyBinding,
    EffectKind,
    EffectReceipt,
    ProviderSubject,
)
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.governed_document_queries import (
    GOVERNED_DOCUMENT_FUNCTION_NAME,
    governed_document_function,
    governed_document_function_type,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty
from fdai.delivery.identity.handover_review_identity import HandoverIdentityFacts
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_core_handover_review import PostgresCoreHandoverReview
from fdai.delivery.persistence.postgres_handover_admission import PostgresHandoverSourceReader
from fdai.runtime.core_handover import CoreHandoverServices, CurrentCoreHandoverSource
from fdai.runtime.handover_document_reader import CoreHandoverDocumentReader
from fdai.shared.contracts.models import CeilingRole
from fdai_service_contracts.handover_checklist import HANDOVER_SLOTS
from fdai_service_contracts.handover_knowledge import notice_for_source
from psycopg.types.json import Jsonb

_support = runpy.run_path(str(Path(__file__).with_name("test_assignment_receipt_postgres.py")))
database = _support["database"]
_role = _support["_role"]
_run_migration = _support["_run_migration"]
_MIGRATION = _support["ROOT"] / (
    "service-migrations/branches/core-control-plane/versions/20260914_core_handover_review_read.py"
)
pytestmark = pytest.mark.integration


def _install(database):
    with psycopg.connect(database) as connection:
        connection.execute(
            "CREATE TABLE knowledge_chunk (doc_id TEXT NOT NULL, chunk_id TEXT PRIMARY KEY, "
            "text TEXT NOT NULL, source_ref TEXT NOT NULL, metadata JSONB NOT NULL)"
        )
        statements = []
        with patch("alembic.op.execute", side_effect=statements.append):
            runpy.run_path(str(_MIGRATION))["upgrade"]()
        for statement in statements:
            connection.execute(statement)


async def _ready(database):
    _install(database)
    config = PostgresStateStoreConfig(dsn=_role(database, "fdai_core"))
    store = PostgresStateStore(config=config)
    source = PostgresHandoverSourceReader(config)
    at = datetime.now(UTC)
    clock = {"at": at}
    identities = {
        person: HandoverIdentityFacts(person, roles, groups, at, at + timedelta(minutes=5))
        for person, roles, groups in (
            ("human:subject", ("Reader",), ()),
            ("human:owner", ("Owner",), ()),
            ("human:backup", ("Reader",), ("group:reader",)),
        )
    }

    async def read(person):
        return identities.get(person)

    admission = PostgresCoreHandoverReview(source, SimpleNamespace(read=read), lambda: clock["at"])
    goals = HandoverGoalService(
        store=store,
        assignments=AssignmentCaseService(store),
        evidence_admission=admission,
        review_eligibility=admission,
        clock=lambda: clock["at"],
    )
    core = CoreHandoverServices(goals, admission, source)
    assignment = AssignmentCase(
        case_id="grant:current",
        intent=AssignmentIntent(
            idempotency_key="core-handover-test",
            subject=ProviderSubject("entra", "human:subject"),
            requested_role=Role.READER,
            duty_bindings=(DutyBinding("Muninn", Duty.PRIMARY, "scope:example"),),
            requester_ref="human:requester",
            goal_refs=(),
            justification="Synthetic Core read evidence.",
        ),
        state=AssignmentState.ACTIVE,
        effect_receipts=tuple(
            EffectReceipt(kind, "effect:" + kind.value, "b" * 64, at) for kind in EffectKind
        ),
    )
    await store.write_state("human_assignment:case:" + assignment.case_id, assignment.to_dict())
    backup = replace(
        assignment,
        case_id="grant:backup",
        intent=replace(
            assignment.intent,
            subject=ProviderSubject("entra", "human:backup"),
            duty_bindings=(DutyBinding("Muninn", Duty.BACKUP, "scope:example"),),
        ),
    )
    await store.write_state("human_assignment:case:" + backup.case_id, backup.to_dict())
    document_id, version_id = uuid4(), uuid4()
    ref = f"doc:{document_id}:{version_id}"
    goal = HandoverGoal(
        goal_id=str(uuid4()),
        assignment_case_id=assignment.case_id,
        subject_ref="human:subject",
        agent_name="Muninn",
        scope_ref="scope:example",
        prompt_ref="prompt:handover",
        priority=50,
        created_at=at,
        state=HandoverGoalState.READY_FOR_REVIEW,
        evidence=tuple(
            GoalEvidence(ref, "a" * 64, "document_span", slot) for slot in HANDOVER_SLOTS
        ),
    )
    await store.write_state("handover_goal:goal:" + goal.goal_id, goal.to_dict())
    document = {
        "uploader_id": goal.subject_ref,
        "source_sha256": "a" * 64,
        "available": True,
        "disposition": "governed_knowledge",
        "index_state": "active",
        "retention_state": "live",
        "access": {
            "reference": "acl:example",
            "collection_id": "handover",
            "reader_groups": ["group:reader"],
        },
    }
    chunk = {
        "doc_id": f"governed:{document_id}:{version_id}",
        "chunk_id": "chunk:example",
        "text": "Synthetic runbook describes the rollback verification step.",
        "source_ref": f"document://{document_id}/versions/{version_id}#unit:1",
        "metadata": {
            "governed_document": "true",
            "document_id": str(document_id),
            "version_id": str(version_id),
            "collection_id": "handover",
            "access_descriptor_ref": "acl:example",
            "retention_state": "live",
            "locator": "docx/paragraph:1",
        },
    }
    with psycopg.connect(database) as admin:
        admin.execute(
            "INSERT INTO document_version VALUES (%s,%s,'ready',true,%s)",
            (document_id, version_id, Jsonb(document)),
        )
        admin.execute(
            "INSERT INTO knowledge_chunk VALUES (%s,%s,%s,%s,%s)",
            (
                chunk["doc_id"],
                chunk["chunk_id"],
                chunk["text"],
                chunk["source_ref"],
                Jsonb(chunk["metadata"]),
            ),
        )
    return SimpleNamespace(
        core=core,
        store=store,
        goal=goal,
        identities=identities,
        document=document,
        chunk=chunk,
        reference=ref,
        document_id=document_id,
        version_id=version_id,
        clock=clock,
        assignment=assignment,
        backup=backup,
    )


async def _search(fixture, **changes):
    return await fixture.core.search(
        goal_id=fixture.goal.goal_id,
        question="rollback",
        access=HandoverKnowledgeAccessContext(
            **{
                "principal_ref": "human:subject",
                "collection_id": "handover",
                "allowed_access_refs": frozenset({"acl:example"}),
                **changes,
            }
        ),
    )


async def test_real_core_source_review_and_existing_governed_function_consume_real_chunks(database):
    fixture = await _ready(database)
    chunks = await _search(fixture)
    assert len(chunks) == 1 and chunks[0].text == fixture.chunk["text"]
    assert chunks[0].source_ref == fixture.chunk["source_ref"]
    assert chunks[0].metadata["source_sha256"] == "a" * 64
    first = await fixture.core.goals.accept(
        goal_id=fixture.goal.goal_id,
        expected_revision=1,
        backup_case_id=fixture.backup.case_id,
        principal=Principal("human:backup", frozenset({Role.READER})),
        now=fixture.clock["at"],
    )
    final = await fixture.core.goals.accept(
        goal_id=first.goal_id,
        expected_revision=first.revision,
        principal=Principal("human:owner", frozenset({Role.OWNER})),
        now=fixture.clock["at"],
    )
    notice = notice_for_source(final.to_dict(), source="core", at=fixture.clock["at"])
    assert await CurrentCoreHandoverSource(fixture.core.source, fixture.core).contribution_current(
        notice
    )
    calls = []
    function = governed_document_function(
        SimpleNamespace(type_ref=lambda *args: calls.append(args)),
        reader=CoreHandoverDocumentReader(fixture.core, lambda: fixture.clock["at"]),
    )
    result = await function(
        {"query": "rollback", "evidence_mode": "required", "limit": 8},
        FunctionInvocationContext(
            caller_agent="Bragi",
            purposes=("operations-review",),
            principal_ref="human:subject",
            caller_role=CeilingRole.READER,
            principal_groups=(),
        ),
    )
    assert calls[0][1] == GOVERNED_DOCUMENT_FUNCTION_NAME
    assert governed_document_function_type().purpose_bindings == ["operations-review"]
    assert result["complete"] is False
    assert any(row["values"].get("text") == fixture.chunk["text"] for row in result["rows"])


@pytest.mark.parametrize("table", ["document_version", "knowledge_chunk"])
async def test_core_search_grants_no_raw_table_read(database, table):
    await _ready(database)
    with psycopg.connect(_role(database, "fdai_core")) as core:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            core.execute(psycopg.sql.SQL("SELECT * FROM {}").format(psycopg.sql.Identifier(table)))


@pytest.mark.parametrize("operation", ["insert", "update", "delete", "rename_in", "rename_out"])
async def test_operator_cannot_forge_core_goal_history(database, operation):
    fixture = await _ready(database)
    key = "handover_goal:goal:" + fixture.goal.goal_id
    with psycopg.connect(_role(database, "fdai_operator")) as operator:
        expected = (
            psycopg.errors.InsufficientPrivilege
            if operation == "delete"
            else psycopg.errors.RaiseException
        )
        with pytest.raises(expected):
            if operation == "insert":
                operator.execute(
                    "INSERT INTO state_kv (key,value) VALUES (%s,'{}')", (key + "-other",)
                )
            elif operation == "update":
                operator.execute("UPDATE state_kv SET value='{}' WHERE key=%s", (key,))
            elif operation == "delete":
                operator.execute("DELETE FROM state_kv WHERE key=%s", (key,))
            elif operation == "rename_out":
                operator.execute("UPDATE state_kv SET key='other:goal' WHERE key=%s", (key,))
            else:
                operator.execute("INSERT INTO state_kv (key,value) VALUES ('other:goal','{}')")
                operator.execute(
                    "UPDATE state_kv SET key=%s WHERE key='other:goal'", (key + "-renamed",)
                )


async def test_real_reader_backup_requires_observed_groups_and_current_document_acl(database):
    fixture = await _ready(database)
    assert await fixture.core.admission.verify(
        subject_ref="human:subject",
        evidence_ref=fixture.reference,
        digest="a" * 64,
        reviewer_ref="human:backup",
    )
    fixture.identities["human:backup"] = replace(fixture.identities["human:backup"], group_ids=())
    assert not await fixture.core.admission.verify(
        subject_ref="human:subject",
        evidence_ref=fixture.reference,
        digest="a" * 64,
        reviewer_ref="human:backup",
    )
    with psycopg.connect(_role(database, "fdai_operator")) as operator:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            operator.execute(
                "SELECT fdai_core_handover_goal_access(%s,1,%s)",
                (fixture.goal.goal_id, "human:subject"),
            )


@pytest.mark.parametrize(
    "field,value",
    [
        ("available", "true"),
        ("index_state", "tombstoned"),
        ("retention_state", "purged"),
        ("disposition", "handover_draft"),
        ("uploader_id", "human:other"),
        ("source_sha256", "b" * 64),
    ],
)
async def test_exact_source_withdrawal_blocks_core_search(database, field, value):
    fixture = await _ready(database)
    with psycopg.connect(database) as admin:
        admin.execute(
            "UPDATE document_version SET payload=%s", (Jsonb({**fixture.document, field: value}),)
        )
    with pytest.raises(PermissionError, match="admission"):
        await _search(fixture)


@pytest.mark.parametrize(
    "changes",
    [
        {"collection_id": "other"},
        {"allowed_access_refs": frozenset({"acl:other"})},
    ],
)
async def test_source_scopes_cannot_be_widened_by_access_labels(database, changes):
    fixture = await _ready(database)
    assert await _search(fixture, **changes) == ()


async def test_wrong_principal_and_core_sql_role_are_refused(database):
    fixture = await _ready(database)
    with pytest.raises(PermissionError, match="own"):
        await _search(fixture, principal_ref="human:other")
    wrong = replace(
        fixture.core.admission,
        source=PostgresHandoverSourceReader(PostgresStateStoreConfig(dsn=database)),
    )
    with pytest.raises(PermissionError, match="Core SQL role"):
        await wrong.verify(
            subject_ref="human:subject",
            evidence_ref=fixture.reference,
            digest="a" * 64,
            reviewer_ref="human:owner",
        )


@pytest.mark.parametrize("change", ["inactive", "wrong_scope", "revocation_hold"])
async def test_current_backup_case_is_not_a_static_role_label(database, change):
    fixture = await _ready(database)
    assert await fixture.core.admission.may_review(
        reviewer_ref="human:backup", agent_name="Muninn", scope_ref="scope:example", role="backup"
    )
    backup = fixture.backup
    if change == "inactive":
        backup = replace(backup, state=AssignmentState.SUPERSEDED)
    elif change == "wrong_scope":
        backup = replace(
            backup,
            intent=replace(
                backup.intent, duty_bindings=(DutyBinding("Muninn", Duty.BACKUP, "scope:other"),)
            ),
        )
    else:
        backup = replace(
            backup,
            state=AssignmentState.DEGRADED,
            revocation_case_id="case:removal",
            degraded_reason="revocation_pending",
        )
    await fixture.store.write_state("human_assignment:case:" + backup.case_id, backup.to_dict())
    assert not await fixture.core.admission.may_review(
        reviewer_ref="human:backup", agent_name="Muninn", scope_ref="scope:example", role="backup"
    )


async def test_expired_chunk_is_not_returned_and_retained_goals_block_schema_rollback(database):
    fixture = await _ready(database)
    with psycopg.connect(database) as admin:
        admin.execute(
            "UPDATE knowledge_chunk SET metadata=metadata || %s",
            (Jsonb({"expires_at": "2000-01-01T00:00:00Z"}),),
        )
    assert await _search(fixture) == ()
    with psycopg.connect(database) as admin:
        with pytest.raises(RuntimeError, match="preserve"):
            _run_migration(admin, _MIGRATION, "downgrade")


@pytest.mark.parametrize("changed_source", ["goal", "document", "chunk"])
async def test_source_change_during_actual_search_does_not_return_old_content(
    database, monkeypatch, changed_source
):
    fixture = await _ready(database)
    original = psycopg.AsyncConnection.execute
    changed = False

    async def execute(connection, query, *args, **kwargs):
        nonlocal changed
        cursor = await original(connection, query, *args, **kwargs)
        if (
            not changed
            and isinstance(query, str)
            and query.startswith("SELECT * FROM fdai_search_core_handover_goal")
        ):
            changed = True
            if changed_source == "goal":
                await fixture.store.write_state(
                    "handover_goal:goal:" + fixture.goal.goal_id,
                    replace(fixture.goal, state=HandoverGoalState.STALE, revision=2).to_dict(),
                )
            else:
                with psycopg.connect(database) as admin:
                    if changed_source == "document":
                        admin.execute(
                            "UPDATE document_version SET payload=payload || "
                            "'{\"available\":false}'::jsonb"
                        )
                    else:
                        admin.execute("UPDATE knowledge_chunk SET text='Changed rollback content.'")
        return cursor

    monkeypatch.setattr(psycopg.AsyncConnection, "execute", execute)
    with pytest.raises(ValueError, match="changed|admission"):
        await _search(fixture)


async def test_same_bare_subject_id_from_another_provider_does_not_gain_entra_admission(database):
    fixture = await _ready(database)
    assignment = replace(
        fixture.assignment,
        intent=replace(
            fixture.assignment.intent,
            subject=ProviderSubject("other", "human:subject"),
        ),
    )
    await fixture.store.write_state(
        "human_assignment:case:" + assignment.case_id, assignment.to_dict()
    )
    with pytest.raises(PermissionError, match="admission"):
        await _search(fixture)
