"""Loopback PostgreSQL checks for Operator authentication receipt retention.

Set FDAI_OPERATIONAL_EVIDENCE_TEST_DSN to a loopback PostgreSQL admin DSN.
"""

from __future__ import annotations

import asyncio
import json
import os
import runpy
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from fdai.composition.semantic_query_invocation_context import semantic_query_invocation_context
from fdai.core.ontology_platform.pattern_queries import OperatingPatternQuery
from fdai.core.operational_evidence.grant_registry_loader import load_grant_registry
from fdai.core.operational_evidence.issuance import (
    IssuedEvidence,
    OperationalEvidenceVerifierEngine,
    StoredAttempt,
    VerifierIdentity,
)
from fdai.core.operational_evidence.owner_outcome import OperationalEvidenceRequester
from fdai.core.operational_evidence.readback.case_history_read import CaseHistoryReadback
from fdai.core.operational_evidence.registry_json import content_pin
from fdai.core.operational_evidence.revision_history import RegistryHistory, RegistryRevision
from fdai.core.operational_evidence.trust_registry_loader import (
    load_deployment_anchors,
    load_trust_registry,
)
from fdai.delivery.operational_evidence_admission import OperationalEvidenceAdmissionProvider
from fdai.delivery.operational_evidence_transport import (
    BoundedOperationalEvidenceIssuer,
    InProcessOperationalEvidenceTransport,
)
from fdai.delivery.persistence.postgres_operational_evidence import (
    VERIFIER_ROLE,
    PostgresOperationalEvidenceConfig,
)
from fdai.delivery.persistence.postgres_operational_evidence_sources import (
    PostgresSemanticAuthenticationReceiptSource,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    RetainedDecisionEvidence,
    decision_evidence_record_mapping,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_core_service.contract_codecs import OPERATOR_REQUEST_CONSUMER_V19
from fdai_core_service.semantic_turn_request import principal as core_principal
from fdai_operator_service.families.conversation.contracts import (
    ConversationProposal,
    ConversationResponse,
    OutboxReceipt,
    PrincipalScope,
)
from fdai_operator_service.families.conversation.semantic_authentication_receipts import (
    AuthenticationReceiptRetainingOutbox,
    PostgresAuthenticationReceiptWriter,
)
from fdai_operator_service.families.conversation.semantic_turn import SemanticTurnEnvelopeBuilder
from fdai_service_contracts import OperatorPrincipal, OperatorRole, SemanticTurnRequest
from fdai_service_contracts.codec import ProducerCodec
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceRejectionRecord,
)
from fdai_service_contracts.operator_authentication import OperatorAuthenticationReceipt
from fdai_service_contracts.venue import ExecutionVenue
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

SCOPE = "a" * 64
REQUESTER = "00000000-0000-0000-0000-000000000011"
REQUESTER_GROUP = "00000000-0000-0000-0000-000000000001"
POLICY = "policy:test-context:1"
LOCAL_PRINCIPALS = {
    "anchor:azure-platform": "local-azure-platform",
    "anchor:core-runtime": "fdai_core",
    "anchor:deploy-runner": "local-deploy-runner",
    "anchor:dev-operations-gateway-executor": "local-dev-operations-gateway",
    "anchor:inventory": "local-inventory",
    "anchor:isolated-executor": "local-isolated-executor",
    "anchor:operating-intent-source": "local-operating-intent",
    "anchor:operational-evidence-verifier": "fdai_operational_evidence_verifier",
    "anchor:operator-reviewers": "local-operator-reviewers",
    "anchor:operator-service": "fdai_operator",
    "anchor:vertical-effect-executors": "local-vertical-effect-executors",
}

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
CORE_MIGRATION = ROOT / (
    "service-migrations/branches/core-control-plane/versions/20260928_core_operational_evidence.py"
)
MIGRATION = ROOT / (
    "service-migrations/branches/operator-service/versions/"
    "20260929_operator_authentication_receipts.py"
)
SOURCE_MIGRATION = ROOT / (
    "service-migrations/branches/core-control-plane/versions/"
    "20260930_core_operator_receipt_source.py"
)


