from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.workflow.automation_hold import (
    AutomationHoldReleaseReceipt,
    StateStoreAutomationHoldLedger,
)
from fdai.core.workflow.recovery_admission import (
    WorkflowRecoveryAdmissionAssessment,
    assess_workflow_recovery_admission,
)
from fdai.core.workflow.workflow_runtime import (
    WorkflowApprovalDecision,
    WorkflowApprovalSnapshot,
    workflow_approval_state_key,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 9, 10, 3, 0, tzinfo=UTC)
_RECEIPTS = ("sha256:" + "b" * 64, "sha256:" + "c" * 64)
_SOURCE_REVISION = "commit:" + "d" * 40


class _Admissions:
    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission:
        return DecisionEvidenceAdmission(
            receipt_digest="sha256:" + "e" * 64,
            verification_bundle_digest="sha256:" + "f" * 64,
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
            verified_at=_NOW - timedelta(minutes=1),
            valid_until=_NOW + timedelta(minutes=1),
        )


def _approval_snapshot(*, process_id: str = "process-1") -> WorkflowApprovalSnapshot:
    return WorkflowApprovalSnapshot(
        process_id=process_id,
        step_id="approve_recovery",
        requester_principal="requester@example.com",
        revision=3,
        requested_at=_NOW - timedelta(minutes=2),
        expires_at=_NOW + timedelta(minutes=3),
        attempt=2,
        decisions=(
            WorkflowApprovalDecision(
                principal="approver@example.com",
                decision="approved",
                receipt_ref="approval:1",
            ),
        ),
    )


async def _release_args(
    store: InMemoryStateStore,
    *,
    target_ref: str = "resource-1",
    process_id: str = "process-1",
    hold_revision: int = 1,
) -> _ReleaseArgs:
    snapshot = _approval_snapshot(process_id=process_id)
    await store.write_state(
        workflow_approval_state_key(snapshot.process_id, snapshot.step_id, snapshot.attempt),
        {
            "process_id": snapshot.process_id,
            "step_id": snapshot.step_id,
            "attempt": snapshot.attempt,
            "requester_principal": snapshot.requester_principal,
            "quorum": 1,
            "no_self_approval": True,
            "requested_at": snapshot.requested_at.isoformat(),
            "decision_claims": {
                "slot-1": {
                    "principal": snapshot.decisions[0].principal,
                    "decision": snapshot.decisions[0].decision,
                    "receipt_ref": snapshot.decisions[0].receipt_ref,
                }
            },
            "state": "pending",
            "revision": snapshot.revision,
            "expires_at": snapshot.expires_at.isoformat() if snapshot.expires_at else None,
        },
    )
    assessment = await assess_workflow_recovery_admission(
        _Admissions(),
        snapshot=snapshot,
        quorum=1,
        no_self_approval=True,
        hold_revision=hold_revision,
        target_digest="sha256:" + hashlib.sha256(target_ref.encode()).hexdigest(),
        compensation_receipt_digests=_RECEIPTS,
        executor_identity="executor@example.com",
        source_revision=_SOURCE_REVISION,
        evaluated_at=_NOW,
    )
    return _ReleaseArgs(
        target_ref=target_ref,
        process_id=process_id,
        action_id="recovery-action-1",
        hold_revision=hold_revision,
        approval_snapshot=snapshot,
        quorum=1,
        no_self_approval=True,
        compensation_receipt_digests=_RECEIPTS,
        executor_identity="executor@example.com",
        source_revision=_SOURCE_REVISION,
        assessment=assessment,
    )


@dataclass(frozen=True, slots=True)
class _ReleaseArgs:
    target_ref: str
    process_id: str
    action_id: str
    hold_revision: int
    approval_snapshot: WorkflowApprovalSnapshot
    quorum: int
    no_self_approval: bool
    compensation_receipt_digests: tuple[str, ...]
    executor_identity: str
    source_revision: str
    assessment: WorkflowRecoveryAdmissionAssessment


async def _release(
    ledger: StateStoreAutomationHoldLedger,
    arguments: _ReleaseArgs,
) -> AutomationHoldReleaseReceipt | None:
    return await ledger.release_admitted(
        target_ref=arguments.target_ref,
        process_id=arguments.process_id,
        action_id=arguments.action_id,
        hold_revision=arguments.hold_revision,
        approval_snapshot=arguments.approval_snapshot,
        quorum=arguments.quorum,
        no_self_approval=arguments.no_self_approval,
        compensation_receipt_digests=arguments.compensation_receipt_digests,
        executor_identity=arguments.executor_identity,
        source_revision=arguments.source_revision,
        assessment=arguments.assessment,
    )


def _admitted_ledger(store: InMemoryStateStore) -> StateStoreAutomationHoldLedger:
    return StateStoreAutomationHoldLedger(store, clock=lambda: _NOW)


