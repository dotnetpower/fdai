"""Real private intent persistence through owned agents; provider/identity input is synthetic."""

from __future__ import annotations

import asyncio
import hashlib
import json
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
import yaml
from fdai.agents._framework.audit_chain_rehydrate import StateStoreAuditChainAdapter
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.document_intent import (
    owned_document_intent_handler,
    publish_document_intent_source,
    recover_document_intent_publications,
)
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.runtime_payload_validation import default_payload_validator
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.agents.odin import Odin
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.agents.var import Var
from fdai.agents.vidar import Vidar
from fdai.core.conversation.session import Principal
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
)
from fdai.core.rbac.roles import Role
from fdai.delivery.identity.handover_review_identity import HandoverIdentityFacts
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_document_intent import PostgresDocumentIntent
from fdai.delivery.persistence.postgres_document_intent_reader import document_intent_gateway
from fdai.delivery.persistence.postgres_ontology import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.runtime.document_intent import DocumentIntentRuntime
from fdai.shared.contracts.models import CeilingRole, OntologyObjectType
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai_document_worker_service.artifact_manifest import attach_artifact_manifest
from fdai_service_contracts import (
    AccessDescriptor,
    DocumentDisposition,
    DocumentEnvelope,
    DocumentIndexState,
    DocumentPurpose,
    DocumentRetentionState,
    DocumentState,
    DocumentVersion,
    ProtectionState,
    RetentionPolicy,
    StructuralUnit,
)
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[3]
_support = runpy.run_path(str(Path(__file__).with_name("test_assignment_receipt_postgres.py")))
database = _support["database"]
_role = _support["_role"]
pytestmark = pytest.mark.integration


async def setup(database):
    at = datetime.now(UTC)
    statements = []
    with patch("alembic.op.execute", side_effect=statements.append):
        runpy.run_path(
            str(
                ROOT
                / (
                    "service-migrations/branches/core-control-plane/versions/"
                    "20261019_core_document_intent.py"
                )
            )
        )["upgrade"]()
    with psycopg.connect(database) as connection:
        connection.execute("ALTER TABLE document_version ADD COLUMN revision BIGINT DEFAULT 1")
        connection.execute(
            "CREATE UNIQUE INDEX document_intent_one_active_version "
            "ON document_version(document_id) WHERE active"
        )
        for statement in statements:
            connection.execute(statement)
    config = PostgresStateStoreConfig(dsn=_role(database, "fdai_core"))
    state = PostgresStateStore(config=config)
    declaration = OntologyObjectType.model_validate(
        yaml.safe_load(
            (ROOT / "rule-catalog/vocabulary/object-types/BusinessService.yaml").read_text()
        )
    )
    graph = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(dsn=config.dsn),
        object_types=(declaration,),
        link_types=(),
    )
    facts = {
        subject: HandoverIdentityFacts(
            subject, roles, ("group:catalog",), at, at + timedelta(minutes=5)
        )
        for subject, roles in (
            ("human:author", ("Reader",)),
            ("human:reviewer", ("Owner",)),
            ("human:reader", ("Reader",)),
        )
    }

    class Identities:
        async def read(self, subject):
            return facts.get(subject)

    repo = PostgresDocumentIntent(graph, Identities(), clock=lambda: at)
    bus = InMemoryBus(
        registry=load_pantheon(),
        isolate_handlers=False,
        payload_validator=default_payload_validator,
    )
    saga = Saga(audit_chain=StateStoreAuditChainAdapter(state), durable_state_store=state)
    var = Var(bus=bus, state_store=state, clock=lambda: at)
    agents = {
        "Saga": saga,
        "Var": var,
        "Muninn": Muninn(),
        "Norns": Norns(),
        "Mimir": Mimir(),
        "Forseti": Forseti(),
        "Heimdall": Heimdall(),
        "Vidar": Vidar(),
        "Thor": Thor(),
        "Odin": Odin(),
    }
    for name, agent in agents.items():
        agent.bind_bus(bus)
        handler = owned_document_intent_handler(agent, repo, agent.on_typed_message)
        for topic in agent.spec.subscribes:
            bus.subscribe(topic, name, handler)
    return SimpleNamespace(
        at=at,
        repo=repo,
        state=state,
        bus=bus,
        agents=agents,
        var=var,
        facts=facts,
        runtime=DocumentIntentRuntime(repo),
    )