@pytest.fixture
def database() -> Iterator[tuple[str, list[str], list[str]]]:
    source = os.environ.get("FDAI_OPERATIONAL_EVIDENCE_TEST_DSN")
    if not source:
        pytest.skip("FDAI_OPERATIONAL_EVIDENCE_TEST_DSN is unset")
    source = source.replace("postgresql+psycopg://", "postgresql://", 1)
    parameters = conninfo_to_dict(source)
    if parameters.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("authentication receipt database test requires a loopback-only fixture")
    name = "fdai_auth_receipt_" + uuid4().hex[:12]
    core_module = runpy.run_path(str(CORE_MIGRATION))
    module = runpy.run_path(str(MIGRATION))
    source_module = runpy.run_path(str(SOURCE_MIGRATION))
    core_upgrade: list[str] = []
    upgrade: list[str] = []
    downgrade: list[str] = []
    source_upgrade: list[str] = []
    source_downgrade: list[str] = []
    with patch("alembic.op.execute", side_effect=core_upgrade.append):
        core_module["upgrade"]()
    with patch("alembic.op.execute", side_effect=upgrade.append):
        module["upgrade"]()
    with patch("alembic.op.execute", side_effect=downgrade.append):
        module["downgrade"]()
    with patch("alembic.op.execute", side_effect=source_upgrade.append):
        source_module["upgrade"]()
    with patch("alembic.op.execute", side_effect=source_downgrade.append):
        source_module["downgrade"]()
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(
            """DO $roles$ BEGIN
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
                    CREATE TABLE audit_log (
                        seq BIGSERIAL PRIMARY KEY, action_kind TEXT NOT NULL,
                        entry JSONB NOT NULL,
                        previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL UNIQUE);
                    GRANT USAGE ON SCHEMA public TO fdai_operator;"""
                )
                for statement in core_upgrade:
                    connection.execute(statement)
                assert _role_exists(connection, "fdai_operational_evidence_verifier")
                for statement in upgrade:
                    connection.execute(statement)
                for statement in source_upgrade:
                    connection.execute(statement)
            yield dsn, downgrade, source_downgrade
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _role(dsn: str, role: str) -> str:
    return make_conninfo(dsn, options=f"-c role={role}")


def _role_exists(connection: psycopg.Connection[object], role: str) -> bool:
    row = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
    return row is not None


class _AcceptedOutbox:
    async def append(self, _proposal: ConversationProposal) -> OutboxReceipt:
        return OutboxReceipt(
            proposal_id="semantic-request",
            duplicate=False,
            response=ConversationResponse(body={"accepted": True}, status_code=202),
        )


class _MemoryProofStore:
    def __init__(self) -> None:
        self.admissions: list[tuple[IssuedEvidence, dict[str, object]]] = []
        self.rejections: list[OperationalEvidenceRejectionRecord] = []

    async def attempt_outcome(self, attempt_id: str) -> StoredAttempt | None:
        for issued, record in self.admissions:
            if issued.attempt_id == attempt_id:
                return StoredAttempt(
                    OperationalEvidenceIssuanceStatus.ISSUED,
                    issued.lookup_digest,
                    str(record["record_digest"]),
                )
        for rejection in self.rejections:
            if rejection.attempt_id == attempt_id:
                return StoredAttempt(
                    OperationalEvidenceIssuanceStatus.REJECTED,
                    rejection.lookup_digest,
                    rejection.record_digest,
                )
        return None

    async def write_admission(self, issued: IssuedEvidence) -> str:
        record = decision_evidence_record_mapping(
            RetainedDecisionEvidence(
                receipt=issued.receipt,
                verification_bundle=issued.bundle,
                admission=issued.admission,
            )
        )
        self.admissions.append((issued, record))
        return str(record["record_digest"])

    async def write_rejection(self, record: OperationalEvidenceRejectionRecord) -> str:
        self.rejections.append(record)
        return record.record_digest

    async def newest_admissions(
        self, lookup_digest: str, pins_digests: frozenset[str], *, limit: int = 2
    ) -> tuple[object, ...]:
        from fdai.delivery.persistence.postgres_operational_evidence import RetainedAdmissionRow

        rows = [
            RetainedAdmissionRow(
                record=record,
                record_digest=str(record["record_digest"]),
                pins_digest=issued.pins.digest,
                lineage={},
            )
            for issued, record in reversed(self.admissions)
            if issued.lookup_digest == lookup_digest and issued.pins.digest in pins_digests
        ]
        return tuple(rows[:limit])

    async def rejection(self, *, record_digest: str, attempt_id: str) -> dict[str, object] | None:
        for record in self.rejections:
            if record.record_digest == record_digest and record.attempt_id == attempt_id:
                return record.model_dump(mode="json")
        return None