async def test_issued_hold_is_target_scoped_and_audited() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAutomationHoldLedger(store)

    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )

    assert await ledger.is_held(target_ref="resource-1")
    assert not await ledger.is_held(target_ref="resource-2")
    assert store.audit_entries[0]["entry"]["action_kind"] == ("workflow.automation_hold.issued")
    assert "resource-1" not in str(store.audit_entries[0])


async def test_malformed_hold_state_fails_closed() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAutomationHoldLedger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )
    key = next(iter(store._state))
    await store.write_state(key, {"state": "unknown"})

    assert await ledger.is_held(target_ref="resource-1")


async def test_active_hold_survives_restart_and_duplicate_delivery() -> None:
    store = InMemoryStateStore()
    first_ledger = StateStoreAutomationHoldLedger(store)
    await first_ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )

    restarted_ledger = StateStoreAutomationHoldLedger(store)
    await restarted_ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="duplicate_delivery",
    )

    assert await restarted_ledger.is_held(target_ref="resource-1")
    assert len(store.audit_entries) == 1
    record = next(iter(store._state.values()))
    assert record["revision"] == 1
    assert record["reason"] == "compensation_failed"


async def test_only_matching_compensation_is_recovery_eligible() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAutomationHoldLedger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )

    assert not await ledger.recovery_eligible(
        target_ref="resource-1",
        process_id="process-other",
        step_id="compensate_start",
    )
    assert not await ledger.recovery_eligible(
        target_ref="resource-1",
        process_id="process-1",
        step_id="ordinary_step",
    )
    assert await ledger.recovery_eligible(
        target_ref="resource-1",
        process_id="process-1",
        step_id="compensate_start",
    )

    assert await ledger.is_held(target_ref="resource-1")
    assert await ledger.read_hold_record(target_ref="resource-1") is not None


async def test_reissued_hold_rejects_stale_process_release() -> None:
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="first_failure",
    )
    assert await _release(ledger, await _release_args(store)) is not None

    await ledger.issue(
        target_ref="resource-1",
        process_id="process-2",
        reason="second_failure",
    )
    reissued = await ledger.read_hold_record(target_ref="resource-1")

    assert await ledger.is_held(target_ref="resource-1")
    assert reissued is not None
    assert reissued["revision"] == 3
    assert await _release(ledger, await _release_args(store)) is None


async def test_admitted_release_is_two_phase_atomic_and_content_addressed() -> None:
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )

    receipt = await _release(ledger, await _release_args(store))

    assert receipt is not None
    assert receipt.released_hold_revision == 1
    assert receipt.fencing_generation == 2
    assert receipt.execution_authority is False
    assert len(receipt.receipt_digest) == 71
    assert not await ledger.is_held(target_ref="resource-1")
    assert [row["entry"]["action_kind"] for row in store.audit_entries] == [
        "workflow.automation_hold.issued",
        "workflow.automation_hold.release_intent",
        "workflow.automation_hold.released_admitted",
    ]


async def test_duplicate_and_concurrent_release_reuse_one_receipt() -> None:
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )
    arguments = await _release_args(store)

    first, second = await asyncio.gather(
        _release(ledger, arguments),
        _release(ledger, arguments),
    )
    restarted = await _release(_admitted_ledger(store), arguments)

    assert first is not None and second == first and restarted == first
    assert len(store.audit_entries) == 3


async def test_stale_tampered_or_cross_process_admission_cannot_release() -> None:
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )
    arguments = await _release_args(store)
    tampered = replace(
        arguments,
        assessment=replace(
            arguments.assessment,
            evidence_digest="sha256:" + "0" * 64,
        ),
    )

    assert await _release(ledger, tampered) is None
    assert (
        await _release(
            ledger,
            replace(arguments, process_id="process-other"),
        )
        is None
    )
    assert (
        await _release(
            ledger,
            replace(arguments, hold_revision=2),
        )
        is None
    )
    assert await ledger.is_held(target_ref="resource-1")


async def test_reissued_hold_rejects_old_admitted_release() -> None:
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="first_failure",
    )
    arguments = await _release_args(store)
    assert await _release(ledger, arguments) is not None
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-2",
        reason="second_failure",
    )

    assert await _release(ledger, arguments) is None
    assert await ledger.is_held(target_ref="resource-1")


