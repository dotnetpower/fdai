"""Exact-source fixtures for operational evidence tests.

Histories and audit rows come from the real ``GovernedTestContextStore`` over an in-memory
store with a genuine hash chain; Operator rows use the Operator outbox record shape; the trust
registry is the reviewed upstream file. All identifiers are placeholders.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fdai.core.operational_context.test_context_commands import TestContextCommandHandler
from fdai.core.operational_context.test_context_lifecycle import (
    GovernedTestContextStore,
    context_history_key,
)
from fdai.core.operational_evidence.grant_registry_loader import load_grant_registry
from fdai.core.operational_evidence.issuance import IssuedEvidence, StoredAttempt
from fdai.core.operational_evidence.readback.base import LineageRecord
from fdai.core.operational_evidence.readback.test_context_sources import (
    AuditRow,
    OperatorCommandRow,
)
from fdai.core.operational_evidence.registry_json import content_pin
from fdai.core.operational_evidence.revision_history import RegistryHistory, RegistryRevision
from fdai.core.operational_evidence.trust_registry import (
    DeploymentAnchors,
)
from fdai.core.operational_evidence.trust_registry_loader import (
    load_deployment_anchors,
    load_trust_registry,
)
from fdai.delivery.persistence.postgres_operational_evidence import RetainedAdmissionRow
from fdai.delivery.persistence.state_store_decision_evidence import (
    RetainedDecisionEvidence,
    decision_evidence_record_mapping,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceRejectionRecord,
)
from fdai_service_contracts.operator_authentication import (
    LOCAL_LOOPBACK_ISSUER,
    OperatorAuthenticationEvidenceClass,
    OperatorAuthenticationReceipt,
    role_mapping_revision,
    tenant_digest,
    token_id_digest,
)
from fdai_service_contracts.test_context import TestContextCommand
from fdai_service_contracts.venue import ExecutionVenue

ROOT = Path(__file__).resolve().parents[5]
TRUST_REGISTRY = ROOT / "config" / "operational-evidence-trust-registry.json"
NOW = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)
SCOPE = "a" * 64
POLICY = "policy:test-context:1"
TARGET = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test"
    "/providers/Microsoft.Web/sites/app-test"
)
REQUESTER = "00000000-0000-0000-0000-000000000011"
REVIEWER = "00000000-0000-0000-0000-000000000012"
REQUESTER_GROUP = "00000000-0000-0000-0000-000000000001"
REVIEWER_GROUP = "00000000-0000-0000-0000-000000000002"
TEST_CONTEXT_PURPOSES = [
    "operational-test-context",
    "operator-test-context-command",
    "test-context-transition",
]
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


def trust_bytes() -> bytes:
    return TRUST_REGISTRY.read_bytes()


def window(start: datetime = NOW - timedelta(days=7), days: int = 60) -> dict[str, object]:
    return {
        "valid_from": start.isoformat(),
        "valid_until": (start + timedelta(days=days)).isoformat(),
        "revoked": False,
    }


def grant_document() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "registry_id": "fdai.operational-evidence.case-scope-grants",
        "revision": 1,
        "case_scopes": [
            {
                "case_scope_id": "cs-test",
                "access_scope_digest": SCOPE,
                "resource_selectors": [
                    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/*"
                ],
                "purposes": TEST_CONTEXT_PURPOSES,
                "policy_revision": POLICY,
                **window(),
            }
        ],
        "principal_grants": [
            {
                "grant_id": "g-propose",
                "selector": {"kind": "group", "value": REQUESTER_GROUP},
                "case_scopes": ["cs-test"],
                "operations": ["test-context.propose"],
                "purposes": TEST_CONTEXT_PURPOSES,
                "reviewer": "grant-reviewer-one",
                **window(),
            },
            {
                "grant_id": "g-review",
                "selector": {"kind": "group", "value": REVIEWER_GROUP},
                "case_scopes": ["cs-test"],
                "operations": ["test-context.review", "test-context.revoke"],
                "purposes": TEST_CONTEXT_PURPOSES,
                "reviewer": "grant-reviewer-one",
                **window(),
            },
        ],
        "reuse_grants": [],
    }


def encode(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()


def anchors(
    *,
    venue: str = "local",
    evidence_class: str = "local-loopback",
    overrides: Mapping[str, str] | None = None,
) -> DeploymentAnchors:
    return load_deployment_anchors(
        anchors_json(venue=venue, evidence_class=evidence_class, overrides=overrides),
        execution_venue=ExecutionVenue(venue),
    )


def anchors_json(
    *,
    venue: str = "local",
    evidence_class: str = "local-loopback",
    overrides: Mapping[str, str] | None = None,
) -> str:
    principals = {**LOCAL_PRINCIPALS, **(overrides or {})}
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "venue": venue,
            "anchors": [
                {"anchor_id": key, "principal_id": value, "evidence_class": evidence_class}
                for key, value in sorted(principals.items())
            ],
        }
    )


def history(
    grants: Mapping[str, Any] | None = None, *, trust: bytes | None = None
) -> RegistryHistory:
    trust_data = trust if trust is not None else trust_bytes()
    grant_data = encode(grants or grant_document())
    return RegistryHistory(
        (
            RegistryRevision(
                trust=load_trust_registry(trust_data, expected_pin=content_pin(trust_data)),
                grants=load_grant_registry(grant_data, expected_pin=content_pin(grant_data)),
            ),
        )
    )


def receipt(
    subject: str,
    group: str,
    roles: tuple[str, ...],
    *,
    issued_at: datetime,
    evidence_class: OperatorAuthenticationEvidenceClass = (
        OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK
    ),
) -> OperatorAuthenticationReceipt:
    local = evidence_class is OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK
    return OperatorAuthenticationReceipt.create(
        evidence_class=evidence_class,
        issuer=LOCAL_LOOPBACK_ISSUER if local else "https://issuer.example.invalid/v2.0",
        audience=LOCAL_LOOPBACK_ISSUER if local else "api://fdai-operator.example.invalid",
        tenant_digest=tenant_digest("00000000-0000-0000-0000-000000000000"),
        subject_id=subject,
        principal_kind="human",
        groups=(group,),
        token_id_digest=token_id_digest("token-id-" + subject),
        issued_at=issued_at - timedelta(minutes=5),
        expires_at=issued_at + timedelta(minutes=55),
        roles=roles,
        role_mapping_revision=role_mapping_revision({"Approver": REVIEWER_GROUP}),
    )


def request_body(
    operation: str, *, expected_revision: int, context_id: str = "context-test"
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "operation": operation,
        "context_id": context_id,
        "access_scope_digest": SCOPE,
        "target_ref": TARGET,
        "signal_code": "cpu_percent",
        "expected_revision": expected_revision,
        "policy_revision": POLICY,
        "source_ref": "operator-turn:example",
        "semantic_receipt": "sha256:" + "d" * 64,
    }
    if operation == "propose":
        body.update(
            expected_min=60.0,
            expected_max=90.0,
            effective_from=(NOW - timedelta(minutes=30)).isoformat(),
            effective_to=(NOW + timedelta(hours=2)).isoformat(),
        )
    return body


@dataclass
class OperatorOutbox:
    """Operator-shaped command rows; the fake stands in for the least-privilege view."""

    rows: list[OperatorCommandRow] = field(default_factory=list)

    def add(
        self,
        operation: str,
        *,
        principal: str,
        group: str,
        roles: tuple[str, ...],
        accepted_at: datetime,
        expected_revision: int,
        key: str | None = None,
        with_receipt: bool = True,
        receipt_class: OperatorAuthenticationEvidenceClass = (
            OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK
        ),
        dispatch_status: str = "published",
        receipt_group: str | None = None,
        receipt_roles: tuple[str, ...] | None = None,
        receipt_issued_at: datetime | None = None,
        context_id: str = "context-test",
    ) -> OperatorCommandRow:
        idempotency_key = key or f"context-{operation}-{principal}"
        payload = {
            "operation": "test-context." + operation,
            "scope": {
                "subject_id": principal,
                "roles": list(roles),
                "principal_kind": "human",
                "groups": [group],
            },
            "idempotency_key": idempotency_key,
            "body": request_body(
                operation, expected_revision=expected_revision, context_id=context_id
            ),
            "query": {},
            "path_params": {},
            "confirmed": False,
            "cancellation": False,
        }
        request = {
            "family": "conversation",
            "operation": "test-context." + operation,
            "principal_id": principal,
            "idempotency_key": idempotency_key,
            "payload": payload,
        }
        digest = hashlib.sha256(
            json.dumps(request, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        record = {
            **request,
            "kind": "operator.proposal",
            "proposal_id": f"operator-{digest[:32]}",
            "request_digest": digest,
            "accepted_at": accepted_at.isoformat(),
        }
        row = OperatorCommandRow(
            key="operator-proposal:conversation:"
            + hashlib.sha256(idempotency_key.encode()).hexdigest(),
            record=record,
            dispatch_status=dispatch_status,
            authentication_receipt=(
                receipt(
                    principal,
                    receipt_group or group,
                    receipt_roles if receipt_roles is not None else roles,
                    issued_at=receipt_issued_at or accepted_at,
                    evidence_class=receipt_class,
                ).model_dump(mode="json")
                if with_receipt
                else None
            ),
        )
        self.rows.append(row)
        return row

    async def commands_for_key(self, idempotency_key: str) -> tuple[OperatorCommandRow, ...]:
        return tuple(row for row in self.rows if row.record["idempotency_key"] == idempotency_key)[
            :2
        ]

    async def commands_for_target(
        self, *, access_scope_digest: str, target_ref: str
    ) -> tuple[OperatorCommandRow, ...]:
        return tuple(
            row
            for row in self.rows
            if row.record["payload"]["body"]["access_scope_digest"] == access_scope_digest
            and row.record["payload"]["body"]["target_ref"] == target_ref
        )


@dataclass
class MimirSources:
    """History and audit rows read from a real governed store's in-memory backend."""

    store: InMemoryStateStore

    async def history(
        self, *, access_scope_digest: str, target_ref: str
    ) -> Mapping[str, Any] | None:
        return await self.store.read_state(context_history_key(access_scope_digest, target_ref))

    async def transition_entries(self, *, context_digests: tuple[str, ...]) -> tuple[AuditRow, ...]:
        return tuple(
            AuditRow(
                seq=index,
                entry=item["entry"],
                previous_hash=item["previous_hash"],
                entry_hash=item["entry_hash"],
            )
            for index, item in enumerate(self.store.audit_entries, start=1)
            if item["entry"].get("action_kind") == "test_context.transition"
            and item["entry"].get("context_digest") in context_digests
        )