def _grant_document() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "registry_id": "fdai.operational-evidence.case-scope-grants",
        "revision": 1,
        "case_scopes": [
            {
                "case_scope_id": "cs-test",
                "access_scope_digest": SCOPE,
                "resource_selectors": ["*"],
                "purposes": ["case-history-read"],
                "policy_revision": POLICY,
                "valid_from": "2026-09-21T06:00:00+00:00",
                "valid_until": "2026-10-28T06:00:00+00:00",
                "revoked": False,
            }
        ],
        "principal_grants": [
            {
                "grant_id": "g-case-read",
                "selector": {"kind": "group", "value": REQUESTER_GROUP},
                "case_scopes": ["cs-test"],
                "operations": ["case-history.read"],
                "purposes": ["case-history-read"],
                "reviewer": "grant-reviewer-one",
                "valid_from": "2026-09-21T06:00:00+00:00",
                "valid_until": "2026-10-28T06:00:00+00:00",
                "revoked": False,
            }
        ],
        "reuse_grants": [],
    }


def _registry_history() -> RegistryHistory:
    trust_data = (ROOT / "config/operational-evidence-trust-registry.json").read_bytes()
    grant_data = (json.dumps(_grant_document(), sort_keys=True) + "\n").encode()
    return RegistryHistory(
        (
            RegistryRevision(
                trust=load_trust_registry(trust_data, expected_pin=content_pin(trust_data)),
                grants=load_grant_registry(grant_data, expected_pin=content_pin(grant_data)),
            ),
        )
    )


def _anchors():
    return load_deployment_anchors(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "venue": "local",
                "anchors": [
                    {
                        "anchor_id": key,
                        "principal_id": value,
                        "evidence_class": "local-loopback",
                    }
                    for key, value in sorted(LOCAL_PRINCIPALS.items())
                ],
            }
        ),
        execution_venue=ExecutionVenue.LOCAL,
    )


def test_receipt_store_is_insert_only_and_exact_function_detects_rows(
    database: tuple[str, list[str], list[str]],
) -> None:
    dsn, _downgrade, _source_downgrade = database
    digest = "sha256:" + "a" * 64
    receipt = {
        "schema_version": "1.0.0",
        "receipt_digest": digest,
        "subject_id": "operator-one",
        "groups": ["group-one"],
    }
    writer = PostgresAuthenticationReceiptWriter(dsn=_role(dsn, "fdai_operator"))
    for request_id in ("semantic-request-one", "semantic-request-one", "semantic-request-two"):
        asyncio.run(
            writer.retain(
                receipt_digest=digest,
                request_id=request_id,
                principal_id="operator-one",
                receipt=receipt,
            )
        )
    with psycopg.connect(_role(dsn, "fdai_operator")) as operator:
        operator.commit()
        with pytest.raises(psycopg.errors.UniqueViolation):
            operator.execute(
                "INSERT INTO operator_authentication_receipt "
                "(receipt_digest, request_id, principal_id, receipt) VALUES (%s, %s, %s, %s)",
                (digest, "semantic-request-one", "operator-one", Jsonb(receipt)),
            )
        operator.rollback()
        for statement in (
            "UPDATE operator_authentication_receipt SET receipt = receipt "
            "WHERE receipt_digest = %s",
            "DELETE FROM operator_authentication_receipt WHERE receipt_digest = %s",
        ):
            with pytest.raises(
                (psycopg.errors.RaiseException, psycopg.errors.InsufficientPrivilege)
            ):
                operator.execute(statement, (digest,))
            operator.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            operator.execute("SELECT receipt FROM operator_authentication_receipt")

    with psycopg.connect(_role(dsn, "fdai_operational_evidence_verifier")) as verifier:
        lookup = (
            "SELECT request_id, principal_id, receipt "
            "FROM fdai_operator_authentication_receipt_for_request(%s, %s)"
        )
        for request_id in ("semantic-request-one", "semantic-request-two"):
            rows = verifier.execute(lookup, (digest, request_id)).fetchall()
            assert rows == [(request_id, "operator-one", receipt)]
        assert verifier.execute(lookup, (digest, "semantic-request-three")).fetchall() == []
        assert verifier.execute(lookup, ("not-a-digest", "semantic-request-one")).fetchall() == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            verifier.execute("SELECT receipt FROM operator_authentication_receipt")