def source(
    fixture, *, document=None, version=None, name="Example service", service_id="service:example"
):
    document, version = document or uuid4(), version or uuid4()
    access = AccessDescriptor(
        reference="acl:example-catalog",
        collection_id="example-catalog",
        reader_groups=("group:catalog",),
    )
    retention = RetentionPolicy(
        policy_version="example:1", derived_expires_at=fixture.at + timedelta(days=1)
    )
    properties = {
        "id": service_id,
        "name": name,
        "criticality": "example-low",
        "effective_from": (fixture.at - timedelta(minutes=1)).isoformat(),
        "source_ref": f"doc:{document}:{version}",
    }
    text = json.dumps(
        {"kind": "fdai.declared-intent.business-service.v1", "properties": properties}
    )
    source_digest = hashlib.sha256(text.encode()).hexdigest()
    metadata = DocumentVersion(
        document_id=document,
        version_id=version,
        upload_id=uuid4(),
        source_name="example-service-catalog.json",
        source_sha256=source_digest,
        size_bytes=len(text.encode()),
        media_type="application/json",
        observed_format="json",
        state=DocumentState.READY,
        protection_state=ProtectionState.NONE,
        access=access,
        retention=retention,
        purposes=(DocumentPurpose.MANUAL_DISTILLATION,),
        uploader_id="human:author",
        created_at=fixture.at,
        updated_at=fixture.at,
        active=True,
        available=True,
        disposition=DocumentDisposition.GOVERNED_KNOWLEDGE,
        index_state=DocumentIndexState.ACTIVE,
        retention_state=DocumentRetentionState.LIVE,
    )
    envelope = DocumentEnvelope(
        document_id=document,
        version_id=version,
        source_sha256=source_digest,
        media_type="application/json",
        observed_format="json",
        size_bytes=len(text.encode()),
        collection_id=access.collection_id,
        purposes=metadata.purposes,
        protection_state=metadata.protection_state,
        access_descriptor_ref=access.reference,
        units=(
            StructuralUnit(
                unit_id="unit:1",
                kind="paragraph",
                locator="json/record:1",
                text=text,
            ),
        ),
        extractor_name="synthetic-typed-provider",
        extractor_version="1",
    )
    envelope = attach_artifact_manifest(envelope=envelope, version=metadata, observed_at=fixture.at)
    return metadata, envelope


def save(database, metadata):
    with psycopg.connect(database) as connection:
        connection.execute(
            "INSERT INTO document_version(document_id,version_id,state,active,payload,revision) "
            "VALUES (%s,%s,%s,%s,%s,1) ON CONFLICT(version_id) DO UPDATE "
            "SET payload=EXCLUDED.payload,active=EXCLUDED.active,state=EXCLUDED.state,"
            "revision=EXCLUDED.revision",
            (
                metadata.document_id,
                metadata.version_id,
                metadata.state.value,
                metadata.active,
                Jsonb(metadata.model_dump(mode="json")),
            ),
        )


async def propose(fixture, envelope, *, operation="add", revision=0, correlation=None):
    digest, default_correlation = await fixture.runtime.submit(
        fixture.bus,
        envelope,
        principal=Principal(id="human:author", role=Role.READER),
        scope_ref="example-catalog",
        operation=operation,
        expected_revision=revision,
    )
    correlation = correlation or default_correlation
    return digest, correlation


async def read(fixture, *, principal="human:reader"):
    gateway = document_intent_gateway(
        fixture.repo, Principal(id=principal, role=Role.READER, groups=frozenset({"group:catalog"}))
    )
    admission = gateway._source_read_admission
    return await gateway.materialize(
        ObjectSetDefinition(
            selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="BusinessService"),
            as_of=fixture.at,
            purpose="operations-review",
        ),
        projection_request=ProjectionRequest(
            caller_role=CeilingRole.READER,
            declared_purposes=frozenset({"operations-review"}),
            principal_scope_digest=admission.scope,
        ),
    )


