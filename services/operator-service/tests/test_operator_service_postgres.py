"""Focused PostgreSQL projection parity tests for Operator Service."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fdai_operator_service.families.iam.contracts import (
    AccessGrantDecisionCommand,
    AccessGrantSnapshotQuery,
    AccessRequestCommand,
    AccessRequestQuery,
    AccessReviewCommand,
    AssignmentCaseQuery,
    AssignmentCreateCommand,
    AssignmentTransitionCommand,
    HilApprovalDecision,
    HilDecisionCommand,
    HilDecisionReceipt,
    IamPrincipal,
    ModelBindingDraftCommand,
    ModelBindingRequestCommand,
)
from fdai_operator_service.families.iam.errors import (
    IamConflictError,
    IamNotFoundError,
    IamPermissionError,
    IamUnavailableError,
)
from fdai_operator_service.families.iam.hil_callback_audit import (
    HilCallbackAuditPhase,
    HilCallbackAuditRecord,
    HilCallbackOutcome,
)
from fdai_operator_service.incident_projection import incident_outcome_metrics, incident_summary
from fdai_operator_service.postgres import (
    PostgresOperatorReadModel,
    PostgresOperatorReadModelConfig,
    _decode_incident_cursor,
    _encode_incident_cursor,
    _group_incident_rows,
    _psycopg_dsn,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
    StoredProposal,
    StoredStatePage,
    StoredStateRecord,
)
from fdai_operator_service.postgres_iam import PostgresIamAdapters, _command_payload
from fdai_operator_service.postgres_sql import (
    AGENT_INVENTORY_ACTIVITY_SQL,
    AGENT_OBSERVATION_ACTIVITY_SQL,
    AGENT_ONTOLOGY_ACTIVITY_SQL,
    AGENT_READ_ACTIVITY_SQL,
    AUDIT_PAGE_SQL,
    HIL_COUNT_SQL,
    HIL_PAGE_SQL,
    INCIDENT_CURRENT_PAGE_SQL,
    INCIDENT_PAGE_SQL,
    INCIDENT_SNAPSHOT_SQL,
    KPI_SAMPLE_SQL,
    LLM_USAGE_CONVERSATIONS_SQL,
    LLM_USAGE_RECORDS_SQL,
    LLM_USAGE_SUMMARIES_SQL,
    statement_identity,
)
from fdai_operator_service.projection_logic import hil_item
from fdai_operator_service.projections import ProjectionUnavailableError
from fdai_operator_service.routes import _sse_frame
from fdai_service_contracts import (
    AgentActivityQuery,
    AuditQuery,
    HilQueueQuery,
    IncidentAttentionQuery,
    IncidentQuery,
    ModelBindingPolicy,
    OperatorRole,
)

_NOW = datetime(2026, 8, 8, tzinfo=UTC)
_GRANT_EXPIRY = datetime(2099, 1, 1, tzinfo=UTC)


class CallbackAuditStore:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
        if key in self.values:
            return False
        self.values[key] = dict(value)
        return True

    async def read_state(self, key: str) -> dict[str, object] | None:
        return self.values.get(key)


class AccessProposalStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, object]] = {}

    async def append_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
    ) -> StoredProposal:
        key = f"{family}:{idempotency_key}"
        record = {
            "proposal_id": f"proposal-{len(self.records) + 1}",
            "accepted_at": (_NOW + timedelta(minutes=len(self.records))).isoformat(),
            "dispatch_status": "pending",
            "operation": operation,
            "principal_id": principal_id,
            "payload": dict(payload),
        }
        existing = self.records.get(key)
        if existing is not None:
            if existing["payload"] != record["payload"]:
                raise PostgresProposalConflict("idempotency key conflict")
            return StoredProposal(
                str(existing["proposal_id"]),
                str(existing["accepted_at"]),
                True,
                existing,
            )
        self.records[key] = record
        return StoredProposal(
            str(record["proposal_id"]),
            str(record["accepted_at"]),
            False,
            record,
        )

    async def read_state_page(
        self,
        *,
        prefix: str,
        limit: int,
        match_field: str | None = None,
        match_value: str | None = None,
    ) -> StoredStatePage:
        del prefix, match_field, match_value
        if not 1 <= limit <= 1_000:
            raise ValueError("state page limit MUST be between 1 and 1000")
        records = tuple(
            StoredStateRecord(key, value, _NOW)
            for key, value in reversed(tuple(self.records.items()))
        )
        return StoredStatePage(records=records[:limit], truncated=len(records) > limit)


def _iam_principal(oid: str) -> IamPrincipal:
    return IamPrincipal(oid=oid, roles=frozenset({OperatorRole.OWNER}))


@pytest.mark.asyncio
async def test_access_proposals_project_complete_requests_and_block_self_review() -> None:
    store = AccessProposalStore()
    adapter = PostgresIamAdapters(store)  # type: ignore[arg-type]
    submitted = await adapter.submit(
        AccessRequestCommand(
            principal=_iam_principal("owner-1"),
            idempotency_key="access-1",
            identity_provider="entra",
            target_subject_id="target-1",
            target_username="target@example.com",
            operation="grant",
            role=OperatorRole.READER,
            justification="Grant bounded console read access.",
        )
    )

    assert submitted["request_id"] == "proposal-1"
    assert submitted["status"] == "pending"
    page, total = await adapter.list_request_page(
        AccessRequestQuery(principal=_iam_principal("owner-2"), limit=50)
    )
    assert total == 1
    assert page[0]["target_subject_id"] == "target-1"

    with pytest.raises(IamPermissionError, match="MUST NOT"):
        await adapter.review(
            AccessReviewCommand(
                principal=_iam_principal("owner-1"),
                request_id="proposal-1",
                decision="approve",
                justification="Independent review is complete.",
            )
        )

    reviewed = await adapter.review(
        AccessReviewCommand(
            principal=_iam_principal("owner-2"),
            request_id="proposal-1",
            decision="approve",
            justification="Independent review is complete.",
        )
    )
    assert reviewed["status"] == "approved"
    assert reviewed["reviewed_by"] == "owner-2"


@pytest.mark.asyncio
async def test_assignment_proposals_project_revisioned_independent_review() -> None:
    store = AccessProposalStore()
    adapter = PostgresIamAdapters(store)  # type: ignore[arg-type]
    created = await adapter.create_case(
        AssignmentCreateCommand(
            principal=_iam_principal("owner-1"),
            idempotency_key="case-1",
            subject_provider="entra",
            subject_id="target-1",
            requested_role=OperatorRole.READER,
            duty_bindings=(
                {
                    "agent_name": "Odin",
                    "duty": "primary",
                    "scope_ref": "scope:platform",
                },
            ),
            goal_refs=(),
            justification="Assign bounded operational ownership.",
        )
    )
    submitted = await adapter.submit_for_review(
        AssignmentTransitionCommand(
            principal=_iam_principal("owner-1"),
            case_id=str(created["case_id"]),
            expected_revision=1,
        )
    )
    assert submitted["state"] == "pending_review"
    assert submitted["revision"] == 2

    reviewed = await adapter.review(
        AssignmentTransitionCommand(
            principal=_iam_principal("owner-2"),
            case_id=str(created["case_id"]),
            expected_revision=2,
            decision="approve",
        )
    )
    assert reviewed["state"] == "approved"
    assert reviewed["revision"] == 3
    projection = await adapter.assignment_projection(
        AssignmentCaseQuery(principal=_iam_principal("owner-2"), limit=50, offset=0)
    )
    assert projection["total"] == 1
    assert projection["items"][0]["case"]["state"] == "approved"  # type: ignore[index]


def _binding_policy(*, revision: int, active_digest: bool = True) -> dict[str, object]:
    policy: dict[str, object] = {
        "schema_version": "1.0.0",
        "environment": "staging",
        "revision": revision,
        "capabilities": {
            "t2.reasoner.primary": {
                "selection_mode": "pinned",
                "publisher": "OpenAI",
                "family": "gpt-4o",
                "version_policy": "latest-compatible",
                "sku": "GlobalProvisionedManaged",
                "capacity": {"unit": "ptu", "value": 30},
            }
        },
    }
    if active_digest:
        policy["expected_active_digest"] = "sha256:" + "a" * 64
    return policy


def _hil_row() -> dict[str, Any]:
    """One authoritative pending park record the projection can render."""
    return {
        "total_count": 1,
        "updated_at": _NOW,
        "value": {
            "approval_id": "approval-1",
            "parked_at": _NOW.isoformat(),
            "idempotency_key": "idem-1",
            "action": {
                "event_id": "00000000-0000-0000-0000-000000000001",
                "action_type": "compute.restart",
                "target_resource_ref": "resource-1",
                "credential": "must-not-leak",
            },
        },
    }


@pytest.mark.asyncio
async def test_callback_audit_persists_distinct_prepared_and_completed_records() -> None:
    store = CallbackAuditStore()
    adapter = PostgresIamAdapters(store)  # type: ignore[arg-type]
    common = {
        "callback_id": "hil-callback:one",
        "correlation_id": "correlation-one",
        "actor_identity_ref": "sha256:" + "a" * 64,
        "authority_basis": "teams_sso_obo+entra_app_role",
        "recorded_at": _NOW,
    }
    prepared = HilCallbackAuditRecord(
        phase=HilCallbackAuditPhase.PREPARED,
        outcome=HilCallbackOutcome.PENDING,
        **common,
    )
    completed = HilCallbackAuditRecord(
        phase=HilCallbackAuditPhase.COMPLETED,
        outcome=HilCallbackOutcome.ACCEPTED,
        **common,
    )

    await adapter.append_callback_audit(prepared)
    await adapter.append_callback_audit(completed)
    await adapter.append_callback_audit(replace(prepared, recorded_at=_NOW + timedelta(seconds=1)))
    await adapter.append_callback_audit(replace(completed, recorded_at=_NOW + timedelta(seconds=2)))

    assert len(store.values) == 2
    assert {value["phase"] for value in store.values.values()} == {
        "prepared",
        "completed",
    }
    assert {value["correlation_id"] for value in store.values.values()} == {"correlation-one"}
    assert all("justification" not in value for value in store.values.values())
    assert {value["recorded_at"] for value in store.values.values()} == {_NOW.isoformat()}


@pytest.mark.asyncio
async def test_hil_context_reader_preserves_original_context_after_timeout() -> None:
    store = CallbackAuditStore()
    store.values["hil_park:approval-1"] = {
        "status": "resolved",
        "decision": "timeout",
        "approval_id": "approval-1",
        "idempotency_key": "idem-1",
        "submitter_oid": "submitter-1",
        "correlation_id": "correlation-1",
        "request_fingerprint": "action-hash-1",
        "approval_context": {
            "reasons": ["Workflow step approval requires one approver."],
            "blast_radius_summary": "1 workflow target",
            "ttl_seconds": 120,
            "expires_at": _GRANT_EXPIRY.isoformat(),
        },
        "metadata": {
            "decision_route": "workflow",
            "required_role": "approver",
        },
    }

    context = await PostgresIamAdapters(store).get_callback_context(  # type: ignore[arg-type]
        "approval-1"
    )

    assert context is not None
    assert context.correlation_id == "correlation-1"
    assert context.idempotency_key == "idem-1"
    assert context.action_hash == "action-hash-1"
    assert context.expires_at == _GRANT_EXPIRY
    assert context.metadata == {
        "decision_route": "workflow",
        "required_role": "approver",
    }


class HilDecisionRecoveryStore:
    """Model proposal-first persistence and a separately raced receipt state."""

    def __init__(self) -> None:
        self.proposal: dict[str, object] | None = None
        self.receipt: dict[str, object] | None = None
        self.fail_receipt_once = False
        self.raced_receipt: dict[str, object] | None = None

    async def find_state(
        self,
        *,
        prefix: str,
        field: str,
        value: str,
    ) -> dict[str, object] | None:
        assert prefix == "hil_park:"
        assert field == "idempotency_key"
        return {
            "approval_id": "approval-1",
            "idempotency_key": value,
        }

    async def append_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
    ) -> StoredProposal:
        del family, operation, principal_id
        candidate = {"idempotency_key": idempotency_key, "payload": dict(payload)}
        if self.proposal is not None and self.proposal != candidate:
            raise PostgresProposalConflict("conflicting proposal")
        duplicate = self.proposal is not None
        self.proposal = candidate
        return StoredProposal(
            proposal_id="operator-hil-receipt",
            accepted_at=_NOW.isoformat(),
            duplicate=duplicate,
            record=candidate,
        )

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
        assert key == "operator-hil-decision:approval-1"
        if self.fail_receipt_once:
            self.fail_receipt_once = False
            raise PostgresFamilyStoreUnavailable("interrupted receipt write")
        if self.raced_receipt is not None:
            self.receipt = self.raced_receipt
            return False
        if self.receipt is not None:
            return False
        self.receipt = dict(value)
        return True

    async def read_state(self, key: str) -> dict[str, object] | None:
        assert key == "operator-hil-decision:approval-1"
        return self.receipt


def _hil_decision_command() -> HilDecisionCommand:
    return HilDecisionCommand(
        idempotency_key="hil-key-1",
        decision=HilApprovalDecision.APPROVE,
        approver_oid="approver-1",
        justification="Verified impact and rollback.",
        decided_at=_NOW,
    )


@pytest.mark.asyncio
async def test_hil_decision_recovers_after_proposal_precedes_receipt_state() -> None:
    store = HilDecisionRecoveryStore()
    store.fail_receipt_once = True
    adapter = PostgresIamAdapters(store)  # type: ignore[arg-type]

    with pytest.raises(IamUnavailableError, match="receipt store"):
        await adapter.record_decision(_hil_decision_command())
    recovered = await adapter.record_decision(_hil_decision_command())

    assert recovered.decided_at == _NOW
    assert recovered.justification == "Verified impact and rollback."
    assert store.proposal is not None
    assert store.receipt is not None


@pytest.mark.asyncio
async def test_hil_decision_rejects_conflicting_receipt_create_race() -> None:
    store = HilDecisionRecoveryStore()
    store.raced_receipt = {
        "approval_id": "approval-1",
        "idempotency_key": "hil-key-1",
        "decision": "reject",
        "approver_oid": "approver-2",
        "decided_at": _NOW.isoformat(),
        "receipt_ref": "raced-receipt",
    }

    with pytest.raises(IamConflictError, match="concurrent durable receipt"):
        await PostgresIamAdapters(store).record_decision(  # type: ignore[arg-type]
            _hil_decision_command()
        )


@pytest.mark.asyncio
async def test_newly_signed_retry_after_the_replay_window_recovers_the_proposal() -> None:
    """A re-signed retry carries a new observation time for the same decision.

    The internal callback replay window is five minutes. Recovering a decision
    whose receipt state never landed therefore requires a fresh signature and a
    fresh ``decided_at``. The durable proposal identity excludes that
    timestamp, so the retry recovers the original proposal instead of
    conflicting with it.
    """
    store = HilDecisionRecoveryStore()
    store.fail_receipt_once = True
    adapter = PostgresIamAdapters(store)  # type: ignore[arg-type]

    with pytest.raises(IamUnavailableError, match="receipt store"):
        await adapter.record_decision(_hil_decision_command())
    original_proposal = dict(store.proposal or {})

    later = _NOW + timedelta(minutes=6)
    recovered = await adapter.record_decision(replace(_hil_decision_command(), decided_at=later))

    assert recovered.decided_at == later
    assert recovered.receipt_ref == "operator-hil-receipt"
    assert store.proposal == original_proposal
    payload = original_proposal["payload"]
    assert isinstance(payload, Mapping)
    assert "decided_at" not in payload
    assert payload["approval_id"] == "approval-1"
    assert payload["decision"] == "approve"
    assert payload["approver_oid"] == "approver-1"
    assert str(payload["justification_digest"]).startswith("sha256:")


@pytest.mark.asyncio
async def test_conflicting_decision_actor_or_justification_is_still_refused() -> None:
    for override in (
        {"decision": HilApprovalDecision.REJECT},
        {"approver_oid": "approver-2"},
        {"justification": "Different recorded reasoning."},
    ):
        store = HilDecisionRecoveryStore()
        store.fail_receipt_once = True
        adapter = PostgresIamAdapters(store)  # type: ignore[arg-type]
        with pytest.raises(IamUnavailableError):
            await adapter.record_decision(_hil_decision_command())

        with pytest.raises(IamConflictError):
            await adapter.record_decision(replace(_hil_decision_command(), **override))


@pytest.mark.asyncio
async def test_case_only_actor_difference_recovers_the_same_durable_decision() -> None:
    store = HilDecisionRecoveryStore()
    store.fail_receipt_once = True
    adapter = PostgresIamAdapters(store)  # type: ignore[arg-type]
    with pytest.raises(IamUnavailableError):
        await adapter.record_decision(_hil_decision_command())

    recovered = await adapter.record_decision(
        replace(_hil_decision_command(), approver_oid="Approver-1")
    )

    assert recovered.approver_oid == "Approver-1"


class HilDeliveryStateStore:
    """Model the durable decision receipt with monotonic delivery state."""

    def __init__(self, receipt: Mapping[str, object] | None = None) -> None:
        self.values: dict[str, dict[str, object]] = {}
        if receipt is not None:
            self.values["operator-hil-decision:approval-1"] = dict(receipt)
        self.writes = 0

    async def read_state(self, key: str) -> dict[str, object] | None:
        return self.values.get(key)

    async def write_state(self, key: str, value: Mapping[str, object]) -> None:
        self.writes += 1
        self.values[key] = dict(value)


def _stored_receipt(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "approval_id": "approval-1",
        "idempotency_key": "hil-key-1",
        "decision": "approve",
        "approver_oid": "approver-1",
        "decided_at": _NOW.isoformat(),
        "receipt_ref": "receipt-1",
        "justification": "Verified impact and rollback.",
        "already_recorded": False,
        "delivered": False,
    }
    value.update(overrides)
    return value


@pytest.mark.asyncio
async def test_mark_delivered_is_monotonic_and_never_regresses() -> None:
    store = HilDeliveryStateStore(_stored_receipt(delivered=True))
    adapter = PostgresIamAdapters(store)  # type: ignore[arg-type]

    stale = await adapter.mark_delivered(
        HilDecisionReceipt(
            approval_id="approval-1",
            idempotency_key="hil-key-1",
            decision=HilApprovalDecision.APPROVE,
            approver_oid="approver-1",
            decided_at=_NOW,
            receipt_ref="receipt-1",
            delivered=False,
        )
    )

    assert stale.delivered is True
    assert store.writes == 0
    assert store.values["operator-hil-decision:approval-1"]["delivered"] is True


@pytest.mark.asyncio
async def test_mark_delivered_advances_the_stored_receipt_once() -> None:
    store = HilDeliveryStateStore(_stored_receipt())
    adapter = PostgresIamAdapters(store)  # type: ignore[arg-type]
    receipt = HilDecisionReceipt(
        approval_id="approval-1",
        idempotency_key="hil-key-1",
        decision=HilApprovalDecision.APPROVE,
        approver_oid="approver-1",
        decided_at=_NOW,
        receipt_ref="receipt-1",
    )

    first = await adapter.mark_delivered(receipt)
    second = await adapter.mark_delivered(receipt)

    assert first.delivered is True
    assert second.delivered is True
    assert store.writes == 1


class ReadinessPostgresFamilyStore(PostgresFamilyStore):
    """Capture the bounded readiness statement without opening PostgreSQL."""

    def __init__(self, row: dict[str, object]) -> None:
        super().__init__(
            PostgresFamilyStoreConfig(
                dsn="postgresql://example.invalid/db",
                role="fdai_operator",
            )
        )
        self.row = row
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        self.calls.append((statement, parameters))
        return [self.row]


class ProjectionPostgresFamilyStore(PostgresFamilyStore):
    """Return one Settings projection without opening PostgreSQL."""

    def __init__(self, payload: dict[str, object]) -> None:
        super().__init__(
            PostgresFamilyStoreConfig(
                dsn="postgresql://example.invalid/db",
                role="fdai_operator",
            )
        )
        self.payload = payload

    async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
        assert (family, operation) == ("iam", "model-settings")
        return self.payload

    async def read_state(self, key: str) -> dict[str, object] | None:
        assert key == "operator-model-binding-policy:current"
        return None


class ModelBindingPostgresFamilyStore(ProjectionPostgresFamilyStore):
    """Keep one model-binding state and proposal ledger without PostgreSQL I/O."""

    def __init__(self) -> None:
        super().__init__(
            {
                "environment": "staging",
                "resolved_metadata": {"digest": "sha256:" + "a" * 64},
                "web_search": {},
            }
        )
        self.state: dict[str, object] | None = None
        self.proposals: list[tuple[str, Mapping[str, object]]] = []
        self.accepted: dict[str, StoredProposal] = {}

    async def read_state(self, key: str) -> dict[str, object] | None:
        assert key == "operator-model-binding-policy:current"
        return self.state

    async def append_revisioned_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
        state_key: str,
        state_value: Mapping[str, object],
        expected_revision: int,
    ) -> StoredProposal:
        del family, principal_id, state_key
        current_revision = int(self.state.get("revision", 0)) if self.state else 0
        if current_revision != expected_revision:
            raise PostgresProposalConflict("state revision conflict")
        self.state = dict(state_value)
        self.proposals.append((operation, payload))
        return StoredProposal(
            proposal_id=f"proposal-{idempotency_key}",
            accepted_at=_NOW.isoformat(),
            duplicate=False,
            record={},
        )

    async def append_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
    ) -> StoredProposal:
        del family, principal_id
        existing = self.accepted.get(idempotency_key)
        if existing is not None:
            return StoredProposal(
                proposal_id=existing.proposal_id,
                accepted_at=existing.accepted_at,
                duplicate=True,
                record=existing.record,
            )
        self.proposals.append((operation, payload))
        stored = StoredProposal(
            proposal_id=f"proposal-{idempotency_key}",
            accepted_at=_NOW.isoformat(),
            duplicate=False,
            record={},
        )
        self.accepted[idempotency_key] = stored
        return stored


class AccessGrantStatePostgresFamilyStore(PostgresFamilyStore):
    """Return authoritative grant-request records without opening PostgreSQL."""

    def __init__(
        self,
        records: tuple[StoredStateRecord, ...],
        *,
        truncated: bool = False,
    ) -> None:
        super().__init__(
            PostgresFamilyStoreConfig(
                dsn="postgresql://example.invalid/db",
                role="fdai_operator",
            )
        )
        self.records = records
        self.truncated = truncated
        self.prefixes: list[str] = []
        self.matches: list[tuple[str | None, str | None]] = []

    async def read_state_page(
        self,
        *,
        prefix: str,
        limit: int,
        match_field: str | None = None,
        match_value: str | None = None,
    ) -> StoredStatePage:
        self.prefixes.append(prefix)
        self.matches.append((match_field, match_value))
        return StoredStatePage(records=self.records[:limit], truncated=self.truncated)


def _grant_state(
    request_id: str,
    *,
    requester_ref: str,
    approver_roles: list[str],
    status: str = "pending",
    expires_at: datetime = _GRANT_EXPIRY,
    updated_at: datetime = _NOW,
    requested_at: datetime = _NOW,
) -> StoredStateRecord:
    return StoredStateRecord(
        key=f"execution-authorization:grant-request:{request_id}",
        value={
            "request_id": request_id,
            "original_action_id": f"action-{request_id}",
            "capability_id": "ops.scale-out",
            "scope_ref": "scope://subscription/resource-group",
            "grant_mode": "exact",
            "requested_at": requested_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "quorum": 2,
            "status": status,
            "revision": 1,
            "requester_ref": requester_ref,
            "approver_roles": approver_roles,
        },
        updated_at=updated_at,
    )


@pytest.mark.asyncio
async def test_access_grant_snapshot_shows_the_longest_waiting_request_first() -> None:
    store = AccessGrantStatePostgresFamilyStore(
        (
            _grant_state(
                "newest",
                requester_ref="alice",
                approver_roles=["Approver"],
                requested_at=datetime(2026, 8, 8, tzinfo=UTC),
                updated_at=datetime(2026, 8, 8, tzinfo=UTC),
            ),
            _grant_state(
                "oldest",
                requester_ref="alice",
                approver_roles=["Approver"],
                requested_at=datetime(2026, 8, 1, tzinfo=UTC),
                updated_at=datetime(2026, 8, 2, tzinfo=UTC),
            ),
        )
    )

    snapshot = await PostgresIamAdapters(store).snapshot(
        AccessGrantSnapshotQuery(
            reviewer_ref="bob",
            reviewer_roles=frozenset({"approver"}),
            after_sequence=None,
            limit=1,
        )
    )

    assert [item.request_id for item in snapshot.requests] == ["oldest"]


@pytest.mark.asyncio
async def test_access_grant_snapshot_hides_requests_the_reviewer_may_not_review() -> None:
    store = AccessGrantStatePostgresFamilyStore(
        (
            _grant_state("reviewable", requester_ref="alice", approver_roles=["Approver"]),
            _grant_state("self-owned", requester_ref="Bob", approver_roles=["Approver"]),
            _grant_state("other-role", requester_ref="alice", approver_roles=["Owner"]),
            _grant_state(
                "already-decided",
                requester_ref="alice",
                approver_roles=["Approver"],
                status="approved",
            ),
            _grant_state(
                "expired",
                requester_ref="alice",
                approver_roles=["Approver"],
                expires_at=datetime(2026, 8, 7, tzinfo=UTC),
            ),
        )
    )

    snapshot = await PostgresIamAdapters(store).snapshot(
        AccessGrantSnapshotQuery(
            reviewer_ref="bob",
            reviewer_roles=frozenset({"approver"}),
            after_sequence=None,
        )
    )

    assert store.prefixes == ["execution-authorization:grant-request:"]
    assert store.matches == [("status", "pending")]
    assert [item.request_id for item in snapshot.requests] == ["reviewable"]
    assert snapshot.requests[0].correlation_id == "action-reviewable"
    assert "requester_ref" not in snapshot.requests[0].to_dict()
    assert "approver_roles" not in snapshot.requests[0].to_dict()


@pytest.mark.asyncio
async def test_access_grant_snapshot_without_reviewer_roles_shows_nothing() -> None:
    store = AccessGrantStatePostgresFamilyStore(
        (_grant_state("reviewable", requester_ref="alice", approver_roles=["Approver"]),)
    )

    snapshot = await PostgresIamAdapters(store).snapshot(
        AccessGrantSnapshotQuery(
            reviewer_ref="bob",
            reviewer_roles=frozenset(),
            after_sequence=None,
        )
    )

    assert snapshot.requests == ()


@pytest.mark.asyncio
async def test_access_grant_snapshot_is_empty_rather_than_unavailable_without_records() -> None:
    snapshot = await PostgresIamAdapters(AccessGrantStatePostgresFamilyStore(())).snapshot(
        AccessGrantSnapshotQuery(
            reviewer_ref="bob",
            reviewer_roles=frozenset({"approver"}),
            after_sequence=None,
        )
    )

    assert snapshot.sequence == 0
    assert snapshot.requests == ()


@pytest.mark.asyncio
async def test_access_grant_snapshot_cursor_does_not_regress_when_the_queue_empties() -> None:
    cursor = int(_NOW.timestamp() * 1_000_000)

    snapshot = await PostgresIamAdapters(AccessGrantStatePostgresFamilyStore(())).snapshot(
        AccessGrantSnapshotQuery(
            reviewer_ref="bob",
            reviewer_roles=frozenset({"approver"}),
            after_sequence=cursor,
        )
    )

    assert snapshot.sequence == cursor
    assert snapshot.requests == ()


class RecordingProposalPostgresFamilyStore(PostgresFamilyStore):
    """Capture appended proposal idempotency keys without opening PostgreSQL."""

    def __init__(self, record: dict[str, object] | None = None) -> None:
        super().__init__(
            PostgresFamilyStoreConfig(
                dsn="postgresql://example.invalid/db",
                role="fdai_operator",
            )
        )
        self.record = record if record is not None else _grant_record()
        self.keys: list[str] = []

    async def read_state(self, key: str) -> dict[str, object] | None:
        del key
        return self.record

    async def append_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
    ) -> StoredProposal:
        del family, operation, principal_id, payload
        self.keys.append(idempotency_key)
        return StoredProposal(
            proposal_id="operator-test",
            accepted_at=_NOW.isoformat(),
            duplicate=False,
            record={},
        )


def _grant_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "status": "pending",
        "quorum": 2,
        "revision": 3,
        "approved_by": ["reviewer-a"],
        "requester_ref": "requester-1",
        "approver_roles": ["Approver"],
        "expires_at": _GRANT_EXPIRY.isoformat(),
    }
    record.update(overrides)
    return record


def _decision(reviewer_ref: str, *, expected_revision: int = 1) -> AccessGrantDecisionCommand:
    return AccessGrantDecisionCommand(
        request_id="grant-1",
        reviewer_ref=reviewer_ref,
        reviewer_roles=frozenset({"approver"}),
        decision="approve",
        reason="approved for the measured window",
        expected_revision=expected_revision,
        decided_at=_NOW,
    )


@pytest.mark.asyncio
async def test_distinct_reviewers_append_distinct_grant_decision_proposals() -> None:
    store = RecordingProposalPostgresFamilyStore()
    adapters = PostgresIamAdapters(store)

    await adapters.decide(_decision("reviewer-a"))
    await adapters.decide(_decision("reviewer-b"))
    await adapters.decide(_decision("reviewer-a"))
    await adapters.decide(_decision("reviewer-a", expected_revision=2))

    assert store.keys[0] != store.keys[1]
    assert store.keys[0] == store.keys[2]
    assert store.keys[3] not in store.keys[:3]
    assert all(key.startswith("grant-1:") for key in store.keys)


@pytest.mark.asyncio
async def test_grant_decision_receipt_reports_the_authoritative_approval_policy() -> None:
    store = RecordingProposalPostgresFamilyStore()

    receipt = await PostgresIamAdapters(store).decide(_decision("reviewer-b"))

    assert (receipt.quorum, receipt.approved_count, receipt.revision) == (2, 1, 3)


@pytest.mark.asyncio
async def test_grant_decision_is_refused_for_an_unknown_request() -> None:
    store = RecordingProposalPostgresFamilyStore(record=None)
    store.record = None

    with pytest.raises(IamNotFoundError):
        await PostgresIamAdapters(store).decide(_decision("reviewer-b"))

    assert store.keys == []


@pytest.mark.asyncio
async def test_grant_decision_is_refused_once_the_request_left_pending() -> None:
    store = RecordingProposalPostgresFamilyStore(_grant_record(status="approved"))

    with pytest.raises(IamConflictError):
        await PostgresIamAdapters(store).decide(_decision("reviewer-b"))

    assert store.keys == []


@pytest.mark.asyncio
async def test_grant_decision_refuses_a_self_approval_before_queuing_it() -> None:
    store = RecordingProposalPostgresFamilyStore()

    with pytest.raises(IamPermissionError):
        await PostgresIamAdapters(store).decide(_decision("Requester-1"))

    assert store.keys == []


@pytest.mark.asyncio
async def test_grant_decision_refuses_a_reviewer_without_an_approver_role() -> None:
    store = RecordingProposalPostgresFamilyStore(_grant_record(approver_roles=["Owner"]))

    with pytest.raises(IamPermissionError):
        await PostgresIamAdapters(store).decide(_decision("reviewer-b"))

    assert store.keys == []


@pytest.mark.asyncio
async def test_grant_decision_refuses_an_expired_request() -> None:
    store = RecordingProposalPostgresFamilyStore(
        _grant_record(expires_at=datetime(2026, 8, 7, tzinfo=UTC).isoformat())
    )

    with pytest.raises(IamPermissionError):
        await PostgresIamAdapters(store).decide(_decision("reviewer-b"))

    assert store.keys == []


def test_iam_command_payload_is_deterministic_and_machine_readable() -> None:
    command = AccessGrantDecisionCommand(
        request_id="grant-1",
        reviewer_ref="reviewer-b",
        reviewer_roles=frozenset({"owner", "approver", "auditor"}),
        decision="approve",
        reason="approved for the measured window",
        expected_revision=3,
        decided_at=_NOW,
    )

    payload = _command_payload(command)

    assert payload["reviewer_roles"] == ["approver", "auditor", "owner"]
    assert payload["decided_at"] == _NOW.isoformat()


@pytest.mark.asyncio
async def test_access_grant_snapshot_fails_closed_when_the_scan_is_truncated() -> None:
    store = AccessGrantStatePostgresFamilyStore(
        (_grant_state("reviewable", requester_ref="alice", approver_roles=["Approver"]),),
        truncated=True,
    )

    with pytest.raises(IamUnavailableError):
        await PostgresIamAdapters(store).snapshot(
            AccessGrantSnapshotQuery(
                reviewer_ref="bob",
                reviewer_roles=frozenset({"approver"}),
                after_sequence=None,
            )
        )


@pytest.mark.parametrize("field", ["quorum", "revision"])
@pytest.mark.asyncio
async def test_access_grant_snapshot_reports_a_malformed_counter_as_unavailable(
    field: str,
) -> None:
    record = _grant_state("reviewable", requester_ref="alice", approver_roles=["Approver"])
    broken = StoredStateRecord(
        key=record.key,
        value={**record.value, field: "not-a-number"},
        updated_at=record.updated_at,
    )

    with pytest.raises(IamUnavailableError):
        await PostgresIamAdapters(AccessGrantStatePostgresFamilyStore((broken,))).snapshot(
            AccessGrantSnapshotQuery(
                reviewer_ref="bob",
                reviewer_roles=frozenset({"approver"}),
                after_sequence=None,
            )
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", ""),
        ("request_id", "has space"),
        ("original_action_id", None),
        ("capability_id", "x" * 257),
        ("grant_mode", ""),
        ("scope_ref", "subscription/resource-group"),
        ("scope_ref", "scope://control\tcharacter"),
        ("quorum", 0),
    ],
)
@pytest.mark.asyncio
async def test_access_grant_snapshot_rejects_a_record_the_browser_would_discard(
    field: str,
    value: object,
) -> None:
    record = _grant_state("reviewable", requester_ref="alice", approver_roles=["Approver"])
    broken = StoredStateRecord(
        key=record.key,
        value={**record.value, field: value},
        updated_at=record.updated_at,
    )

    with pytest.raises(IamUnavailableError):
        await PostgresIamAdapters(AccessGrantStatePostgresFamilyStore((broken,))).snapshot(
            AccessGrantSnapshotQuery(
                reviewer_ref="bob",
                reviewer_roles=frozenset({"approver"}),
                after_sequence=None,
            )
        )


def test_sqlalchemy_psycopg_dsn_is_normalized_for_direct_driver_use() -> None:
    assert _psycopg_dsn("postgresql+psycopg://user@example.invalid/db") == (
        "postgresql://user@example.invalid/db"
    )
    assert _psycopg_dsn("postgresql://user@example.invalid/db") == (
        "postgresql://user@example.invalid/db"
    )


@pytest.mark.parametrize(
    "dsn",
    ["postgresql+psycopg://", "postgresql://", "postgres://"],
)
@pytest.mark.parametrize(
    "config_type",
    [PostgresOperatorReadModelConfig, PostgresFamilyStoreConfig],
)
def test_postgres_configs_reject_targetless_dsn(
    dsn: str,
    config_type: type[PostgresOperatorReadModelConfig] | type[PostgresFamilyStoreConfig],
) -> None:
    with pytest.raises(ValueError, match="MUST include a connection target"):
        config_type(dsn)


@pytest.mark.asyncio
async def test_operator_readiness_verifies_exact_projection_and_conversation_privileges() -> None:
    store = ReadinessPostgresFamilyStore({"ready": True})

    assert await store.probe_readiness() is True

    statement, parameters = store.calls[-1]
    assert parameters == {"expected_role": "fdai_operator"}
    for fragment in (
        "current_user = %(expected_role)s",
        "NOT login_role.rolsuper",
        "NOT login_role.rolcreaterole",
        "NOT login_role.rolcreatedb",
        "NOT login_role.rolreplication",
        "NOT login_role.rolbypassrls",
        "NOT pg_has_role(current_user, 'pg_read_all_data', 'MEMBER')",
        "NOT pg_has_role(current_user, 'pg_write_all_data', 'MEMBER')",
        "has_table_privilege(current_user, 'audit_log', 'SELECT')",
        "has_table_privilege(current_user, 'state_kv', 'SELECT')",
        "has_table_privilege(current_user, 'state_kv', 'INSERT')",
        "has_table_privilege(current_user, 'state_kv', 'UPDATE')",
        "NOT has_table_privilege(current_user, 'audit_log', 'INSERT')",
        "NOT has_table_privilege(current_user, 'audit_log', 'UPDATE')",
        "NOT has_table_privilege(current_user, 'state_kv', 'DELETE')",
        "has_table_privilege(current_user, 'llm_invocation', 'SELECT')",
        "NOT has_table_privilege(current_user, 'llm_invocation', 'INSERT')",
        "NOT has_table_privilege(current_user, 'llm_invocation', 'UPDATE')",
        "NOT has_table_privilege(current_user, 'llm_invocation', 'DELETE')",
        "has_table_privilege(current_user, 'inventory_snapshot', 'SELECT')",
        "has_table_privilege(current_user, 'inventory_snapshot_resource', 'SELECT')",
        "has_table_privilege(current_user, 'inventory_snapshot_link', 'SELECT')",
        "has_table_privilege(current_user, 'inventory_active', 'SELECT')",
        "has_table_privilege(current_user, 'inventory_realtime_resource', 'SELECT')",
        "has_table_privilege(current_user, 'inventory_realtime_link', 'SELECT')",
        "has_table_privilege(current_user, 'conversation_record', 'SELECT')",
        "has_table_privilege(current_user, 'conversation_record', 'INSERT')",
        "has_table_privilege(current_user, 'conversation_record', 'UPDATE')",
        "has_table_privilege(current_user, 'conversation_turn', 'SELECT')",
        "has_table_privilege(current_user, 'conversation_turn', 'INSERT')",
        "has_table_privilege(current_user, 'operator_background_task_projection', 'SELECT')",
        "has_table_privilege(current_user, 'operator_background_task_projection', 'INSERT')",
        "has_table_privilege(current_user, 'operator_background_task_projection', 'UPDATE')",
        "has_table_privilege(current_user, 'operator_background_task_projection', 'DELETE')",
        "has_table_privilege(current_user, 'operator_background_task_progress', 'SELECT')",
        "has_table_privilege(current_user, 'operator_background_task_progress', 'INSERT')",
        "has_table_privilege(current_user, 'operator_background_task_progress', 'DELETE')",
        "current_user, 'operator_background_task_progress', 'task_id', 'UPDATE'",
        "NOT has_table_privilege(current_user, 'background_task_attempt', 'SELECT')",
        "NOT has_table_privilege(current_user, 'background_task_progress', 'SELECT')",
        "NOT has_table_privilege(current_user, 'background_task_completion', 'SELECT')",
        "current_user, 'operator_read_investigation_completion', 'SELECT'",
        "current_user, 'operator_read_investigation_completion', 'INSERT'",
        "has_table_privilege(current_user, 'operator_read_investigation_completion', 'DELETE')",
        "current_user, 'operator_read_investigation_completion', 'completion_id', 'UPDATE'",
        "current_user, 'operator_read_investigation_completion_sequence_seq', 'USAGE'",
        "NOT has_schema_privilege(current_user, 'public', 'CREATE')",
    ):
        assert fragment in statement
    for table in (
        "background_task_attempt",
        "background_task_progress",
        "background_task_completion",
        "inventory_snapshot",
        "inventory_snapshot_resource",
        "inventory_snapshot_link",
        "inventory_active",
        "inventory_realtime_resource",
        "inventory_realtime_link",
        "process_runtime",
        "process_event",
        "automation_blueprint_candidate",
        "conversation_assurance_assessment",
        "conversation_assurance_dispute",
        "forecast_episode",
        "forecast_publication_outbox",
        "operator_memory",
        "memory_compaction_candidate",
        "skill_source",
        "skill_source_refresh_state",
    ):
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            assert f"NOT has_table_privilege(current_user, '{table}', '{privilege}')" in statement
    for privilege in ("DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        assert (
            f"NOT has_table_privilege(current_user, 'conversation_record', '{privilege}')"
            in statement
        )
    for privilege in ("UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        assert (
            f"NOT has_table_privilege(current_user, 'conversation_turn', '{privilege}')"
            in statement
        )
    assert (
        "NOT has_table_privilege(current_user, 'operator_background_task_progress', 'UPDATE')"
        in statement
    )
    for privilege in ("TRUNCATE", "REFERENCES", "TRIGGER"):
        assert (
            "NOT has_table_privilege("
            f"current_user, 'operator_background_task_projection', '{privilege}'" in statement
        )
        assert (
            "NOT has_table_privilege("
            f"current_user, 'operator_background_task_progress', '{privilege}'" in statement
        )
    for privilege in ("UPDATE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        assert "NOT has_table_privilege(" in statement
        assert f"current_user, 'operator_read_investigation_completion', '{privilege}'" in statement
    assert "INSERT,UPDATE,DELETE" not in statement
    for mutation in ("INSERT INTO", "UPDATE state_kv", "DELETE FROM"):
        assert mutation not in statement


@pytest.mark.asyncio
async def test_operator_readiness_rejects_role_or_privilege_failure() -> None:
    store = ReadinessPostgresFamilyStore({"ready": False})

    assert await store.probe_readiness() is False


@pytest.mark.asyncio
async def test_model_projection_injects_principal_capability_at_nested_contract() -> None:
    adapters = PostgresIamAdapters(
        ProjectionPostgresFamilyStore({"web_search": {"available": True}})
    )

    projection = await adapters.projection(
        "principal-1",
        can_manage_web_search=True,
    )

    assert projection["web_search"] == {"available": True, "can_manage": True}
    assert "can_manage_web_search" not in projection
    assert projection["binding_policy"] == {
        "environment": "unspecified",
        "revision": 0,
        "state": "not-configured",
        "policy": None,
        "policy_digest": None,
        "can_manage": False,
        "execution_authority": False,
    }


@pytest.mark.asyncio
async def test_model_binding_draft_persists_and_queues_exact_assessment_and_plan() -> None:
    store = ModelBindingPostgresFamilyStore()
    adapters = PostgresIamAdapters(store)
    policy = ModelBindingPolicy.model_validate(_binding_policy(revision=1))
    draft = ModelBindingDraftCommand(
        actor_id="owner-1",
        policy=policy.model_dump(mode="json", exclude_none=True),
        policy_digest=policy.digest(),
        expected_revision=0,
        idempotency_key="draft-1",
    )

    saved = await adapters.save_binding_policy(draft)
    projection = await adapters.projection(
        "owner-1",
        can_manage_model_bindings=True,
    )
    request = ModelBindingRequestCommand(
        actor_id="owner-1",
        environment="staging",
        policy_revision=1,
        policy_digest=policy.digest(),
        idempotency_key="assess-1",
    )
    assessed = await adapters.request_binding_assessment(request)
    planned = await adapters.request_binding_plan(
        ModelBindingRequestCommand(
            actor_id="owner-1",
            environment="staging",
            policy_revision=1,
            policy_digest=policy.digest(),
            idempotency_key="plan-1",
        )
    )

    assert saved["state"] == "draft"
    assert projection["binding_policy"]["can_manage"] is True  # type: ignore[index]
    assert assessed["state"] == "assessment-requested"
    assert planned["state"] == "plan-requested"
    assert all(receipt["execution_authority"] is False for receipt in (saved, assessed, planned))
    assert [operation for operation, _payload in store.proposals] == [
        "model-settings.binding-policy.draft",
        "model-settings.binding-policy.assessment",
        "model-settings.binding-policy.plan",
    ]


@pytest.mark.asyncio
async def test_model_binding_projection_does_not_expose_unknown_stored_fields() -> None:
    store = ModelBindingPostgresFamilyStore()
    adapters = PostgresIamAdapters(store)
    policy = ModelBindingPolicy.model_validate(_binding_policy(revision=1))
    await adapters.save_binding_policy(
        ModelBindingDraftCommand(
            actor_id="owner-1",
            policy=policy.model_dump(mode="json", exclude_none=True),
            policy_digest=policy.digest(),
            expected_revision=0,
            idempotency_key="draft-1",
        )
    )
    assert store.state is not None
    store.state["unexpected_secret"] = "must-not-cross-the-projection-boundary"

    projection = await adapters.projection("owner-1", can_manage_model_bindings=True)

    binding_policy = projection["binding_policy"]
    assert isinstance(binding_policy, dict)
    assert "unexpected_secret" not in binding_policy


@pytest.mark.asyncio
async def test_model_binding_rejects_stale_revision_and_unbound_plan() -> None:
    store = ModelBindingPostgresFamilyStore()
    adapters = PostgresIamAdapters(store)
    initial = ModelBindingPolicy.model_validate(_binding_policy(revision=1))
    await adapters.save_binding_policy(
        ModelBindingDraftCommand(
            actor_id="owner-1",
            policy=initial.model_dump(mode="json", exclude_none=True),
            policy_digest=initial.digest(),
            expected_revision=0,
            idempotency_key="draft-1",
        )
    )
    stale = ModelBindingPolicy.model_validate(_binding_policy(revision=1))
    with pytest.raises(IamConflictError, match="revision"):
        await adapters.save_binding_policy(
            ModelBindingDraftCommand(
                actor_id="owner-1",
                policy=stale.model_dump(mode="json", exclude_none=True),
                policy_digest=stale.digest(),
                expected_revision=0,
                idempotency_key="draft-stale",
            )
        )

    no_active_digest = ModelBindingPolicy.model_validate(
        _binding_policy(revision=2, active_digest=False)
    )
    await adapters.save_binding_policy(
        ModelBindingDraftCommand(
            actor_id="owner-1",
            policy=no_active_digest.model_dump(mode="json", exclude_none=True),
            policy_digest=no_active_digest.digest(),
            expected_revision=1,
            idempotency_key="draft-2",
        )
    )
    with pytest.raises(IamConflictError, match="expected active"):
        await adapters.request_binding_plan(
            ModelBindingRequestCommand(
                actor_id="owner-1",
                environment="staging",
                policy_revision=2,
                policy_digest=no_active_digest.digest(),
                idempotency_key="plan-2",
            )
        )


@pytest.mark.asyncio
async def test_model_binding_rejects_draft_for_another_environment() -> None:
    adapters = PostgresIamAdapters(ModelBindingPostgresFamilyStore())
    policy = ModelBindingPolicy.model_validate(
        {**_binding_policy(revision=1), "environment": "prod"}
    )

    with pytest.raises(IamConflictError, match="does not match this deployment"):
        await adapters.save_binding_policy(
            ModelBindingDraftCommand(
                actor_id="owner-1",
                policy=policy.model_dump(mode="json", exclude_none=True),
                policy_digest=policy.digest(),
                expected_revision=0,
                idempotency_key="wrong-environment",
            )
        )


@pytest.mark.asyncio
async def test_model_binding_plan_rejects_stale_active_artifact_digest() -> None:
    store = ModelBindingPostgresFamilyStore()
    adapters = PostgresIamAdapters(store)
    policy = ModelBindingPolicy.model_validate(_binding_policy(revision=1))
    await adapters.save_binding_policy(
        ModelBindingDraftCommand(
            actor_id="owner-1",
            policy=policy.model_dump(mode="json", exclude_none=True),
            policy_digest=policy.digest(),
            expected_revision=0,
            idempotency_key="draft-1",
        )
    )
    store.payload["resolved_metadata"] = {"digest": "sha256:" + "b" * 64}

    with pytest.raises(IamConflictError, match="active resolved-models digest"):
        await adapters.request_binding_plan(
            ModelBindingRequestCommand(
                actor_id="owner-1",
                environment="staging",
                policy_revision=1,
                policy_digest=policy.digest(),
                idempotency_key="plan-stale-active",
            )
        )


@pytest.mark.asyncio
async def test_model_binding_assessment_rejects_stale_policy_digest() -> None:
    store = ModelBindingPostgresFamilyStore()
    adapters = PostgresIamAdapters(store)
    policy = ModelBindingPolicy.model_validate(_binding_policy(revision=1))
    await adapters.save_binding_policy(
        ModelBindingDraftCommand(
            actor_id="owner-1",
            policy=policy.model_dump(mode="json", exclude_none=True),
            policy_digest=policy.digest(),
            expected_revision=0,
            idempotency_key="draft-1",
        )
    )

    with pytest.raises(IamConflictError, match="does not match the current draft"):
        await adapters.request_binding_assessment(
            ModelBindingRequestCommand(
                actor_id="owner-1",
                environment="staging",
                policy_revision=1,
                policy_digest="sha256:" + "b" * 64,
                idempotency_key="assess-stale-policy",
            )
        )


@pytest.mark.asyncio
async def test_model_binding_assessment_retry_returns_duplicate_receipt() -> None:
    store = ModelBindingPostgresFamilyStore()
    adapters = PostgresIamAdapters(store)
    policy = ModelBindingPolicy.model_validate(_binding_policy(revision=1))
    await adapters.save_binding_policy(
        ModelBindingDraftCommand(
            actor_id="owner-1",
            policy=policy.model_dump(mode="json", exclude_none=True),
            policy_digest=policy.digest(),
            expected_revision=0,
            idempotency_key="draft-1",
        )
    )
    request = ModelBindingRequestCommand(
        actor_id="owner-1",
        environment="staging",
        policy_revision=1,
        policy_digest=policy.digest(),
        idempotency_key="assess-retry",
    )

    first = await adapters.request_binding_assessment(request)
    retried = await adapters.request_binding_assessment(request)

    assert first["duplicate"] is False
    assert retried["duplicate"] is True
    assert retried["proposal_id"] == first["proposal_id"]
    assert [operation for operation, _payload in store.proposals].count(
        "model-settings.binding-policy.assessment"
    ) == 1


def _audit_row(
    seq: int,
    *,
    correlation_id: str = "corr-1",
    action_kind: str = "control.stage",
    entry: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "seq": seq,
        "event_id": "00000000-0000-0000-0000-000000000001",
        "correlation_id": correlation_id,
        "actor": "operator-test",
        "action_kind": action_kind,
        "mode": "shadow",
        "entry": dict(entry or {}),
        "previous_hash": f"hash-{seq - 1}",
        "entry_hash": f"hash-{seq}",
        "created_at": _NOW,
    }


class StubPostgresReadModel(PostgresOperatorReadModel):
    """Return deterministic rows while recording SQL parameter boundaries."""

    def __init__(self) -> None:
        super().__init__(PostgresOperatorReadModelConfig(dsn="postgresql://example.invalid/db"))
        self.calls: list[tuple[str, Mapping[str, object]]] = []
        self.audit_rows: list[dict[str, object]] = []
        self.hil_rows: list[dict[str, object]] = []
        self.incident_rows: list[dict[str, object]] = []
        self.incident_snapshot_seq = 0
        self.llm_summary_rows: list[dict[str, object]] = []
        self.llm_conversation_rows: list[dict[str, object]] = []
        self.llm_record_rows: list[dict[str, object]] = []
        self.inventory_activity_rows: list[dict[str, object]] = []
        self.ontology_activity_rows: list[dict[str, object]] = []
        self.read_activity_rows: list[dict[str, object]] = []
        self.observation_activity_rows: list[dict[str, object]] = []

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        self.calls.append((statement, parameters))
        if statement == AUDIT_PAGE_SQL:
            return self.audit_rows
        if statement == KPI_SAMPLE_SQL:
            return self.audit_rows
        if statement == HIL_COUNT_SQL:
            # Mirrors the SQL projectability filter so the count agrees with the page.
            unprojectable = sum(1 for row in self.hil_rows if hil_item(row) is None)
            return [{"total_count": len(self.hil_rows), "unprojectable_count": unprojectable}]
        if statement == HIL_PAGE_SQL:
            return self.hil_rows
        if statement in (INCIDENT_CURRENT_PAGE_SQL, INCIDENT_PAGE_SQL):
            return self.incident_rows
        if statement == INCIDENT_SNAPSHOT_SQL:
            return [{"snapshot_seq": self.incident_snapshot_seq}]
        if statement == LLM_USAGE_SUMMARIES_SQL:
            return self.llm_summary_rows
        if statement == LLM_USAGE_CONVERSATIONS_SQL:
            return self.llm_conversation_rows
        if statement == LLM_USAGE_RECORDS_SQL:
            return self.llm_record_rows
        if statement == AGENT_INVENTORY_ACTIVITY_SQL:
            return self.inventory_activity_rows
        if statement == AGENT_ONTOLOGY_ACTIVITY_SQL:
            return self.ontology_activity_rows
        if statement == AGENT_READ_ACTIVITY_SQL:
            return self.read_activity_rows
        if statement == AGENT_OBSERVATION_ACTIVITY_SQL:
            return self.observation_activity_rows
        raise AssertionError("unexpected SQL statement")


@pytest.mark.asyncio
async def test_agent_activity_reads_each_durable_source_with_bounded_limits() -> None:
    model = StubPostgresReadModel()
    model.inventory_activity_rows = [
        {
            "id": "attempt-1",
            "status": "active",
            "source": "azure-resource-graph",
            "started_at": _NOW,
            "completed_at": _NOW,
            "failure_code": None,
            "resource_count": 2,
            "link_count": 1,
        }
    ]

    payload = (await model.list_agent_activity(AgentActivityQuery(limit=25))).to_dict()

    assert payload["items"][0]["kind"] == "inventory.scan"
    assert payload["items"][0]["evidence_count"] == 3
    inventory_call = next(call for call in model.calls if call[0] == AGENT_INVENTORY_ACTIVITY_SQL)
    read_call = next(call for call in model.calls if call[0] == AGENT_READ_ACTIVITY_SQL)
    assert inventory_call[1] == {"limit": 25}
    assert read_call[1] == {"limit": 25}
    assert "get_resource_state" in AGENT_READ_ACTIVITY_SQL
    assert "operation_class' = 'resource_state'" in AGENT_READ_ACTIVITY_SQL
    assert "read-investigation-latency:%%" in AGENT_READ_ACTIVITY_SQL


@pytest.mark.asyncio
async def test_audit_query_is_parameterized_paginated_and_redacted() -> None:
    model = StubPostgresReadModel()
    model.audit_rows = [
        _audit_row(
            3,
            entry={
                "token": "secret-value",
                "client-secret": "also-hidden",
                "nested": {"password": "hidden"},
            },
        ),
        _audit_row(2),
    ]
    attack = "corr' OR TRUE --"

    page = await model.list_audit(AuditQuery(limit=1, correlation_id=attack))

    assert page.next_cursor == "3"
    assert page.items[0]["entry"] == {
        "token": "[REDACTED]",
        "client-secret": "[REDACTED]",
        "nested": {"password": "[REDACTED]"},
    }
    statement, parameters = model.calls[0]
    assert attack not in statement
    assert parameters["correlation_id"] == attack
    assert parameters["fetch"] == 2


@pytest.mark.asyncio
async def test_audit_projection_normalizes_null_string_correlation() -> None:
    model = StubPostgresReadModel()
    model.audit_rows = [_audit_row(1, correlation_id="None")]

    page = await model.list_audit(AuditQuery(limit=1))

    assert page.items[0]["correlation_id"] is None


@pytest.mark.asyncio
async def test_hil_reader_gets_count_only_and_approver_gets_redacted_detail() -> None:
    model = StubPostgresReadModel()
    model.hil_rows = [_hil_row()]

    count_only = await model.list_hil_queue(
        HilQueueQuery(limit=50, search=None, include_details=False)
    )
    details = await model.list_hil_queue(
        HilQueueQuery(limit=50, search="resource-1", include_details=True)
    )

    assert count_only.to_dict(include_details=False) == {
        "items": [],
        "total": 1,
        "detail_level": "count_only",
    }
    assert details.items[0]["target_resource_ref"] == "resource-1"
    assert "credential" not in details.items[0]
    detail_call = next(call for call in model.calls if call[0] == HIL_PAGE_SQL)
    assert detail_call[1]["search"] == "resource-1"
    assert detail_call[1]["search_pattern"] == "%resource-1%"


@pytest.mark.asyncio
async def test_malformed_authoritative_hil_row_fails_closed() -> None:
    model = StubPostgresReadModel()
    model.hil_rows = [{"total_count": 1, "value": {"approval_id": "incomplete"}}]

    with pytest.raises(RuntimeError, match="HIL row is malformed"):
        await model.list_hil_queue(HilQueueQuery(limit=50, search=None, include_details=True))


@pytest.mark.asyncio
async def test_count_only_hil_queue_fails_closed_on_a_mixed_page() -> None:
    """A reader without approval roles MUST NOT see a total the page cannot render."""
    model = StubPostgresReadModel()
    model.hil_rows = [
        _hil_row(),
        {"total_count": 2, "value": {"approval_id": "incomplete"}},
    ]

    with pytest.raises(RuntimeError, match="HIL row is malformed"):
        await model.list_hil_queue(HilQueueQuery(limit=50, search=None, include_details=False))


@pytest.mark.asyncio
async def test_count_only_hil_queue_reports_a_renderable_total() -> None:
    model = StubPostgresReadModel()
    model.hil_rows = [_hil_row()]

    projection = await model.list_hil_queue(
        HilQueueQuery(limit=50, search=None, include_details=False)
    )

    assert projection.total == 1
    assert projection.items == ()


@pytest.mark.asyncio
async def test_kpi_uses_bounded_sample_and_authoritative_hil_count() -> None:
    model = StubPostgresReadModel()
    model.audit_rows = [
        _audit_row(1, action_kind="rule.evaluate", entry={"outcome": "hil", "tier": "T0"})
    ]
    model.hil_rows = [{"value": {}}]

    payload = (await model.dashboard_metrics()).to_dict()

    assert payload["event_count"] == 1
    assert payload["hil_pending"] == 1
    assert payload["by_tier"] == {"t0": 1}
    assert payload["by_outcome"] == {"hil": 1}
    kpi_call = next(call for call in model.calls if call[0] == KPI_SAMPLE_SQL)
    assert kpi_call[1]["limit"] == 500


@pytest.mark.asyncio
async def test_kpi_abstains_instead_of_inventing_an_outcome_for_rows_without_one() -> None:
    model = StubPostgresReadModel()
    model.audit_rows = [
        _audit_row(1, action_kind="observation-campaign.source-transition", entry={}),
        _audit_row(2, action_kind="control_loop.compliant", entry={"rule_id": "r-1"}),
        _audit_row(3, action_kind="executor.direct_api.dispatched", entry={"outcome": "applied"}),
    ]

    payload = (await model.dashboard_metrics()).to_dict()

    assert payload["event_count"] == 3
    assert payload["by_outcome"] == {"applied": 1}


@pytest.mark.asyncio
async def test_llm_usage_projects_measured_tokens_without_price_fields() -> None:
    model = StubPostgresReadModel()
    model.llm_summary_rows = [
        {
            "group_kind": kind,
            "group_key": key,
            "invocations": invocations,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
        }
        for kind, key, invocations, prompt, completion in (
            ("total", "total", 2, 30, 12),
            ("chat", "chat", 1, 10, 5),
            ("scope", "control_plane", 1, 20, 7),
            ("scope", "operator_chat", 1, 10, 5),
            ("model", "model-a", 2, 30, 12),
            ("chat_model", "model-a", 1, 10, 5),
            ("mode", "shadow", 2, 30, 12),
            ("hour", "2026-08-08T00:00:00Z", 2, 30, 12),
            ("day", "2026-08-08", 2, 30, 12),
            ("month", "2026-08", 2, 30, 12),
        )
    ]
    model.llm_conversation_rows = [
        {
            "group_key": "corr-1",
            "invocations": 2,
            "prompt_tokens": 30,
            "completion_tokens": 12,
            "conversation_count": 1,
        }
    ]
    model.llm_record_rows = [
        {
            "occurred_at": _NOW,
            "correlation_id": "corr-1",
            "capability_id": "narrator",
            "model_key": "model-a",
            "tier": "narrator",
            "mode": "shadow",
            "usage_scope": "operator_chat",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "record_count": 2,
        }
    ]

    payload = (await model.llm_usage(_NOW, _NOW.replace(day=9))).to_dict()

    assert payload["invocations"] == 2
    assert payload["total"]["total_tokens"] == 42
    assert payload["chat"]["total_tokens"] == 15
    assert payload["by_conversation"][0]["key"] == "corr-1"
    assert payload["records"][0]["total_tokens"] == 15
    assert payload["record_count"] == 2
    assert "cost" not in payload["total"]
    for statement in (
        LLM_USAGE_SUMMARIES_SQL,
        LLM_USAGE_CONVERSATIONS_SQL,
        LLM_USAGE_RECORDS_SQL,
    ):
        call = next(item for item in model.calls if item[0] == statement)
        assert call[1]["range_start"] == _NOW


@pytest.mark.asyncio
async def test_incident_page_and_attention_replay_use_durable_sequence() -> None:
    model = StubPostgresReadModel()
    row = _audit_row(
        7,
        entry={
            "kind": "incident.open",
            "incident_id": "INC-1",
            "severity": "high",
            "state": "open",
            "opened_at": _NOW.isoformat(),
            "correlation_keys": ["resource:example-app"],
            "source_platform": "Azure Monitor",
            "source_incident_id": "alert-example",
            "source_status": "triggered",
            "source_fired_at": _NOW.isoformat(),
            "source_url": "https://example.com/incidents/alert-example",
            "source_url_trusted": True,
            "description": "Inventory refresh exceeded its freshness objective.",
            "response_plan_id": "inventory-freshness",
            "response_plan_revision": "rev-7",
            "response_plan_enabled": True,
            "response_plan_match_count": 4,
            "reinvestigation_cooldown_seconds": 10800,
            "deduplication_key": "inventory:example-app",
        },
    )
    row.update(
        {
            "normalized_correlation_id": "corr-1",
            "group_last_seq": 7,
            "group_history_count": 1,
            "snapshot_seq": 7,
        }
    )
    model.incident_rows = [row]

    page = await model.list_incidents(IncidentQuery(status="active", limit=50))
    initial = await model.incident_attention(IncidentAttentionQuery(after_seq=None, limit=50))
    replayed = await model.incident_attention(IncidentAttentionQuery(after_seq=7, limit=50))

    assert page.items[0]["title"] == "Resource example-app"
    assert page.items[0]["title_source"] == "correlation_subject"
    assert page.items[0]["source"] == {
        "platform": "Azure Monitor",
        "incident_id": "alert-example",
        "status": "triggered",
        "fired_at": _NOW.isoformat(),
        "description": "Inventory refresh exceeded its freshness objective.",
        "url": "https://example.com/incidents/alert-example",
    }
    assert page.items[0]["response_plan"] == {
        "id": "inventory-freshness",
        "revision": "rev-7",
        "enabled": True,
        "historical_match_count": 4,
        "reinvestigation_cooldown_seconds": 10800,
        "deduplication_key": "inventory:example-app",
    }
    assert page.items[0]["status"] == "open"
    assert initial is not None
    assert initial.sequence == 7
    assert initial.to_dict()["incidents"][0]["incident_id"] == "INC-1"
    assert replayed is None
    assert _sse_frame(initial).startswith(
        b'id: 7\nevent: incident-attention\ndata: {"event":"incident_attention.snapshot"'
    )


@pytest.mark.parametrize(
    ("entry", "expected_title", "expected_source"),
    [
        (
            {"title": "Database connection saturation"},
            "Database connection saturation",
            "recorded_title",
        ),
        (
            {"summary": "Checkout latency increased"},
            "Checkout latency increased",
            "recorded_summary",
        ),
        ({"rule_id": "slo.burn-rate"}, "Rule Slo burn rate", "rule_id"),
        (
            {
                "correlation_keys": [
                    "signal:resource_inventory_change",
                    "resource:/subscriptions/example/resourceGroups/example/providers/"
                    "Microsoft.Storage/storageAccounts/storage-example",
                ]
            },
            "Resource inventory change - Storage accounts storage-example",
            "correlation_subject",
        ),
        (
            {
                "resource_type": "compute.vm.novel",
                "reason": "no_rule_matches_resource_and_signal_type",
            },
            "Compute vm novel - No rule matches resource and signal type",
            "recorded_subject",
        ),
        (
            {
                "payload": {
                    "resource_id": "scope-example/resource-group/rg-example/providers/"
                    "microsoft.dbforpostgresql/flexibleservers/psql-example",
                    "reason": "no_rule_match",
                }
            },
            "Flexibleservers psql-example - No rule match",
            "recorded_subject",
        ),
        (
            {"reason": "control_loop_unhandled_error"},
            "Control loop unhandled error",
            "recorded_subject",
        ),
        ({}, "Incident INC-1", "identifier_fallback"),
    ],
)
def test_incident_title_precedence_and_provenance(
    entry: dict[str, object],
    expected_title: str,
    expected_source: str,
) -> None:
    row = _audit_row(
        1,
        entry={
            "incident_id": "INC-1",
            "incident_number": "INC-202608-0000",
            **entry,
        },
    )
    row.update(
        {
            "normalized_correlation_id": "corr-1",
            "group_last_seq": 1,
            "group_history_count": 1,
        }
    )

    summary = incident_summary([row])

    assert summary["title"] == expected_title
    assert summary["title_source"] == expected_source
    assert summary["incident_number"] == "INC-202608-0000"


@pytest.mark.parametrize(
    ("recorded_state", "expected_status"),
    [
        ("open", "open"),
        ("triaging", "in_progress"),
        ("mitigated", "in_progress"),
        ("resolved", "resolved"),
        ("closed", "resolved"),
    ],
)
def test_incident_lifecycle_state_maps_onto_the_roster_contract(
    recorded_state: str,
    expected_status: str,
) -> None:
    row = _audit_row(
        1,
        entry={
            "incident_id": "INC-1",
            "kind": "incident.transition",
            "to_state": recorded_state,
        },
    )
    row.update(
        {
            "normalized_correlation_id": "corr-1",
            "group_last_seq": 1,
            "group_history_count": 1,
        }
    )

    summary = incident_summary([row])

    assert summary["status"] == expected_status
    assert summary["status_source"] == "incident_lifecycle"
    assert summary["lifecycle_state"] == recorded_state


def test_incident_projection_does_not_expose_unknown_lifecycle_state() -> None:
    row = _audit_row(
        1,
        entry={
            "incident_id": "INC-1",
            "kind": "incident.transition",
            "to_state": "unknown-state",
        },
    )
    row.update(
        {
            "normalized_correlation_id": "corr-1",
            "group_last_seq": 1,
            "group_history_count": 1,
        }
    )

    summary = incident_summary([row])

    assert summary["status"] == "in_progress"
    assert summary["status_source"] == "incident_lifecycle"
    assert summary["lifecycle_state"] is None


def test_incident_title_bound_and_partial_response_plan() -> None:
    row = _audit_row(
        1,
        entry={
            "incident_id": "INC-1",
            "title": "x" * 161,
            "response_plan_id": "plan-1",
        },
    )
    row.update(
        {
            "normalized_correlation_id": "corr-1",
            "group_last_seq": 1,
            "group_history_count": 1,
        }
    )

    summary = incident_summary([row])

    assert len(summary["title"]) == 160
    assert summary["title"].endswith("...")
    assert summary["response_plan"] == {
        "id": "plan-1",
        "revision": None,
        "enabled": None,
        "historical_match_count": None,
        "reinvestigation_cooldown_seconds": None,
        "deduplication_key": None,
    }


def test_incident_projection_reader_rejects_null_string_correlation_sentinels() -> None:
    valid = {"normalized_correlation_id": " corr-1 "}

    grouped = _group_incident_rows(
        [
            {"normalized_correlation_id": None},
            {"normalized_correlation_id": ""},
            {"normalized_correlation_id": "None"},
            {"normalized_correlation_id": "null"},
            valid,
        ]
    )

    assert grouped == [[valid]]


def test_incident_page_excludes_platform_housekeeping_groups() -> None:
    """A group of only platform activity is not an incident and not a cohort denominator."""
    assert "projection.has_incident_activity" in INCIDENT_PAGE_SQL
    assert "projection.has_incident_activity" in INCIDENT_CURRENT_PAGE_SQL


def test_current_incident_page_uses_current_projection_predicate() -> None:
    assert "projection.valid_to_seq IS NULL" in INCIDENT_CURRENT_PAGE_SQL
    assert "projection.valid_from_seq <=" not in INCIDENT_CURRENT_PAGE_SQL


def test_incident_page_limits_temporal_projection_before_expanding_history() -> None:
    """Roster cost follows the requested page instead of total audit history."""
    projection = INCIDENT_PAGE_SQL.index("FROM operator_incident_projection")
    page_limit = INCIDENT_PAGE_SQL.index("LIMIT %(fetch)s", projection)
    history_expansion = INCIDENT_PAGE_SQL.index("JSONB_ARRAY_ELEMENTS", page_limit)

    assert projection < page_limit < history_expansion
    assert "FROM audit_log AS audit" not in INCIDENT_PAGE_SQL


def test_incident_outcome_metrics_require_independent_verification() -> None:
    incidents = [
        {
            "correlation_id": "corr-agent",
            "status": "resolved",
            "independent_outcome_verified": True,
            "mitigated_by": "agent",
            "agent_assisted": False,
            "opened_at": "2026-08-14T00:00:00Z",
            "last_updated_at": "2026-08-14T00:10:00Z",
        },
        {
            "correlation_id": "corr-assisted",
            "status": "resolved",
            "independent_outcome_verified": True,
            "mitigated_by": "human",
            "agent_assisted": True,
            "opened_at": "2026-08-14T00:00:00Z",
            "last_updated_at": "2026-08-14T00:20:00Z",
        },
        {
            "correlation_id": "corr-unverified",
            "status": "resolved",
            "independent_outcome_verified": False,
            "mitigated_by": "agent",
            "agent_assisted": False,
            "opened_at": "2026-08-14T00:00:00Z",
            "last_updated_at": "2026-08-14T00:30:00Z",
        },
        {
            "correlation_id": "corr-pending",
            "status": "in_progress",
            "independent_outcome_verified": False,
            "mitigated_by": None,
            "agent_assisted": False,
            "opened_at": "2026-08-14T00:40:00Z",
            "last_updated_at": "2026-08-14T00:40:00Z",
        },
    ]

    metrics = incident_outcome_metrics(incidents, snapshot_seq=44, truncated=False)

    assert metrics["denominator"] == 4
    assert metrics["cohorts"] == {
        "agent_mitigated": 1,
        "agent_assisted": 1,
        "human_mitigated": 0,
        "pending": 1,
        "integrity_excluded": 1,
    }
    assert metrics["median_time_to_mitigate_seconds"] == 900
    assert metrics["time_to_mitigate_sample_size"] == 2
    assert metrics["drilldown"] == {
        "agent_mitigated": ["corr-agent"],
        "agent_assisted": ["corr-assisted"],
        "human_mitigated": [],
        "pending": ["corr-pending"],
        "integrity_excluded": ["corr-unverified"],
    }


def test_incident_metrics_preserve_half_second_median_and_mark_drilldown_cap() -> None:
    base = {
        "status": "resolved",
        "independent_outcome_verified": True,
        "mitigated_by": "agent",
        "agent_assisted": False,
        "opened_at": "2026-08-14T00:00:00Z",
    }
    precise = [
        {**base, "correlation_id": "corr-0", "last_updated_at": "2026-08-14T00:01:40Z"},
        {**base, "correlation_id": "corr-1", "last_updated_at": "2026-08-14T00:01:41Z"},
    ]
    large = [
        {
            **base,
            "correlation_id": f"corr-{index}",
            "last_updated_at": "2026-08-14T00:02:00Z",
        }
        for index in range(201)
    ]

    metrics = incident_outcome_metrics(precise, snapshot_seq=2, truncated=False)
    capped = incident_outcome_metrics(large, snapshot_seq=201, truncated=False)

    assert metrics["median_time_to_mitigate_seconds"] == 100.5
    assert metrics["time_to_mitigate_sample_size"] == 2
    assert len(capped["drilldown"]["agent_mitigated"]) == 200
    assert capped["drilldown_truncated"]["agent_mitigated"] is True


@pytest.mark.asyncio
async def test_empty_incident_page_pins_metrics_to_current_snapshot() -> None:
    model = StubPostgresReadModel()
    model.incident_snapshot_seq = 42

    page = await model.list_incidents(IncidentQuery(status="active", limit=25))

    assert page.items == ()
    assert page.metrics["snapshot_seq"] == 42
    current_calls = [call for call in model.calls if call[0] == INCIDENT_CURRENT_PAGE_SQL]
    incident_calls = [call for call in model.calls if call[0] == INCIDENT_PAGE_SQL]
    assert len(current_calls) == 1
    assert incident_calls[0][1]["snapshot_seq"] == 42


@pytest.mark.asyncio
async def test_incident_search_uses_one_page_and_metrics_filter() -> None:
    model = StubPostgresReadModel()

    await model.list_incidents(IncidentQuery(status="active", limit=25, search="compute vm"))

    current_calls = [call for call in model.calls if call[0] == INCIDENT_CURRENT_PAGE_SQL]
    incident_calls = [call for call in model.calls if call[0] == INCIDENT_PAGE_SQL]
    assert [call[1]["search"] for call in current_calls + incident_calls] == [
        "compute vm",
        "compute vm",
    ]
    assert "REGEXP_SPLIT_TO_TABLE" in INCIDENT_PAGE_SQL
    assert "STRPOS(projection.search_document" in INCIDENT_PAGE_SQL


def test_incident_cursor_is_bound_to_normalized_search() -> None:
    cursor = _encode_incident_cursor(42, 21, "active", "compute vm", None, None)

    assert _decode_incident_cursor(
        cursor,
        status="active",
        search="compute vm",
        vertical=None,
        severity=None,
    ) == (42, 21)
    with pytest.raises(ValueError, match="invalid incident cursor"):
        _decode_incident_cursor(
            cursor,
            status="active",
            search="storage account",
            vertical=None,
            severity=None,
        )


def test_incident_source_link_and_agent_attribution_require_trusted_records() -> None:
    row = _audit_row(
        1,
        entry={
            "incident_id": "INC-1",
            "source_url": "https://example.com/incidents/INC-1",
            "source_url_trusted": False,
        },
    )
    row["actor"] = "external-monitor"
    row.update(
        {
            "normalized_correlation_id": "corr-1",
            "group_last_seq": 1,
            "group_history_count": 1,
        }
    )

    summary = incident_summary([row])

    assert summary["source"] is None
    assert summary["involved_agents"] == []


@pytest.mark.asyncio
async def test_trace_and_rca_preserve_frozen_envelopes() -> None:
    model = StubPostgresReadModel()
    model.audit_rows = [
        _audit_row(
            2,
            action_kind="risk_gate.shadow_authority",
            entry={"stage": "gate", "decision": "auto", "rollback_reference": "pr-7"},
        ),
        _audit_row(
            1,
            action_kind="rca.hypothesis",
            entry={
                "rca_outcome": "grounded",
                "rca_tier": "t0",
                "rca_cause": "public access open",
                "rca_confidence": 0.95,
                "rca_citations": [{"kind": "rule", "ref": "storage.public-access"}],
            },
        ),
    ]

    trace = await model.get_rule_fire_trace("corr-1")
    rca = await model.get_rca("corr-1")

    assert trace is not None
    assert trace.to_dict()["terminal_stage"] == "gate"
    assert rca is not None
    assert rca.to_dict()["hypotheses"][0]["tier"] == "t0"
    assert rca.to_dict()["response"]["verdict"] == "auto"


def test_statement_identity_names_a_registered_statement_without_its_text() -> None:
    assert statement_identity(AUDIT_PAGE_SQL) == "AUDIT_PAGE_SQL"
    assert statement_identity(INCIDENT_PAGE_SQL) == "INCIDENT_PAGE_SQL"
    assert statement_identity("SELECT 1") == "unregistered_statement"


@pytest.mark.asyncio
async def test_failed_projection_query_records_its_cause_before_reporting_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = PostgresOperatorReadModel(
        PostgresOperatorReadModelConfig(
            dsn="postgresql://operator@127.0.0.1:1/db",
            connect_timeout_s=1,
        )
    )

    with caplog.at_level(logging.WARNING, logger="fdai_operator_service.postgres"):
        with pytest.raises(ProjectionUnavailableError) as raised:
            await model._fetch_all(INCIDENT_PAGE_SQL, {"search": "operator utterance"})

    record = next(r for r in caplog.records if r.message == "operator_projection_query_failed")
    assert record.statement == "INCIDENT_PAGE_SQL"  # type: ignore[attr-defined]
    # The recorded class names the real cause; which psycopg error a refused
    # connection raises differs between environments.
    assert record.error_class == type(raised.value.__cause__).__name__  # type: ignore[attr-defined]
    assert isinstance(raised.value.__cause__, psycopg.Error)
    assert "operator utterance" not in caplog.text