def test_receipt_migration_downgrade_is_symmetric_after_drain(
    database: tuple[str, list[str], list[str]],
) -> None:
    dsn, downgrade, source_downgrade = database
    with psycopg.connect(_role(dsn, "fdai_operator")) as operator:
        operator.execute(
            "INSERT INTO operator_authentication_receipt "
            "(receipt_digest, request_id, principal_id, receipt) VALUES (%s, %s, %s, %s)",
            ("sha256:" + "b" * 64, "request-two", "operator-two", Jsonb({"ok": True})),
        )
        operator.commit()
    with psycopg.connect(dsn) as connection:
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute(downgrade[0])
        connection.rollback()
        connection.execute(
            "ALTER TABLE operator_authentication_receipt "
            "DISABLE TRIGGER operator_auth_receipt_delete_immutable"
        )
        connection.execute("DELETE FROM operator_authentication_receipt")
        connection.execute(
            "ALTER TABLE operator_authentication_receipt "
            "ENABLE TRIGGER operator_auth_receipt_delete_immutable"
        )
        for statement in source_downgrade:
            connection.execute(statement)
        for statement in downgrade:
            connection.execute(statement)
        with pytest.raises(psycopg.errors.UndefinedTable):
            connection.execute("SELECT count(*) FROM operator_authentication_receipt")


def test_operator_objects_grant_nothing_to_the_core_verifier_role(
    database: tuple[str, list[str], list[str]],
) -> None:
    """After Core drops its lookup, no Operator object can block dropping the verifier role."""
    dsn, _downgrade, source_downgrade = database
    with psycopg.connect(dsn) as connection:
        for statement in source_downgrade:
            connection.execute(statement)
        table_grants = connection.execute(
            "SELECT count(*) FROM pg_class "
            "WHERE relname = 'operator_authentication_receipt' "
            "AND coalesce(relacl::text, '') LIKE '%fdai_operational_evidence_verifier%'"
        ).fetchone()
        function_grants = connection.execute(
            "SELECT count(*) FROM pg_proc "
            "WHERE proname LIKE 'fdai_operator_authentication_receipt%' "
            "AND coalesce(proacl::text, '') LIKE '%fdai_operational_evidence_verifier%'"
        ).fetchone()
        assert table_grants == (0,)
        assert function_grants == (0,)
        connection.execute("SELECT count(*) FROM operator_authentication_receipt")


def test_core_lookup_can_migrate_before_the_operator_receipt_table_exists() -> None:
    """Core's lookup is created without body validation and fails closed until the table exists."""
    module = runpy.run_path(str(SOURCE_MIGRATION))
    statements: list[str] = []
    with patch("alembic.op.execute", side_effect=statements.append):
        module["upgrade"]()
    assert "SET LOCAL check_function_bodies = off;" in statements[0]
    assert (
        "GRANT EXECUTE" in statements[0]
        and "TO fdai_operational_evidence_verifier" in statements[0]
    )
    assert "PUBLIC" in statements[0]


def _live_receipt(principal: OperatorPrincipal) -> OperatorAuthenticationReceipt:
    now = datetime.now(UTC)
    return OperatorAuthenticationReceipt.create(
        evidence_class="live",
        issuer="https://issuer.example.invalid/v2.0",
        audience="api://fdai-operator.example.invalid",
        tenant_digest="sha256:" + "1" * 64,
        subject_id=principal.subject_id,
        principal_kind="human",
        groups=tuple(sorted(principal.groups)),
        token_id_digest="sha256:" + "2" * 64,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
        roles=("Reader",),
        role_mapping_revision="sha256:" + "3" * 64,
    )