async def test_governed_envelope_exact_var_approval_persisted_secured_read_and_withdrawal(database):
    fixture = await setup(database)
    try:
        metadata, envelope = source(fixture)
        save(database, metadata)
        digest, correlation = await propose(fixture, envelope)
        assert correlation in fixture.var._pending
        inspected = await fixture.runtime.review_diff(
            digest, principal=Principal(id="human:reviewer", role=Role.OWNER)
        )
        assert inspected.digest == digest
        assert inspected.properties.name == "Example service"
        assert fixture.var._pending[correlation].params == {"intent_digest": inspected.digest}
        assert fixture.var._pending[correlation].resource_id != inspected.properties.id
        assert (await read(fixture)).receipt.returned_object_count == 0
        with pytest.raises(ValueError, match="self-approval"):
            await fixture.var.decide(correlation, approver="human:author", decision="approve")
        await fixture.var.decide(correlation, approver="human:reviewer", decision="approve")
        result = await read(fixture)
        assert result.materialization.graph.objects[0].properties["name"] == "Example service"
        assert result.receipt.execution_authority is False
        assert result.receipt.source_generation.startswith("document-intent:")
        with psycopg.connect(database) as connection:
            assert (
                connection.execute(
                    "SELECT receipt->>'outcome' FROM document_intent_transition "
                    "WHERE digest=%s AND phase='verified_sealed'",
                    (digest,),
                ).fetchone()[0]
                == "matched"
            )
            connection.execute(
                "UPDATE document_version SET active=FALSE WHERE version_id=%s",
                (metadata.version_id,),
            )
        with pytest.raises(PermissionError):
            await read(fixture)
        await publish_document_intent_source(
            fixture.bus, intent_digest=digest, correlation_id="withdrawal:" + digest[7:]
        )
        assert (await read(fixture)).receipt.returned_object_count == 0
        with psycopg.connect(database) as connection:
            assert (
                connection.execute(
                    "SELECT status FROM document_intent_projection WHERE digest=%s", (digest,)
                ).fetchone()[0]
                == "rolled_back"
            )
    finally:
        await fixture.state.aclose()


@pytest.mark.parametrize("drift", ["acl", "revision", "withdrawn", "release", "target"])
async def test_current_approval_cas_drift_is_audited_hold_without_partial_write(
    database, drift, monkeypatch
):
    fixture = await setup(database)
    try:
        metadata, envelope = source(fixture)
        save(database, metadata)
        digest, correlation = await propose(fixture, envelope)
        original = PostgresDocumentIntent.authorize_review

        async def mutate_after_review(self, reviewer, target):
            approved = await original(self, reviewer, target)
            assert approved
            with psycopg.connect(database) as connection:
                if drift == "acl":
                    connection.execute(
                        "UPDATE document_version SET payload=jsonb_set(payload,"
                        "'{access,reader_groups}','[]'::jsonb) WHERE version_id=%s",
                        (metadata.version_id,),
                    )
                elif drift == "revision":
                    connection.execute("UPDATE document_version SET revision=2")
                elif drift == "withdrawn":
                    connection.execute("UPDATE document_version SET active=FALSE")
                elif drift == "release":
                    fixture.repo.graph._release = build_ontology_release(
                        object_types=(
                            fixture.repo.graph._object_types["BusinessService"].model_copy(
                                update={"version": "1.0.1"}
                            ),
                        ),
                    )
                else:
                    connection.execute(
                        "INSERT INTO document_intent_resource VALUES "
                        "('service:example','BusinessService',%s,3,'1.0.0',%s)",
                        (
                            Jsonb({"id": "service:example", "name": "unrelated"}),
                            fixture.repo.graph._release.digest,
                        ),
                    )
            return approved

        monkeypatch.setattr(PostgresDocumentIntent, "authorize_review", mutate_after_review)
        await fixture.var.decide(correlation, approver="human:reviewer", decision="approve")
        with psycopg.connect(database) as connection:
            assert (
                connection.execute(
                    "SELECT status FROM document_intent_projection WHERE digest=%s", (digest,)
                ).fetchone()[0]
                == "candidate"
            )
            assert (
                connection.execute(
                    "SELECT count(*) FROM document_intent_transition "
                    "WHERE digest=%s AND phase='held'",
                    (digest,),
                ).fetchone()[0]
                == 1
            )
            assert connection.execute("SELECT count(*) FROM document_intent_resource").fetchone()[
                0
            ] == (1 if drift == "target" else 0)
    finally:
        await fixture.state.aclose()