class _ReleaseFailStore(InMemoryStateStore):
    async def compare_and_set_state_with_approval_guard(
        self,
        key,
        value,
        *,
        expected_revision,
        approval_key,
        expected_approval_revision,
        expected_approval_process_id,
        expected_approval_step_id,
        expected_approval_attempt,
        expected_approval_requester,
        expected_approval_quorum,
        expected_no_self_approval,
        expected_approval_decisions,
        evaluated_at,
        admission_verified_at,
        admission_valid_until,
        audit_entry,
    ):
        if audit_entry.get("action_kind") == "workflow.automation_hold.released_admitted":
            return False
        return await super().compare_and_set_state_with_approval_guard(
            key,
            value,
            expected_revision=expected_revision,
            approval_key=approval_key,
            expected_approval_revision=expected_approval_revision,
            expected_approval_process_id=expected_approval_process_id,
            expected_approval_step_id=expected_approval_step_id,
            expected_approval_attempt=expected_approval_attempt,
            expected_approval_requester=expected_approval_requester,
            expected_approval_quorum=expected_approval_quorum,
            expected_no_self_approval=expected_no_self_approval,
            expected_approval_decisions=expected_approval_decisions,
            evaluated_at=evaluated_at,
            admission_verified_at=admission_verified_at,
            admission_valid_until=admission_valid_until,
            audit_entry=audit_entry,
        )


class _CancelApprovalStore(InMemoryStateStore):
    async def compare_and_set_state_with_approval_guard(
        self,
        key,
        value,
        *,
        expected_revision,
        approval_key,
        expected_approval_revision,
        expected_approval_process_id,
        expected_approval_step_id,
        expected_approval_attempt,
        expected_approval_requester,
        expected_approval_quorum,
        expected_no_self_approval,
        expected_approval_decisions,
        evaluated_at,
        admission_verified_at,
        admission_valid_until,
        audit_entry,
    ):
        approval = dict(self._state[approval_key])
        approval["state"] = "cancelled"
        approval["revision"] = expected_approval_revision + 1
        await self.write_state(approval_key, approval)
        return await super().compare_and_set_state_with_approval_guard(
            key,
            value,
            expected_revision=expected_revision,
            approval_key=approval_key,
            expected_approval_revision=expected_approval_revision,
            expected_approval_process_id=expected_approval_process_id,
            expected_approval_step_id=expected_approval_step_id,
            expected_approval_attempt=expected_approval_attempt,
            expected_approval_requester=expected_approval_requester,
            expected_approval_quorum=expected_approval_quorum,
            expected_no_self_approval=expected_no_self_approval,
            expected_approval_decisions=expected_approval_decisions,
            evaluated_at=evaluated_at,
            admission_verified_at=admission_verified_at,
            admission_valid_until=admission_valid_until,
            audit_entry=audit_entry,
        )


class _TerminalAuditFailStore(InMemoryStateStore):
    fail_terminal_audit = False

    def _append_audit_locked(self, entry):
        if (
            self.fail_terminal_audit
            and entry.get("action_kind") == "workflow.automation_hold.released_admitted"
        ):
            raise RuntimeError("terminal audit unavailable")
        super()._append_audit_locked(entry)


class _IntentAuditFailStore(InMemoryStateStore):
    fail_intent_audit = True

    def _append_audit_locked(self, entry):
        if (
            self.fail_intent_audit
            and entry.get("action_kind") == "workflow.automation_hold.release_intent"
        ):
            raise RuntimeError("intent audit unavailable")
        super()._append_audit_locked(entry)


async def test_failed_release_commit_preserves_active_hold() -> None:
    store = _ReleaseFailStore()
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )

    assert await _release(ledger, await _release_args(store)) is None
    assert await ledger.is_held(target_ref="resource-1")
    assert [row["entry"]["action_kind"] for row in store.audit_entries] == [
        "workflow.automation_hold.issued",
        "workflow.automation_hold.release_intent",
    ]


async def test_terminal_audit_failure_rolls_back_release_state() -> None:
    store = _TerminalAuditFailStore(linearization_clock=lambda: _NOW)
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )
    arguments = await _release_args(store)
    store.fail_terminal_audit = True

    with pytest.raises(RuntimeError, match="terminal audit unavailable"):
        await _release(ledger, arguments)

    assert await ledger.is_held(target_ref="resource-1")
    assert [row["entry"]["action_kind"] for row in store.audit_entries] == [
        "workflow.automation_hold.issued",
        "workflow.automation_hold.release_intent",
    ]


async def test_intent_audit_failure_rolls_back_and_retry_is_safe() -> None:
    store = _IntentAuditFailStore(linearization_clock=lambda: _NOW)
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )
    arguments = await _release_args(store)

    with pytest.raises(RuntimeError, match="intent audit unavailable"):
        await _release(ledger, arguments)

    assert await ledger.is_held(target_ref="resource-1")
    assert not any("release-intent" in key for key in store._state)
    store.fail_intent_audit = False
    assert await _release(ledger, arguments) is not None


