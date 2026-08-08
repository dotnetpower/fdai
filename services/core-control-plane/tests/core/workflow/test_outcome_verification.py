from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fdai.core.workflow import StateStoreWorkflowOutcomeLedger
from fdai.shared.contracts.models import (
    Action,
    BlastRadius,
    Mode,
    ResponseOutcome,
    ResponseOutcomeLabel,
    ResponseVerificationStatus,
    RollbackRef,
    WorkflowActionRef,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _action(*, mode: Mode = Mode.ENFORCE) -> Action:
    return Action(
        schema_version="1.0.0",
        action_id=uuid4(),
        event_id=uuid4(),
        idempotency_key="action-1",
        mode=mode,
        action_type="ops.restart-service",
        operation="restart",
        target_resource_ref="resource-1",
        params={},
        stop_condition="provider_api_error_streak",
        stop_conditions=[{"kind": "provider_api_error_streak", "count": 1}],
        rollback_ref=RollbackRef(kind="state_forward_only"),
        blast_radius=BlastRadius(scope="resource"),
        citing_rules=["rule-1"],
        created_at=datetime.now(tz=UTC),
        workflow_action=WorkflowActionRef(
            process_id="process-1",
            step_id="restart",
            proposal_ref="process-1:step:restart:attempt:1",
        ),
    )


def _response(action: Action, *, verified: bool) -> ResponseOutcome:
    now = datetime.now(tz=UTC)
    return ResponseOutcome(
        schema_version="1.0.0",
        outcome_id=uuid4(),
        idempotency_key=f"response-{uuid4()}",
        action_id=action.action_id,
        event_id=action.event_id,
        action_type_id=action.action_type,
        target_digest="0" * 64,
        prediction_id="prediction-1" if verified else None,
        metric="availability" if verified else None,
        expected_min=0.99 if verified else None,
        expected_max=1.0 if verified else None,
        observed_value=1.0 if verified else None,
        predicted_at=now if verified else None,
        observation_deadline=now if verified else None,
        observed_at=now if verified else None,
        label=ResponseOutcomeLabel.VERIFIED if verified else ResponseOutcomeLabel.UNSCORABLE,
        verification_status=(
            ResponseVerificationStatus.VERIFIED if verified else ResponseVerificationStatus.HOLD
        ),
        verification_reason="within_bounds" if verified else "observation_unavailable",
        execution_mode=action.mode,
        execution_outcome="dispatched",
        decision="auto",
        evidence_refs=("effect:prediction-1",),
        recorded_at=now,
    )


async def test_verified_success_requires_exact_durable_lineage_and_receipt() -> None:
    ledger = StateStoreWorkflowOutcomeLedger(InMemoryStateStore())
    action = _action()
    receipt_ref = await ledger.record(
        action=action,
        execution_outcome="dispatched",
        execution_receipt_ref="provider-receipt-1",
        response_outcome=_response(action, verified=True),
    )

    assert receipt_ref is not None
    assert await ledger.verify(
        process_id="process-1",
        step_id="restart",
        proposal_ref="process-1:step:restart:attempt:1",
        outcome="succeeded",
        receipt_ref=receipt_ref,
    )
    resolved = await ledger.resolve(
        process_id="process-1",
        step_id="restart",
        proposal_ref="process-1:step:restart:attempt:1",
    )
    assert resolved is not None
    assert resolved.outcome == "succeeded"
    assert resolved.receipt_ref == receipt_ref
    assert not await ledger.verify(
        process_id="process-forged",
        step_id="restart",
        proposal_ref="process-1:step:restart:attempt:1",
        outcome="succeeded",
        receipt_ref=receipt_ref,
    )
    assert not await ledger.verify(
        process_id="process-1",
        step_id="restart",
        proposal_ref="process-1:step:restart:attempt:1",
        outcome="succeeded",
        receipt_ref="forged-receipt",
    )


async def test_unverified_execution_success_does_not_create_success_receipt() -> None:
    ledger = StateStoreWorkflowOutcomeLedger(InMemoryStateStore())
    action = _action()

    receipt_ref = await ledger.record(
        action=action,
        execution_outcome="dispatched",
        execution_receipt_ref="provider-receipt-1",
        response_outcome=_response(action, verified=False),
    )

    assert receipt_ref is None


async def test_verified_shadow_execution_does_not_advance_enforce_workflow() -> None:
    ledger = StateStoreWorkflowOutcomeLedger(InMemoryStateStore())
    action = _action(mode=Mode.SHADOW)

    receipt_ref = await ledger.record(
        action=action,
        execution_outcome="dispatched",
        execution_receipt_ref="shadow-receipt-1",
        response_outcome=_response(action, verified=True),
    )

    assert receipt_ref is None