async def test_update_identical_replay_and_conflicting_source_never_overwrite_history(database):
    fixture = await setup(database)
    try:
        metadata, envelope = source(fixture)
        save(database, metadata)
        digest, correlation = await propose(fixture, envelope)
        await fixture.var.decide(correlation, approver="human:reviewer", decision="approve")
        replay = await fixture.repo.apply(digest, correlation)
        assert replay.applied_revision == 1
        updated, replacement = source(
            fixture, document=metadata.document_id, name="Updated service"
        )
        with psycopg.connect(database) as connection:
            connection.execute("UPDATE document_version SET active=FALSE")
        save(database, updated)
        changed, review = await propose(fixture, replacement, operation="update", revision=1)
        await fixture.var.decide(review, approver="human:reviewer", decision="approve")
        result = await read(fixture)
        assert result.materialization.graph.objects[0].revision == 2
        assert result.materialization.graph.objects[0].properties["name"] == "Updated service"
        foreign, foreign_envelope = source(fixture, name="Conflicting source")
        save(database, foreign)
        rejected, foreign_review = await propose(
            fixture, foreign_envelope, operation="update", revision=2
        )
        await fixture.var.decide(foreign_review, approver="human:reviewer", decision="approve")
        assert (await read(fixture)).materialization.graph.objects[0].properties[
            "name"
        ] == "Updated service"
        with psycopg.connect(database) as connection:
            assert (
                connection.execute(
                    "SELECT phase FROM document_intent_transition WHERE digest=%s AND phase='held'",
                    (rejected,),
                ).fetchone()[0]
                == "held"
            )
            assert (
                connection.execute(
                    "SELECT status FROM document_intent_projection WHERE digest=%s", (changed,)
                ).fetchone()[0]
                == "applied"
            )
    finally:
        await fixture.state.aclose()


async def test_independent_readback_failure_rolls_back_only_its_own_record(database, monkeypatch):
    fixture = await setup(database)
    try:
        metadata, envelope = source(
            fixture, service_id="service:unrelated", name="Unrelated service"
        )
        save(database, metadata)
        _, correlation = await propose(fixture, envelope)
        await fixture.var.decide(correlation, approver="human:reviewer", decision="approve")
        original = PostgresDocumentIntent.observe

        async def corrupted_effect(self, event):
            with psycopg.connect(database) as connection:
                connection.execute(
                    "UPDATE document_intent_resource SET properties=jsonb_set("
                    "properties,'{name}','\"wrong effect\"'::jsonb) WHERE id='service:example'"
                )
            return await original(self, event)

        monkeypatch.setattr(PostgresDocumentIntent, "observe", corrupted_effect)
        bad, bad_envelope = source(fixture)
        save(database, bad)
        digest, review = await propose(fixture, bad_envelope)
        await fixture.var.decide(review, approver="human:reviewer", decision="approve")
        result = await read(fixture)
        assert [row.id for row in result.materialization.graph.objects] == ["service:unrelated"]
        with psycopg.connect(database) as connection:
            assert (
                connection.execute(
                    "SELECT status FROM document_intent_projection WHERE digest=%s", (digest,)
                ).fetchone()[0]
                == "rolled_back"
            )
    finally:
        await fixture.state.aclose()


async def test_rejected_or_unpersisted_approval_cannot_create_intent(database):
    fixture = await setup(database)
    try:
        metadata, envelope = source(fixture)
        save(database, metadata)
        digest, correlation = await propose(fixture, envelope)
        await fixture.var.decide(correlation, approver="human:reviewer", decision="reject")
        assert (await read(fixture)).receipt.returned_object_count == 0
        await fixture.bus.publish(
            "Var",
            "object.approval",
            {
                "kind": "document_intent_projection",
                "producer_principal": "Var",
                "correlation_id": "forged-review",
                "resource_id": "document-intent:" + digest[7:],
                "idempotency_key": "forged-review",
                "action_idempotency_key": "sha256:" + "b" * 64,
                "action_type": "document.review-intent-diff",
                "original_quorum_required": 1,
                "effective_quorum_required": 1,
                "state": "approved",
                "params": {"intent_digest": digest},
                "approvers": ["human:reviewer"],
            },
        )
        assert (await read(fixture)).receipt.returned_object_count == 0
    finally:
        await fixture.state.aclose()