async def test_durable_quorum_mismatch_preserves_hold() -> None:
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )
    arguments = await _release_args(store)
    approval_key = workflow_approval_state_key(
        arguments.approval_snapshot.process_id,
        arguments.approval_snapshot.step_id,
        arguments.approval_snapshot.attempt,
    )
    approval = dict(store._state[approval_key])
    approval["quorum"] = 2
    await store.write_state(approval_key, approval)

    assert await _release(ledger, arguments) is None
    assert await ledger.is_held(target_ref="resource-1")


async def test_missing_durable_decision_claim_preserves_hold() -> None:
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )
    arguments = await _release_args(store)
    approval_key = workflow_approval_state_key(
        arguments.approval_snapshot.process_id,
        arguments.approval_snapshot.step_id,
        arguments.approval_snapshot.attempt,
    )
    approval = dict(store._state[approval_key])
    approval["decision_claims"] = {}
    await store.write_state(approval_key, approval)

    assert await _release(ledger, arguments) is None
    assert await ledger.is_held(target_ref="resource-1")


async def test_future_durable_approval_window_preserves_hold() -> None:
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )
    arguments = await _release_args(store)
    approval_key = workflow_approval_state_key(
        arguments.approval_snapshot.process_id,
        arguments.approval_snapshot.step_id,
        arguments.approval_snapshot.attempt,
    )
    approval = dict(store._state[approval_key])
    approval["requested_at"] = (_NOW + timedelta(seconds=1)).isoformat()
    await store.write_state(approval_key, approval)

    assert await _release(ledger, arguments) is None
    assert await ledger.is_held(target_ref="resource-1")


async def test_approval_cancelled_before_terminal_cas_preserves_hold() -> None:
    store = _CancelApprovalStore()
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )

    assert await _release(ledger, await _release_args(store)) is None
    assert await ledger.is_held(target_ref="resource-1")
    assert [row["entry"]["action_kind"] for row in store.audit_entries] == [
        "workflow.automation_hold.issued",
        "workflow.automation_hold.release_intent",
    ]


async def test_approval_expiring_after_intent_preserves_hold() -> None:
    store = InMemoryStateStore()
    instants = iter((_NOW, _NOW + timedelta(minutes=2)))
    ledger = StateStoreAutomationHoldLedger(store, clock=lambda: next(instants))
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )

    assert await _release(ledger, await _release_args(store)) is None
    assert await ledger.is_held(target_ref="resource-1")
    assert [row["entry"]["action_kind"] for row in store.audit_entries] == [
        "workflow.automation_hold.issued",
        "workflow.automation_hold.release_intent",
    ]


async def test_admission_expiring_at_store_linearization_preserves_hold() -> None:
    store = InMemoryStateStore(
        linearization_clock=lambda: _NOW + timedelta(minutes=2),
    )
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )

    assert await _release(ledger, await _release_args(store)) is None
    assert await ledger.is_held(target_ref="resource-1")


async def test_expired_or_wrong_purpose_admission_cannot_start_release() -> None:
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    await _admitted_ledger(store).issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )
    arguments = await _release_args(store)
    stale_ledger = StateStoreAutomationHoldLedger(
        store,
        clock=lambda: _NOW + timedelta(minutes=2),
    )
    assert await _release(stale_ledger, arguments) is None

    assert arguments.assessment.admission is not None
    wrong_purpose = replace(
        arguments,
        assessment=replace(
            arguments.assessment,
            admission=replace(
                arguments.assessment.admission,
                purpose_id="different-purpose",
            ),
        ),
    )
    assert await _release(_admitted_ledger(store), wrong_purpose) is None
    assert await _admitted_ledger(store).is_held(target_ref="resource-1")


async def test_malformed_retained_intent_fails_closed() -> None:
    store = _ReleaseFailStore()
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )
    arguments = await _release_args(store)
    assert await _release(ledger, arguments) is None
    intent_key = next(key for key in store._state if "release-intent" in key)
    malformed = dict(store._state[intent_key])
    malformed.pop("requested_at")
    await store.write_state(intent_key, malformed)

    assert await _release(ledger, arguments) is None
    assert await ledger.is_held(target_ref="resource-1")


async def test_tampered_authority_receipt_is_not_replayed() -> None:
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    ledger = _admitted_ledger(store)
    await ledger.issue(
        target_ref="resource-1",
        process_id="process-1",
        reason="compensation_failed",
    )
    arguments = await _release_args(store)
    assert await _release(ledger, arguments) is not None
    hold_key = next(key for key in store._state if "automation-hold:" in key)
    released = dict(store._state[hold_key])
    raw_receipt = dict(released["release_receipt"])
    raw_receipt["execution_authority"] = True
    released["release_receipt"] = raw_receipt
    await store.write_state(hold_key, released)

    assert await _release(ledger, arguments) is None
