"""End-to-end authority coverage for the held-target recovery exception.

An automation hold denies every ordinary forward dispatch on its target. The
one exception is the recovery step that a separate human approved and that the
recovery coordinator then authorized under the exact hold revision still in
force. These tests drive that path through the real control loop and the real
executor safeguard lifecycle, using the production automation-hold ledger for
both reads, so an approved recovery reaches provider invocation while a stale,
cross-Process, or superseded-revision authorization still denies.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fdai.core.control_loop import ControlLoop
from fdai.core.executor import (
    DirectApiExecutionOutcome,
    DirectApiShadowExecutor,
    ResourceLockManager,
)
from fdai.core.executor.lock_continuity import (
    EffectSinkContinuityPolicy,
    OwnershipContinuityStrategy,
)
from fdai.core.executor.safeguard_lifecycle_coordinator import (
    SafeguardLifecycleCoordinator,
    SafeguardLifecycleCoordinatorConfig,
)
from fdai.core.executor.testing_safeguard_lifecycle import (
    InMemoryAuditIntentStore,
    InMemoryIdempotencyReservationStore,
    InMemoryPostReleaseClosureStore,
    InMemorySafeguardDispatchEvidenceStore,
    InMemoryTargetDispatchFenceStore,
)
from fdai.core.risk_gate import (
    ActionPromotionRegistry,
    RiskDecisionOutcome,
    RiskGate,
)
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.core.workflow.automation_hold import StateStoreAutomationHoldLedger
from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    recovery_attempt_step_id,
)
from fdai.core.workflow.safeguard_commitment import ProcessRuntimeSafeguardCommitmentStore
from fdai.shared.contracts.models import (
    Action,
    Event,
    OntologyActionType,
    Rule,
    WorkflowActionRef,
)
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingDirectApiExecutor,
)
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai_service_contracts.ontology_query import content_digest

from tests.core.executor.test_direct_api_executor import _action as _direct_action

pytestmark = pytest.mark.asyncio

REPO_ROOT = Path(__file__).resolve().parents[4]
TABLE_PATH = REPO_ROOT / "rule-catalog" / "risk-classification.yaml"

_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
_SOURCE_REVISION = "commit:" + "a" * 40
_PROCESS_ID = "process-recovery-authority-1"
_OTHER_PROCESS_ID = "process-recovery-authority-2"
_FAILED_PROPOSAL = "sha256:" + "b" * 64
_ACTION_TYPE = "workflow.recovery.reconcile"
_PARAMS: dict[str, object] = {"reason": "reconcile the partially applied change"}


def _attempt(target_ref: str, *, process_id: str = _PROCESS_ID) -> RecoveryAttemptIdentity:
    return RecoveryAttemptIdentity.create(
        process_id=process_id,
        failed_compensation_proposal_digest=_FAILED_PROPOSAL,
        hold_revision=1,
        recovery_action_type=_ACTION_TYPE,
        recovery_payload_digest=content_digest(
            {
                "action_type": _ACTION_TYPE,
                "params": dict(_PARAMS),
                "purpose": "workflow-recovery-payload",
            }
        ),
        target_digest=f"sha256:{hashlib.sha256(target_ref.encode()).hexdigest()}",
        source_revision=_SOURCE_REVISION,
        attempt_number=1,
    )


def _recovery_action(
    valid_action: dict[str, Any],
    action_type: OntologyActionType,
    *,
    target_ref: str,
    process_id: str,
    step_id: str,
) -> Action:
    return Action.model_validate(valid_action).model_copy(
        update={
            "action_type": action_type.name,
            "target_resource_ref": target_ref,
            "workflow_action": WorkflowActionRef(
                process_id=process_id,
                step_id=step_id,
                proposal_ref=f"{process_id}:step:{step_id}:attempt:1",
            ),
        }
    )


def _loop(
    holds: StateStoreAutomationHoldLedger,
    *,
    action_type: OntologyActionType,
    rule: Rule,
    audit_store: MagicMock,
) -> ControlLoop:
    return ControlLoop(
        event_ingest=MagicMock(),
        trust_router=MagicMock(),
        t0_engine=MagicMock(),
        action_builder=MagicMock(),
        executor=MagicMock(),
        audit_store=audit_store,
        rules_by_id={rule.id: rule},
        risk_table=load_risk_table(TABLE_PATH),
        action_types_by_name={action_type.name: action_type},
        risk_gate=RiskGate(registry=ActionPromotionRegistry(allow_legacy_metrics=True)),
        automation_hold_reader=holds,
    )


async def _commitment_store(target_ref: str) -> ProcessRuntimeSafeguardCommitmentStore:
    process_store = InMemoryProcessRuntimeStore()
    await process_store.create(
        snapshot=ProcessSnapshot(
            process_id=_PROCESS_ID,
            workflow_ref="recovery-flow",
            workflow_version="1",
            status=ProcessStatus.COMPENSATING,
            current_step="compensate_apply_first",
            target_resource_id=target_ref,
            started_at=_NOW,
            updated_at=_NOW,
            correlation_id="correlation-recovery-authority-1",
        ),
        event=ProcessEvent(
            event_id="event-created",
            process_id=_PROCESS_ID,
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key=f"{_PROCESS_ID}:created",
            recorded_at=_NOW,
            correlation_id="correlation-recovery-authority-1",
        ),
    )
    return ProcessRuntimeSafeguardCommitmentStore(process_store)


def _safeguard_executor(
    audit: InMemoryStateStore,
    holds: StateStoreAutomationHoldLedger,
    commitments: ProcessRuntimeSafeguardCommitmentStore,
) -> tuple[DirectApiShadowExecutor, RecordingDirectApiExecutor]:
    lock = ResourceLockManager(clock=lambda: _NOW, acquisition_id_factory=lambda: "test")
    reservations = InMemoryIdempotencyReservationStore()
    fences = InMemoryTargetDispatchFenceStore()
    coordinator = SafeguardLifecycleCoordinator(
        resource_lock=lock,
        reservation_store=reservations,
        audit_intent_store=InMemoryAuditIntentStore(),
        fence_store=fences,
        evidence_store=InMemorySafeguardDispatchEvidenceStore(),
        closure_store=InMemoryPostReleaseClosureStore(
            reservation_store=reservations,
            fence_store=fences,
        ),
        denial_audit_store=audit,
        continuity_policy=EffectSinkContinuityPolicy.create(
            sink_id="test-dispatch",
            sink_version="1.0.0",
            strategy=OwnershipContinuityStrategy.QUARANTINED_RECONCILIATION,
            cancellation_supported=True,
            durable_unknown_quarantine=True,
            reconciliation_supported=True,
        ),
        config=SafeguardLifecycleCoordinatorConfig(
            source_revision=_SOURCE_REVISION,
            producer_id="fdai.core.executor",
            producer_version="1.0.0",
            actor="fdai.core.executor",
            expected_lock_verifier_id="fdai-in-memory-lock-readback",
            expected_lock_verifier_version="1.0.0",
            expected_lock_trust_anchor_id="fdai:local-test-only",
        ),
        commitment_store=commitments,
        hold_state_reader=holds,
        hold_release_authorizations=holds,
        clock=lambda: _NOW,
    )
    adapter = RecordingDirectApiExecutor()
    executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )
    return executor, adapter


class TestApprovedRecoveryReachesSafeguardExecution:
    async def test_the_authorized_recovery_step_passes_the_gate_and_dispatches(
        self,
        valid_event: dict[str, Any],
        valid_action: dict[str, Any],
        valid_rule: dict[str, Any],
        valid_ontology_action_type: dict[str, Any],
    ) -> None:
        store = InMemoryStateStore(linearization_clock=lambda: _NOW)
        holds = StateStoreAutomationHoldLedger(store, clock=lambda: _NOW)
        executor_action = _direct_action()
        target_ref = executor_action.target_resource_ref
        attempt = _attempt(target_ref)
        step_id = recovery_attempt_step_id(attempt)
        await holds.issue(
            target_ref=target_ref,
            process_id=_PROCESS_ID,
            reason="compensation_failed",
        )
        assert await holds.authorize_hold_scoped_dispatch(
            target_ref=target_ref,
            process_id=_PROCESS_ID,
            step_id=step_id,
            hold_revision=1,
        )

        action_type = OntologyActionType.model_validate(valid_ontology_action_type)
        rule = Rule.model_validate(valid_rule).model_copy(update={"remediates": action_type.name})
        audit_store = MagicMock()
        audit_store.append_audit_entry = AsyncMock()
        unified = await _loop(
            holds,
            action_type=action_type,
            rule=rule,
            audit_store=audit_store,
        )._evaluate_and_audit(
            event=Event.model_validate(valid_event),
            action=_recovery_action(
                valid_action,
                action_type,
                target_ref=target_ref,
                process_id=_PROCESS_ID,
                step_id=step_id,
            ),
            rule=rule,
        )

        assert unified is not None
        assert unified.gate.outcome is RiskDecisionOutcome.HIL
        assert "target_automation_hold_recovery_requires_hil" in unified.gate.reasons

        safeguard_executor, adapter = _safeguard_executor(
            store,
            holds,
            await _commitment_store(target_ref),
        )
        result = await safeguard_executor.execute(
            action=executor_action.model_copy(
                update={
                    "workflow_action": WorkflowActionRef(
                        process_id=_PROCESS_ID,
                        step_id=step_id,
                        proposal_ref=f"{_PROCESS_ID}:step:{step_id}:attempt:1",
                    )
                }
            )
        )

        assert result.outcome is DirectApiExecutionOutcome.DISPATCHED
        assert len(adapter.records) == 1
        assert not any(
            row["entry"].get("action_kind") == "executor.hold_dispatch_fence.denied"
            for row in store.audit_entries
        )


class TestUnprovenRecoveryStillDenies:
    @pytest.mark.parametrize(
        "scenario",
        ["unauthorized", "cross_process", "stale_revision", "generic_recover_step"],
    )
    async def test_the_gate_denies_without_a_current_scoped_authorization(
        self,
        scenario: str,
        valid_event: dict[str, Any],
        valid_action: dict[str, Any],
        valid_rule: dict[str, Any],
        valid_ontology_action_type: dict[str, Any],
    ) -> None:
        store = InMemoryStateStore(linearization_clock=lambda: _NOW)
        holds = StateStoreAutomationHoldLedger(store, clock=lambda: _NOW)
        target_ref = "resource:example/rg/recovery-authority-1"
        attempt = _attempt(target_ref)
        step_id = recovery_attempt_step_id(attempt)
        await holds.issue(
            target_ref=target_ref,
            process_id=_PROCESS_ID,
            reason="compensation_failed",
        )
        process_id = _PROCESS_ID
        evaluated_step = step_id
        if scenario != "unauthorized":
            assert await holds.authorize_hold_scoped_dispatch(
                target_ref=target_ref,
                process_id=_PROCESS_ID,
                step_id=step_id,
                hold_revision=1,
            )
        if scenario == "cross_process":
            process_id = _OTHER_PROCESS_ID
        if scenario == "generic_recover_step":
            evaluated_step = "recover_the_target"
        if scenario == "stale_revision":
            # A second failure supersedes the revision the step was authorized
            # under, so the authorization is evidence of a hold that is gone.
            await store.write_state(
                f"workflow:automation-hold:{hashlib.sha256(target_ref.encode()).hexdigest()}",
                {
                    "target_digest": hashlib.sha256(target_ref.encode()).hexdigest(),
                    "process_id": _PROCESS_ID,
                    "reason": "second_failure",
                    "state": "active",
                    "created_at": _NOW.isoformat(),
                    "revision": 2,
                },
            )

        action_type = OntologyActionType.model_validate(valid_ontology_action_type)
        rule = Rule.model_validate(valid_rule).model_copy(update={"remediates": action_type.name})
        audit_store = MagicMock()
        audit_store.append_audit_entry = AsyncMock()

        unified = await _loop(
            holds,
            action_type=action_type,
            rule=rule,
            audit_store=audit_store,
        )._evaluate_and_audit(
            event=Event.model_validate(valid_event),
            action=_recovery_action(
                valid_action,
                action_type,
                target_ref=target_ref,
                process_id=process_id,
                step_id=evaluated_step,
            ),
            rule=rule,
        )

        assert unified is not None
        assert unified.gate.outcome is RiskDecisionOutcome.DENY
        assert unified.gate.reasons == ("target_automation_hold_active",)

    async def test_a_superseded_revision_also_fences_provider_invocation(
        self,
    ) -> None:
        store = InMemoryStateStore(linearization_clock=lambda: _NOW)
        holds = StateStoreAutomationHoldLedger(store, clock=lambda: _NOW)
        executor_action = _direct_action()
        target_ref = executor_action.target_resource_ref
        attempt = _attempt(target_ref)
        step_id = recovery_attempt_step_id(attempt)
        await holds.issue(
            target_ref=target_ref,
            process_id=_PROCESS_ID,
            reason="compensation_failed",
        )
        assert await holds.authorize_hold_scoped_dispatch(
            target_ref=target_ref,
            process_id=_PROCESS_ID,
            step_id=step_id,
            hold_revision=1,
        )
        await store.write_state(
            f"workflow:automation-hold:{hashlib.sha256(target_ref.encode()).hexdigest()}",
            {
                "target_digest": hashlib.sha256(target_ref.encode()).hexdigest(),
                "process_id": _PROCESS_ID,
                "reason": "second_failure",
                "state": "active",
                "created_at": (_NOW + timedelta(minutes=1)).isoformat(),
                "revision": 2,
            },
        )

        assert not await holds.recovery_eligible(
            target_ref=target_ref,
            process_id=_PROCESS_ID,
            step_id=step_id,
        )

        safeguard_executor, adapter = _safeguard_executor(
            store,
            holds,
            await _commitment_store(target_ref),
        )
        result = await safeguard_executor.execute(
            action=executor_action.model_copy(
                update={
                    "workflow_action": WorkflowActionRef(
                        process_id=_PROCESS_ID,
                        step_id=step_id,
                        proposal_ref=f"{_PROCESS_ID}:step:{step_id}:attempt:1",
                    )
                }
            )
        )

        assert result.outcome is not DirectApiExecutionOutcome.DISPATCHED
        assert len(adapter.records) == 0
        denial = next(
            row["entry"]
            for row in store.audit_entries
            if row["entry"].get("action_kind") == "executor.hold_dispatch_fence.denied"
        )
        assert "hold_authorization_mismatch" in denial["rejection_reasons"]