async def test_real_runtime_bridge_uses_default_validation_for_approval_write_and_withdrawal(
    database,
):
    fixture = await setup(database)
    runtime = PantheonRuntime.build(
        provider=LocalEventBus(),
        raw_event_topic="fdai.document-intent.test",
        saga=fixture.agents["Saga"],
        var_state_store=fixture.state,
        document_intent=fixture.repo,
    )
    fixture.var = runtime.agents["Var"]
    running = asyncio.create_task(runtime.run())

    async def wait_for_state(digest, phase, correlation):
        async with asyncio.timeout(10):
            while True:
                with psycopg.connect(database) as connection:
                    row = connection.execute(
                        "SELECT receipt FROM document_intent_transition "
                        "WHERE digest=%s AND phase=%s AND correlation_id=%s",
                        (digest, phase, correlation),
                    ).fetchone()
                if row is not None:
                    return row[0]
                await asyncio.sleep(0.01)

    try:
        assert runtime.bridge.payload_validator is default_payload_validator
        metadata, envelope = source(fixture)
        save(database, metadata)
        digest, correlation = await fixture.runtime.submit(
            runtime.bridge,
            envelope,
            principal=Principal(id="human:author", role=Role.READER),
            scope_ref="example-catalog",
            operation="add",
            expected_revision=0,
        )
        async with asyncio.timeout(10):
            while correlation not in fixture.var._pending:
                await asyncio.sleep(0.01)
        await fixture.var.decide(correlation, approver="human:reviewer", decision="approve")
        effect = await wait_for_state(digest, "verified_sealed", correlation)
        assert effect["outcome"] == "matched"
        assert (await read(fixture)).receipt.returned_object_count == 1
        with psycopg.connect(database) as connection:
            connection.execute(
                "UPDATE document_version SET active=FALSE WHERE version_id=%s",
                (metadata.version_id,),
            )
        with pytest.raises(PermissionError):
            await read(fixture)
        withdrawn = "withdrawal:" + digest[7:]
        await publish_document_intent_source(
            runtime.bridge, intent_digest=digest, correlation_id=withdrawn
        )
        await wait_for_state(digest, "rolled_back", withdrawn)
        assert (await read(fixture)).receipt.returned_object_count == 0
        assert not runtime.bridge.snapshot()["recent_rejected_edges"]
    finally:
        await runtime.stop()
        await asyncio.wait_for(running, timeout=5)
        await fixture.state.aclose()


@pytest.mark.parametrize("reason", ["acl", "role", "expired"])
async def test_var_cannot_approve_without_current_source_access_and_review_role(database, reason):
    fixture = await setup(database)
    try:
        metadata, envelope = source(fixture)
        save(database, metadata)
        _, correlation = await propose(fixture, envelope)
        human = fixture.facts["human:reviewer"]
        fixture.facts["human:reviewer"] = HandoverIdentityFacts(
            human.subject_ref,
            ("Reader",) if reason == "role" else human.roles,
            () if reason == "acl" else human.group_ids,
            human.observed_at,
            fixture.at if reason == "expired" else human.expires_at,
        )
        with pytest.raises(PermissionError, match="not authorized"):
            await fixture.var.decide(correlation, approver="human:reviewer", decision="approve")
        with psycopg.connect(database) as connection:
            assert (
                connection.execute("SELECT count(*) FROM document_intent_resource").fetchone()[0]
                == 0
            )
    finally:
        await fixture.state.aclose()


async def test_source_diff_and_transitions_are_immutable_and_operator_cannot_read(database):
    fixture = await setup(database)
    try:
        metadata, envelope = source(fixture)
        save(database, metadata)
        digest, _ = await propose(fixture, envelope)
        with psycopg.connect(_role(database, "fdai_core"), autocommit=True) as connection:
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                connection.execute(
                    "UPDATE document_intent_projection SET diff='{}'::jsonb WHERE digest=%s",
                    (digest,),
                )
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                connection.execute(
                    "UPDATE document_intent_transition SET receipt='{}'::jsonb WHERE digest=%s",
                    (digest,),
                )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT payload FROM document_version")
        with psycopg.connect(_role(database, "fdai_operator"), autocommit=True) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT * FROM document_intent_resource")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    "SELECT fdai_document_intent_source(%s,%s)",
                    (metadata.document_id, metadata.version_id),
                )
    finally:
        await fixture.state.aclose()


async def test_lost_publication_ack_restarts_from_persisted_receipts_without_reapplying(
    database, monkeypatch
):
    fixture = await setup(database)
    try:
        metadata, envelope = source(fixture)
        save(database, metadata)
        _, correlation = await propose(fixture, envelope)
        original = PostgresDocumentIntent.published
        failed = False

        async def lose_once(self, event):
            nonlocal failed
            if event.phase == "verified_sealed" and not failed:
                failed = True
                raise RuntimeError("synthetic lost publication acknowledgment")
            await original(self, event)

        monkeypatch.setattr(PostgresDocumentIntent, "published", lose_once)
        with pytest.raises(RuntimeError, match="lost publication"):
            await fixture.var.decide(correlation, approver="human:reviewer", decision="approve")
        await recover_document_intent_publications(fixture.agents, fixture.repo)
        await fixture.var.recover_approvals()
        result = await read(fixture)
        assert result.materialization.graph.objects[0].revision == 1
        assert fixture.agents["Saga"].durable_audit
        assert fixture.agents["Saga"].audit_chain.entries
    finally:
        await fixture.state.aclose()