class AllowingAdmission:
    """Stand-in for already-admitted history while fixtures build Mimir's store."""

    async def admit(self, **values: str) -> DecisionEvidenceAdmission:
        return DecisionEvidenceAdmission(
            **values,
            receipt_digest="sha256:" + "b" * 64,
            verification_bundle_digest="sha256:" + "c" * 64,
            verified_at=NOW - timedelta(minutes=10),
            valid_until=NOW + timedelta(hours=1),
        )


@dataclass
class MemoryProofStore:
    """Insert-only proof store double with the same record mapping as PostgreSQL."""

    admissions: list[tuple[IssuedEvidence, dict[str, Any]]] = field(default_factory=list)
    rejections: list[OperationalEvidenceRejectionRecord] = field(default_factory=list)

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
        if await self.attempt_outcome(issued.attempt_id) is not None:
            raise AssertionError("an attempt is written at most once")
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
        if await self.attempt_outcome(record.attempt_id) is not None:
            raise AssertionError("an attempt is written at most once")
        self.rejections.append(record)
        return record.record_digest

    async def newest_admissions(
        self, lookup_digest: str, pins_digests: frozenset[str], *, limit: int = 2
    ) -> tuple[RetainedAdmissionRow, ...]:
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

    async def rejection(self, *, record_digest: str, attempt_id: str) -> Mapping[str, Any] | None:
        for record in self.rejections:
            if record.record_digest == record_digest and record.attempt_id == attempt_id:
                return record.model_dump(mode="json")
        return None

    async def admission_by_receipt(self, receipt_digest: str) -> LineageRecord | None:
        for issued, _record in self.admissions:
            if issued.receipt.receipt_digest == receipt_digest:
                return LineageRecord(
                    purpose_id=issued.purpose_id,
                    lookup_digest=issued.lookup_digest,
                    receipt_digest=receipt_digest,
                    pins_digest=issued.pins.digest,
                    binding=issued.binding,
                    verified_at=issued.admission.verified_at,
                    valid_until=issued.admission.valid_until,
                )
        return None


