"""Explicit synthetic unit scenarios, never production truth, approval or promotion evidence.

Production-shaped observations below exist only to exercise the pure boundary. No fixture
is installed in runtime composition, and no external provider is called by these tests.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.detection.alert_noise.admission import effect_outcome
from fdai.core.detection.alert_noise.execution import RESTORE_ACTION, alert_execution_key
from fdai.core.detection.alert_noise.outcomes import (
    ALERT_EFFECT_PURPOSE,
    ALERT_RECOVERY_EFFECT_PURPOSE,
    AlertEffectContext,
    AlertEffectDrift,
    AlertExecutedActionRecord,
    AlertExecutionNotice,
    alert_effect_deadline,
    alert_effect_key,
    alert_executed_action_key,
    alert_response_outcome,
    classify_alert_effect,
    require_alert_dispatch_lineage,
)
from fdai.core.executor.safeguards import full_action_digest
from fdai.core.workflow.workflow_runtime import event_id
from fdai.shared.contracts.models import (
    Action,
    Mode,
    Operation,
    ResponseOutcome,
    ResponseOutcomeLabel,
    RollbackKind,
    RollbackRef,
    WorkflowActionRef,
)
from fdai.shared.providers.process_runtime import ProcessEvent, ProcessEventKind
from fdai.shared.providers.remediation_pr import PublishReceipt
from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_plan import (
    AlertChangePlan,
    AlertEffectObservation,
    AlertTreatment,
)
from tests.core.executor.test_executor import _action

_NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
_BUNDLE = "sha256:" + "b" * 64
_RECEIPT = "sha256:" + "c" * 64


def _fixture_plan() -> AlertChangePlan:
    """Declare small synthetic timing budgets, not configured production defaults."""
    return AlertChangePlan(
        action_type="ops.update-alert-routing",
        tenant_ref="tenant:example",
        scope_ref="scope:example",
        requester_ref="person:requester",
        evidence_digest="sha256:" + "a" * 64,
        policy_digest="sha256:" + "d" * 64,
        target_revision="sha256:" + "e" * 64,
        treatment=AlertTreatment(
            kind="routing",
            target_ref="rule:example",
            remove_group_ref="group:old",
            replacement_group_ref="group:new",
        ),
        service_refs=("service:example",),
        lock_refs=("rule:example",),
        created_at=_NOW,
        expires_at=_NOW + timedelta(hours=24),
        max_execution_seconds=300,
        max_observation_seconds=600,
        max_recovery_seconds=300,
        rollback_ref="sha256:" + "f" * 64,
    )


def _event(
    kind: ProcessEventKind, step: str, suffix: str, at: datetime, **payload: Any
) -> ProcessEvent:
    return ProcessEvent(
        event_id=event_id("process:example", suffix),
        process_id="process:example",
        kind=kind,
        idempotency_key="process:example:" + suffix,
        recorded_at=at,
        correlation_id="trace:example",
        step_id=step,
        payload=payload,
    )


def _fixture_context(
    *,
    restore: bool = False,
    plan: AlertChangePlan | None = None,
    dispatched_at: datetime | None = None,
) -> AlertEffectContext:
    """Build typed unit-only publication and journal facts, without pretending to admit them."""
    plan = plan or _fixture_plan()
    at = dispatched_at or (_NOW + timedelta(seconds=1000) if restore else _NOW)
    step = "compensate_update_routing" if restore else "update_routing"
    action_type = RESTORE_ACTION if restore else plan.action_type
    proposal = f"process:example:step:{step}:attempt:1"
    values = _action(
        mode=Mode.ENFORCE,
        target=plan.treatment.processing_rule_ref or plan.treatment.target_ref,
        action_id="00000000-0000-0000-0000-000000000012"
        if restore
        else "00000000-0000-0000-0000-000000000010",
    ).model_dump(mode="python")
    values.update(
        action_type=action_type,
        operation=Operation.UPDATE,
        created_at=at,
        params={"plan_digest": digest_record(plan)[7:]},
        executor_identity_ref="executor:example",
        idempotency_key=alert_execution_key(action_type, digest_record(plan)),
        rollback_ref=RollbackRef(kind=RollbackKind.PR_REVERT, reference=plan.rollback_ref),
        workflow_action=WorkflowActionRef(
            process_id="process:example", step_id=step, proposal_ref=proposal
        ),
    )
    action = Action.model_validate(values)
    execution = AlertExecutedActionRecord(
        action=action,
        plan=plan,
        publication_receipt=PublishReceipt(pr_ref="pr:example"),
        execution_outcome="published",
        dispatch_generation=1,
        source_event=AlertExecutionNotice(
            producer_principal="Thor",
            action_id=action.action_id,
            action_digest=full_action_digest(action),
            correlation_id="trace:example",
            state="succeeded",
            terminal_at=at + timedelta(seconds=1),
        ),
    )
    original = _event(
        ProcessEventKind.ACTION_DISPATCHED,
        "update_routing",
        "step:update_routing:attempt:1:action-dispatched",
        _NOW,
        proposal_ref="process:example:step:update_routing:attempt:1",
        action_type=plan.action_type,
        params=dict(action.params),
    )
    events = (original,)
    if restore:
        completed = _event(
            ProcessEventKind.STEP_COMPLETED,
            "update_routing",
            "fixture-completed",
            _NOW + timedelta(seconds=700),
            reason="action_effect_verified",
            safeguard_bundle_digest="sha256:" + "a" * 64,
        )
        intent = _event(
            ProcessEventKind.COMPENSATION_STARTED,
            step,
            "fixture-compensation",
            at - timedelta(seconds=1),
            compensates_step_id="update_routing",
            action_type=RESTORE_ACTION,
            params=dict(action.params),
            original_safeguard_bundle_digest="sha256:" + "a" * 64,
        )
        dispatch = _event(
            ProcessEventKind.COMPENSATION_DISPATCHED,
            step,
            "compensation:update_routing:dispatched",
            at,
            proposal_ref=proposal,
            action_type=RESTORE_ACTION,
            compensates_step_id="update_routing",
        )
        events = (original, completed, intent, dispatch)
    return AlertEffectContext(
        execution,
        at,
        _BUNDLE,
        ALERT_RECOVERY_EFFECT_PURPOSE if restore else ALERT_EFFECT_PURPOSE,
        events,
    )


def _fixture_observation(context: AlertEffectContext, **changes: Any) -> AlertEffectObservation:
    """Positive booleans are explicit unit data; real readers may only decode admitted facts."""
    start = context.dispatched_at + timedelta(seconds=2)
    end = start + timedelta(seconds=context.execution.plan.max_observation_seconds)
    values: dict[str, Any] = {
        "plan_digest": digest_record(context.execution.plan),
        "dispatch_ref": context.execution.dispatch_ref,
        "source_ref": "source:example",
        "observer_ref": "observer:example",
        "executor_ref": "executor:example",
        "window_start": start,
        "window_end": end,
        "recorded_at": end + timedelta(seconds=1),
        "coverage": "complete",
        "configuration_matches": True,
        "collection_continues": True,
        "protected_paths_preserved": True,
        "response_deadlines_preserved": True,
        "expected_delivery_observed": True,
        "eligible_events": 8,
        "failures": 0,
        "missed_incidents": 0,
        "synthetic": False,
        "receipt_ref": "observation:example",
        "recovery": context.purpose == ALERT_RECOVERY_EFFECT_PURPOSE,
        "execution_authority": False,
    }
    return AlertEffectObservation.model_validate({**values, **changes})


def test_provider_publication_without_observation_is_held() -> None:
    context = _fixture_context()
    assert context.execution.execution_outcome == "published"
    assert classify_alert_effect(context, None, now=_NOW + timedelta(hours=1)) == "held"


def test_recovery_boolean_cannot_turn_a_forward_effect_into_recovery() -> None:
    context = _fixture_context()
    observation = _fixture_observation(context, recovery=True)
    assert (
        effect_outcome(
            context.execution.plan,
            observation,
            dispatch_ref=context.execution.dispatch_ref,
            dispatched_at=context.dispatched_at,
            now=observation.recorded_at,
        )
        == "recovered"
    )
    assert classify_alert_effect(context, observation, now=observation.recorded_at) == "held"


@pytest.mark.parametrize("restore", [False, True])
@pytest.mark.parametrize(
    "changes",
    [
        {"configuration_matches": False},
        {"collection_continues": False},
        {"protected_paths_preserved": False},
        {"response_deadlines_preserved": False},
        {"failures": 1},
        {"missed_incidents": 1},
    ],
)
def test_independent_guard_regression_needs_recovery_even_with_fewer_messages(
    restore, changes
) -> None:
    context = _fixture_context(restore=restore)
    observation = _fixture_observation(context, eligible_events=1, **changes)
    assert classify_alert_effect(context, observation, now=observation.recorded_at) == (
        "recovery_incomplete" if restore else "recovery_required"
    )


@pytest.mark.parametrize("restore", [False, True])
@pytest.mark.parametrize("changes", [{"eligible_events": 0}, {"expected_delivery_observed": False}])
def test_empty_or_unobserved_delivery_is_never_success(restore, changes) -> None:
    context = _fixture_context(restore=restore)
    observation = _fixture_observation(context, **changes)
    assert classify_alert_effect(context, observation, now=observation.recorded_at) == (
        "recovery_incomplete" if restore else "unscorable"
    )
    response = alert_response_outcome(
        context, observation, receipt_digest=_RECEIPT, now=observation.recorded_at
    )
    assert response is not None and response.label is ResponseOutcomeLabel.UNSCORABLE
    assert response.observed_value is None and response.observed_at is None


@pytest.mark.parametrize(
    "changes",
    [
        {"synthetic": True},
        {"coverage": "partial"},
        {"coverage": "unavailable"},
        {"dispatch_ref": "proposal:other"},
        {"plan_digest": "sha256:" + "0" * 64},
        {"executor_ref": "executor:other"},
        {"window_start": _NOW - timedelta(seconds=1)},
        {"window_end": _NOW + timedelta(seconds=20)},
        {"recorded_at": _NOW + timedelta(seconds=901)},
        {"window_end": _NOW + timedelta(seconds=901), "recorded_at": _NOW + timedelta(seconds=902)},
    ],
)
def test_mismatched_synthetic_short_and_late_observations_hold(changes) -> None:
    context = _fixture_context()
    observation = _fixture_observation(context, **changes)
    assert classify_alert_effect(context, observation, now=observation.recorded_at) == "held"


def test_adverse_short_window_is_not_delayed_for_a_better_sample() -> None:
    context = _fixture_context()
    observation = _fixture_observation(
        context, window_end=_NOW + timedelta(seconds=10), missed_incidents=1
    )
    assert (
        classify_alert_effect(context, observation, now=observation.recorded_at)
        == "recovery_required"
    )


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "wrong_digest", "reordered", "same_bundle"]
)
def test_restore_requires_actual_independent_forward_and_compensation_lineage(change) -> None:
    context = _fixture_context(restore=True)
    original, completed, intent, dispatch = context.process_events
    if change == "missing":
        events = (original, dispatch)
    elif change == "duplicate":
        events = (*context.process_events, dispatch)
    elif change == "wrong_digest":
        events = (
            original,
            completed,
            replace(
                intent,
                payload={
                    **intent.payload,
                    "original_safeguard_bundle_digest": "sha256:" + "0" * 64,
                },
            ),
            dispatch,
        )
    elif change == "reordered":
        events = (original, intent, completed, dispatch)
    else:
        events = (
            original,
            replace(completed, payload={**completed.payload, "safeguard_bundle_digest": _BUNDLE}),
            replace(
                intent, payload={**intent.payload, "original_safeguard_bundle_digest": _BUNDLE}
            ),
            dispatch,
        )
    context = replace(context, process_events=events)
    observation = _fixture_observation(context)
    assert classify_alert_effect(context, observation, now=observation.recorded_at) == "held"


def test_expired_forward_plan_does_not_supply_or_prevent_separately_dispatched_restore() -> None:
    plan = _fixture_plan()
    at = plan.expires_at + timedelta(seconds=1)
    forward = _fixture_context(plan=plan, dispatched_at=at)
    observation = _fixture_observation(forward)
    assert classify_alert_effect(forward, observation, now=observation.recorded_at) == "held"
    recovery = _fixture_context(plan=plan, restore=True, dispatched_at=at)
    observed_restore = _fixture_observation(recovery)
    assert (
        classify_alert_effect(recovery, observed_restore, now=observed_restore.recorded_at)
        == "recovered"
    )
    assert (
        classify_alert_effect(
            replace(recovery, purpose=ALERT_EFFECT_PURPOSE),
            observed_restore,
            now=observed_restore.recorded_at,
        )
        == "held"
    )


def test_wrong_clock_future_receipt_and_missing_dispatch_hold() -> None:
    context = _fixture_context()
    observation = _fixture_observation(context)
    assert classify_alert_effect(context, observation, now=_NOW.replace(tzinfo=None)) == "held"
    assert classify_alert_effect(context, observation, now=observation.window_end) == "held"
    assert (
        classify_alert_effect(
            replace(context, process_events=()), observation, now=observation.recorded_at
        )
        == "held"
    )
    assert (
        classify_alert_effect(
            replace(context, dispatched_at=_NOW.replace(tzinfo=None)),
            observation,
            now=observation.recorded_at,
        )
        == "held"
    )


def _suppression() -> AlertEffectContext:
    values = _fixture_plan().model_dump(mode="python")
    values.update(
        action_type="ops.set-alert-notification-window",
        lock_refs=("processing:example", "rule:example"),
        treatment=AlertTreatment(
            kind="suppression",
            target_ref="rule:example",
            processing_rule_ref="processing:example",
            starts_at=_NOW + timedelta(seconds=1800),
            ends_at=_NOW + timedelta(seconds=2400),
        ),
    )
    return _fixture_context(plan=AlertChangePlan.model_validate(values))


def test_finite_suppression_needs_activation_and_post_expiry_coverage() -> None:
    context = _suppression()
    during = _fixture_observation(context)
    assert classify_alert_effect(context, during, now=during.recorded_at) == "held"
    expired = _NOW + timedelta(seconds=2400)
    at_expiry = _fixture_observation(context, window_end=expired, recorded_at=expired)
    assert classify_alert_effect(context, at_expiry, now=expired) == "held"
    after = _fixture_observation(
        context,
        window_end=expired + timedelta(seconds=1),
        recorded_at=expired + timedelta(seconds=2),
    )
    assert classify_alert_effect(context, after, now=after.recorded_at) == "verified"
    missed_start = _fixture_observation(
        context,
        window_start=_NOW + timedelta(seconds=1801),
        window_end=expired + timedelta(seconds=2),
        recorded_at=expired + timedelta(seconds=3),
    )
    assert classify_alert_effect(context, missed_start, now=missed_start.recorded_at) == "held"
    assert alert_effect_deadline(context) == expired + timedelta(seconds=300)


def test_response_uses_actual_observation_and_is_replay_stable() -> None:
    context = _fixture_context()
    observation = _fixture_observation(context)
    response = alert_response_outcome(
        context, observation, receipt_digest=_RECEIPT, now=observation.recorded_at
    )
    replay = alert_response_outcome(
        context,
        observation,
        receipt_digest=_RECEIPT,
        now=observation.recorded_at + timedelta(seconds=1),
    )
    assert response == replay and response is not None
    assert ResponseOutcome.model_validate(response.model_dump(mode="json")) == response
    assert response.metric == "alert_effect_verified" and response.observed_value == 1.0
    assert response.expected_min == response.expected_max == 1.0
    assert (
        response.observed_at == observation.window_end
        and response.recorded_at == observation.recorded_at
    )
    assert response.action_id == context.execution.action.action_id
    assert response.execution_outcome == "published" and response.rollback_succeeded is None
    adverse = _fixture_observation(context, missed_incidents=1)
    mismatch = alert_response_outcome(
        context, adverse, receipt_digest=_RECEIPT, now=adverse.recorded_at
    )
    assert mismatch is not None and mismatch.label is ResponseOutcomeLabel.MISMATCH
    assert mismatch.observed_value == 0.0


def test_action_digest_covers_fields_outside_execution_fingerprint() -> None:
    context = _fixture_context()
    raw = context.execution.model_dump(mode="json")
    raw["action"]["event_id"] = "00000000-0000-0000-0000-000000000099"
    with pytest.raises(ValueError, match="exact Action"):
        AlertExecutedActionRecord.model_validate(raw)


def test_key_is_bounded_without_truncating_identity() -> None:
    context = _fixture_context()
    digest = digest_record(context.execution.plan)
    key = alert_effect_key(plan_digest=digest, dispatch_ref="r" * 160)
    assert len(key) < 100 and key != alert_effect_key(
        plan_digest=digest, dispatch_ref="r" * 159 + "s"
    )
    assert alert_executed_action_key(full_action_digest(context.execution.action)).endswith(
        context.execution.source_event.action_digest
    )
    with pytest.raises(ValueError):
        alert_effect_key(plan_digest=digest, dispatch_ref="r" * 161)
    require_alert_dispatch_lineage(context)


def test_drift_carries_no_process_completion_or_authority() -> None:
    context = _fixture_context()
    signal = AlertEffectDrift(
        correlation_id="trace:example",
        idempotency_key="effect:example",
        resource_id="rule:example",
        process_id="process:example",
        step_id="update_routing",
        action_digest=full_action_digest(context.execution.action),
        plan_digest=digest_record(context.execution.plan),
        dispatch_ref=context.execution.dispatch_ref,
        outcome_ref="alert-noise:outcome:example",
        effect_outcome="recovery_required",
        workflow_outcome_ref=None,
        recorded_at=_NOW,
    )
    for field in ("execution_authority", "promotion_authority", "process_completed"):
        with pytest.raises(ValueError):
            AlertEffectDrift.model_validate({**signal.model_dump(mode="json"), field: True})


def test_even_a_rehashed_shadow_action_cannot_gain_an_effect_outcome() -> None:
    raw = _fixture_context().execution.model_dump(mode="json")
    raw["action"]["mode"] = "shadow"
    raw["source_event"]["action_digest"] = full_action_digest(Action.model_validate(raw["action"]))
    with pytest.raises(ValueError, match="exact Action"):
        AlertExecutedActionRecord.model_validate(raw)