async def _stream_pattern_read(
    dsn: str,
    principal: OperatorPrincipal,
    auth: OperatorAuthenticationReceipt,
    *,
    idempotency_key: str,
    proofs: _MemoryProofStore,
) -> dict[str, object]:
    """Drive one Operator stream turn through retention, codecs, Core, Bragi, and the verifier."""
    proposal = ConversationProposal(
        operation="chat.stream",
        scope=PrincipalScope(
            principal.subject_id,
            frozenset({"Reader"}),
            groups=frozenset(principal.groups),
        ),
        idempotency_key=idempotency_key,
        body={"prompt": "Show reusable operating patterns.", "conversation_id": "session-one"},
        authentication_receipt=auth.model_dump(mode="json"),
    )
    builder = SemanticTurnEnvelopeBuilder(
        clock=lambda: datetime.now(UTC),
        emit_authentication_receipt_ref=True,
    )
    outbox = AuthenticationReceiptRetainingOutbox(
        delegate=_AcceptedOutbox(),
        builder=builder,
        writer=PostgresAuthenticationReceiptWriter(dsn=_role(dsn, "fdai_operator")),
    )
    await outbox.append(proposal)
    envelope = builder.build(proposal)
    decoded = OPERATOR_REQUEST_CONSUMER_V19.decode(
        ProducerCodec("operator-core-request", "N", "1.9.0").encode(envelope)
    )
    semantic_request = decoded["semantic_turn"]
    assert isinstance(semantic_request, dict)
    request_model = SemanticTurnRequest.model_validate(semantic_request)
    principal_context = core_principal(request_model, request_ref=str(decoded["request_id"]))
    context = semantic_query_invocation_context(
        principal=principal_context,
        role=CeilingRole.READER,
        purpose="operations-review",
        document_context=None,
    )
    verifier_store = PostgresOperationalEvidenceConfig(
        dsn=_role(dsn, VERIFIER_ROLE),
        expected_role=VERIFIER_ROLE,
    )
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=_registry_history,
        anchors=_anchors(),
        readbacks=(
            CaseHistoryReadback(
                receipts=PostgresSemanticAuthenticationReceiptSource(verifier_store)
            ),
        ),
        writer=proofs,
        clock=lambda: datetime.now(UTC),
    )
    admission = OperationalEvidenceAdmissionProvider(
        reader=proofs,
        history=_registry_history,
        anchors=_anchors(),
        verifier_id="operational-evidence-verifier",
        clock=lambda: datetime.now(UTC),
    )
    reader = OperatingPatternQuery(
        store=InMemoryStateStore(),
        materializer=lambda: None,
        admission=admission,
        source_revision="sha256:" + "a" * 64,
        clock=lambda: datetime.now(UTC),
        evidence=OperationalEvidenceRequester(
            issuer=BoundedOperationalEvidenceIssuer(
                InProcessOperationalEvidenceTransport(engine, caller_principal="fdai_core")
            ),
            outcomes=admission,
            producer_id="core-control-plane",
            producer_version="1.0.0",
        ),
    )
    return await reader.read(
        {
            "access_scope_digest": "a" * 64,
            "purpose": "operations-review",
            "failure_fingerprint": None,
            "limit": 5,
        },
        context,
    )


_AUTHORIZED_WITHOUT_MATERIALIZED_PATTERNS = {
    "patterns": [],
    "unavailable": True,
    "truncated": False,
    "execution_authority": False,
}


async def test_operator_stream_receipt_reaches_case_history_read_positive_issuance(
    database: tuple[str, list[str], list[str]],
) -> None:
    dsn, _downgrade, _source_downgrade = database
    principal = OperatorPrincipal(
        subject_id=REQUESTER,
        roles=frozenset({OperatorRole.READER}),
        groups=frozenset({REQUESTER_GROUP}),
    )
    proofs = _MemoryProofStore()

    result = await _stream_pattern_read(
        dsn,
        principal,
        _live_receipt(principal),
        idempotency_key="case-history-positive",
        proofs=proofs,
    )

    assert result == _AUTHORIZED_WITHOUT_MATERIALIZED_PATTERNS
    assert [issued.purpose_id for issued, _record in proofs.admissions] == ["case-history-read"]
    assert proofs.rejections == []


async def test_every_turn_of_one_live_token_reaches_its_own_positive_issuance(
    database: tuple[str, list[str], list[str]],
) -> None:
    """One bearer token's receipt is retained per request, so later turns are not replays."""
    dsn, _downgrade, _source_downgrade = database
    principal = OperatorPrincipal(
        subject_id=REQUESTER,
        roles=frozenset({OperatorRole.READER}),
        groups=frozenset({REQUESTER_GROUP}),
    )
    auth = _live_receipt(principal)
    proofs = _MemoryProofStore()

    for turn in ("turn-one", "turn-two", "turn-one"):
        result = await _stream_pattern_read(
            dsn, principal, auth, idempotency_key=turn, proofs=proofs
        )
        assert result == _AUTHORIZED_WITHOUT_MATERIALIZED_PATTERNS

    assert proofs.rejections == []
    assert {issued.purpose_id for issued, _record in proofs.admissions} == {"case-history-read"}
    with psycopg.connect(dsn) as connection:
        rows = connection.execute(
            "SELECT receipt_digest, count(*) FROM operator_authentication_receipt "
            "GROUP BY receipt_digest"
        ).fetchall()
    assert rows == [(auth.receipt_digest, 2)]