def command_from_row(row: OperatorCommandRow) -> TestContextCommand:
    from fdai_service_contracts.test_context import context_command_from_record

    return context_command_from_record(row.record)


async def reviewed_history(outbox: OperatorOutbox) -> tuple[InMemoryStateStore, TestContextCommand]:
    """Record a real proposal and independent review through Mimir's store."""

    store = InMemoryStateStore()
    handler = TestContextCommandHandler(
        contexts=GovernedTestContextStore(
            store=store, admission=AllowingAdmission(), clock=lambda: NOW - timedelta(minutes=10)
        ),
        admission=AllowingAdmission(),
        clock=lambda: NOW - timedelta(minutes=10),
    )
    proposal = outbox.add(
        "propose",
        principal=REQUESTER,
        group=REQUESTER_GROUP,
        roles=("Contributor",),
        accepted_at=NOW - timedelta(minutes=20),
        expected_revision=0,
    )
    await handler.transition(
        command_from_row(proposal).model_dump(mode="json"), reviewed_by_var=False
    )
    review = outbox.add(
        "review",
        principal=REVIEWER,
        group=REVIEWER_GROUP,
        roles=("Approver",),
        accepted_at=NOW - timedelta(minutes=15),
        expected_revision=1,
    )
    await handler.transition(command_from_row(review).model_dump(mode="json"), reviewed_by_var=True)
    return store, command_from_row(review)
