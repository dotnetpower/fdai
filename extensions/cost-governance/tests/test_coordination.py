from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fdai.shared.providers.cost_governance_decision import (
    COST_RECOVERY_ORDER,
    CostActionOption,
    CostAutonomyCeiling,
    CostCoordinationRequest,
    CostDecisionFrame,
    CostDecisionOutcome,
    CostDependencySnapshot,
    CostRecoveryAttempt,
    CostRecoveryAttemptStatus,
    CostRecoveryStep,
    CostTargetScope,
)

from fdai_cost_governance.coordination import (
    CostCoordinationError,
    CostObservationModeLatch,
    DeterministicCostCoordinator,
)

NOW = datetime(2026, 8, 28, 8, tzinfo=UTC)
DIGEST_A = f"sha256:{'a' * 64}"
DIGEST_B = f"sha256:{'b' * 64}"
DIGEST_C = f"sha256:{'c' * 64}"


def _scope(*targets: str, duration: int = 3600, impact: int = 4) -> CostTargetScope:
    return CostTargetScope(
        target_refs=targets or ("resource-a", "resource-b"),
        duration_seconds=duration,
        capacity_delta=Decimal("-4"),
        impact_units=impact,
    )


def _options(scope: CostTargetScope) -> tuple[CostActionOption, ...]:
    return (
        CostActionOption(
            option_id="option-unsafe",
            action_type_id="remediate.resize-vm-down",
            scope=scope,
            unsafe_reasons=("service-objective-conflict",),
            reversible=True,
            safeguards_complete=True,
        ),
        CostActionOption(
            option_id="option-safe",
            action_type_id="remediate.resize-vm-down",
            scope=scope,
            unsafe_reasons=(),
            reversible=True,
            safeguards_complete=True,
        ),
        CostActionOption(
            option_id="option-no-action",
            action_type_id=None,
            scope=scope,
            unsafe_reasons=(),
            reversible=True,
            safeguards_complete=True,
            no_action=True,
        ),
    )


def _frame() -> CostDecisionFrame:
    scope = _scope("resource-a", "resource-b")
    return CostDecisionFrame(
        episode_id="episode-1",
        package_id="fdai-cost-governance",
        ontology_release_digest=DIGEST_A,
        semantic_profile_digest=DIGEST_B,
        evidence_cutoff=NOW,
        scope=scope,
        options=_options(scope),
        selected_option_id=None,
        unresolved_facts=("cost-fact",),
        evidence_refs=(DIGEST_C,),
    )


def _next_frame(
    frame: CostDecisionFrame,
    step: CostRecoveryStep,
) -> CostDecisionFrame:
    if step is CostRecoveryStep.REACQUIRE_CONTEXT:
        return replace(frame, evidence_cutoff=frame.evidence_cutoff + timedelta(minutes=1))
    if step is CostRecoveryStep.INDEPENDENT_SOURCE:
        return replace(frame, evidence_refs=(*frame.evidence_refs, DIGEST_A))
    if step is CostRecoveryStep.REMOVE_UNSAFE_OPTIONS:
        return replace(
            frame,
            options=tuple(option for option in frame.options if not option.unsafe_reasons),
            unresolved_facts=(),
        )
    if step is CostRecoveryStep.REDUCE_SCOPE:
        smaller = _scope("resource-a", duration=1800, impact=1)
        return replace(
            frame,
            scope=smaller,
            options=tuple(replace(option, scope=smaller) for option in frame.options),
        )
    if step is CostRecoveryStep.SELECT_SAFE_OPTION:
        return replace(frame, selected_option_id="option-safe")
    return replace(frame)


def _attempts(
    *,
    through: CostRecoveryStep = CostRecoveryStep.RESIDUAL_APPROVAL,
    target_status: CostRecoveryAttemptStatus = CostRecoveryAttemptStatus.SUCCESS,
    target_ceiling: CostAutonomyCeiling = CostAutonomyCeiling.EXECUTION_ELIGIBLE,
) -> tuple[CostRecoveryAttempt, ...]:
    frame = _frame()
    attempts: list[CostRecoveryAttempt] = []
    for index, step in enumerate(COST_RECOVERY_ORDER):
        status = target_status if step is through else CostRecoveryAttemptStatus.SUCCESS
        ceiling = target_ceiling if step is through else CostAutonomyCeiling.EXECUTION_ELIGIBLE
        output = _next_frame(frame, step) if status is CostRecoveryAttemptStatus.SUCCESS else None
        attempts.append(
            CostRecoveryAttempt(
                step=step,
                status=status,
                hypothesis_id=f"hypothesis-{index}",
                input_frame_digest=frame.digest,
                autonomy_ceiling=ceiling,
                evidence_refs=(f"evidence-{index}",),
                attempted_at=NOW + timedelta(minutes=index + 1),
                output_frame=output,
                independent_source_authority=(
                    "independent-cost-evidence"
                    if step is CostRecoveryStep.INDEPENDENT_SOURCE
                    and status is CostRecoveryAttemptStatus.SUCCESS
                    else None
                ),
            )
        )
        if output is not None:
            frame = output
        if step is through:
            break
    return tuple(attempts)


def _request(
    *,
    attempts: tuple[CostRecoveryAttempt, ...] | None = None,
    dependencies: CostDependencySnapshot | None = None,
    saga_intent: str | None = DIGEST_A,
    terminal_audit: str | None = DIGEST_B,
    approval_granted: bool | None = None,
    approval_receipt: str | None = None,
    frame: CostDecisionFrame | None = None,
    ceiling: CostAutonomyCeiling = CostAutonomyCeiling.EXECUTION_ELIGIBLE,
) -> CostCoordinationRequest:
    return CostCoordinationRequest(
        frame=frame or _frame(),
        attempts=attempts if attempts is not None else _attempts(),
        dependencies=dependencies
        or CostDependencySnapshot(
            saga_available=True,
            vidar_available=True,
            forseti_available=True,
            heimdall_available=True,
            var_available=True,
            observed_at=NOW,
        ),
        initial_ceiling=ceiling,
        hold_deadline=NOW + timedelta(hours=2),
        saga_intent_audit_digest=saga_intent,
        terminal_audit_digest=terminal_audit,
        approval_granted=approval_granted,
        approval_receipt_digest=approval_receipt,
    )


@pytest.mark.parametrize("step", COST_RECOVERY_ORDER)
@pytest.mark.parametrize("status", CostRecoveryAttemptStatus)
def test_every_recovery_step_status_is_bounded(
    step: CostRecoveryStep,
    status: CostRecoveryAttemptStatus,
) -> None:
    result = DeterministicCostCoordinator().coordinate(
        _request(attempts=_attempts(through=step, target_status=status))
    )

    assert result.outcome in CostDecisionOutcome
    assert result.decision_frame_digest.startswith("sha256:")


def test_complete_trace_selects_effect_request_without_executing() -> None:
    result = DeterministicCostCoordinator().coordinate(_request())

    assert result.outcome is CostDecisionOutcome.EXECUTE
    assert result.terminal is False
    assert DIGEST_A in result.evidence_refs


@pytest.mark.parametrize("missing", ["saga", "vidar"])
def test_hard_dependency_failure_is_sticky_observation_mode(missing: str) -> None:
    latch = CostObservationModeLatch()
    coordinator = DeterministicCostCoordinator(latch=latch)
    values = {"saga_available": True, "vidar_available": True}
    values[f"{missing}_available"] = False
    degraded = CostDependencySnapshot(
        forseti_available=True,
        heimdall_available=True,
        var_available=True,
        observed_at=NOW,
        **values,
    )

    first = coordinator.coordinate(_request(dependencies=degraded))
    second = coordinator.coordinate(_request())

    assert first.outcome is CostDecisionOutcome.HOLD
    assert first.observation_mode is True
    assert second.observation_mode is True


def test_missing_forseti_produces_no_fallback_judgment() -> None:
    dependencies = replace(_request().dependencies, forseti_available=False)

    result = DeterministicCostCoordinator().coordinate(_request(dependencies=dependencies))

    assert result.outcome is CostDecisionOutcome.HOLD
    assert result.reason == "forseti_judgment_unavailable"


def test_missing_heimdall_does_not_claim_successful_closure() -> None:
    dependencies = replace(_request().dependencies, heimdall_available=False)

    result = DeterministicCostCoordinator().coordinate(_request(dependencies=dependencies))

    assert result.outcome is CostDecisionOutcome.EXECUTE
    assert result.terminal is False


def test_saga_intent_audit_is_required_before_effect_request() -> None:
    result = DeterministicCostCoordinator().coordinate(_request(saga_intent=None))

    assert result.outcome is CostDecisionOutcome.HOLD
    assert result.reason == "saga_intent_audit_required"


def test_var_silence_never_permits_execution() -> None:
    attempts = _attempts(
        target_ceiling=CostAutonomyCeiling.APPROVAL,
    )
    result = DeterministicCostCoordinator().coordinate(
        _request(
            attempts=attempts,
            ceiling=CostAutonomyCeiling.EXECUTION_ELIGIBLE,
            approval_granted=None,
            approval_receipt=None,
        )
    )

    assert result.outcome is CostDecisionOutcome.APPROVAL
    assert result.terminal is False


def test_verified_var_approval_still_requires_saga_intent() -> None:
    attempts = _attempts(target_ceiling=CostAutonomyCeiling.APPROVAL)
    result = DeterministicCostCoordinator().coordinate(
        _request(
            attempts=attempts,
            approval_granted=True,
            approval_receipt=DIGEST_C,
            saga_intent=None,
        )
    )

    assert result.outcome is CostDecisionOutcome.HOLD


def test_no_op_counts_only_with_terminal_audit() -> None:
    attempts = list(_attempts(through=CostRecoveryStep.SELECT_SAFE_OPTION))
    selected = replace(attempts[-1].output_frame, selected_option_id="option-no-action")
    attempts[-1] = replace(attempts[-1], output_frame=selected)

    pending = DeterministicCostCoordinator().coordinate(
        _request(attempts=tuple(attempts), terminal_audit=None)
    )
    terminal = DeterministicCostCoordinator().coordinate(
        _request(attempts=tuple(attempts), terminal_audit=DIGEST_B)
    )

    assert pending.outcome is CostDecisionOutcome.NO_OP
    assert pending.terminal is False
    assert terminal.terminal is True


def test_policy_and_approval_denials_are_distinct_terminal_records() -> None:
    denied_frame = replace(_frame(), policy_denied=True)
    policy = DeterministicCostCoordinator().coordinate(
        _request(frame=denied_frame, attempts=(), terminal_audit=DIGEST_B)
    )
    approval = DeterministicCostCoordinator().coordinate(
        _request(
            attempts=_attempts(target_ceiling=CostAutonomyCeiling.APPROVAL),
            approval_granted=False,
            approval_receipt=DIGEST_C,
        )
    )

    assert policy.outcome is CostDecisionOutcome.DENY
    assert policy.reason == "policy_denied"
    assert approval.outcome is CostDecisionOutcome.DENY
    assert approval.reason == "approval_denied"
    assert policy.terminal and approval.terminal


def test_rollback_request_remains_pending_for_vidar() -> None:
    frame = replace(_frame(), rollback_required=True)

    result = DeterministicCostCoordinator().coordinate(_request(frame=frame, attempts=()))

    assert result.outcome is CostDecisionOutcome.ROLLBACK
    assert result.terminal is False


def test_out_of_order_duplicate_hypothesis_and_retry_are_rejected() -> None:
    attempts = _attempts(through=CostRecoveryStep.INDEPENDENT_SOURCE)
    out_of_order = (attempts[1], attempts[0])
    with pytest.raises(CostCoordinationError, match="fixed bounded order"):
        DeterministicCostCoordinator().coordinate(_request(attempts=out_of_order))

    duplicate = (attempts[0], replace(attempts[1], hypothesis_id=attempts[0].hypothesis_id))
    with pytest.raises(CostCoordinationError, match="new hypothesis"):
        DeterministicCostCoordinator().coordinate(_request(attempts=duplicate))

    retry = (attempts[0], replace(attempts[0], hypothesis_id="another-hypothesis"))
    with pytest.raises(CostCoordinationError, match="fixed bounded order"):
        DeterministicCostCoordinator().coordinate(_request(attempts=retry))


def test_recovery_cannot_widen_scope_change_release_or_raise_ceiling() -> None:
    first = _attempts(through=CostRecoveryStep.REACQUIRE_CONTEXT)[0]
    widened = replace(
        first.output_frame,
        scope=_scope("resource-a", "resource-b", "resource-c", impact=5),
    )
    with pytest.raises(CostCoordinationError, match="widen"):
        DeterministicCostCoordinator().coordinate(
            _request(attempts=(replace(first, output_frame=widened),))
        )

    changed_release = replace(first.output_frame, ontology_release_digest=DIGEST_C)
    with pytest.raises(CostCoordinationError, match="exact package and release"):
        DeterministicCostCoordinator().coordinate(
            _request(attempts=(replace(first, output_frame=changed_release),))
        )

    raised = replace(first, autonomy_ceiling=CostAutonomyCeiling.EXECUTION_ELIGIBLE)
    with pytest.raises(CostCoordinationError, match="raise autonomy"):
        DeterministicCostCoordinator().coordinate(
            _request(
                attempts=(raised,),
                ceiling=CostAutonomyCeiling.APPROVAL,
            )
        )


def test_recovery_cannot_relabel_an_unsafe_option_as_safe() -> None:
    attempts = list(_attempts(through=CostRecoveryStep.REMOVE_UNSAFE_OPTIONS))
    prior = attempts[-2].output_frame
    assert prior is not None
    relabeled = replace(
        prior,
        options=tuple(
            replace(option, unsafe_reasons=()) if option.option_id == "option-unsafe" else option
            for option in prior.options
        ),
    )
    attempts[-1] = replace(attempts[-1], output_frame=relabeled)

    with pytest.raises(CostCoordinationError, match="preserve option safety"):
        DeterministicCostCoordinator().coordinate(_request(attempts=tuple(attempts)))


def test_recovery_attempt_after_hold_deadline_is_rejected() -> None:
    attempt = replace(
        _attempts(through=CostRecoveryStep.REACQUIRE_CONTEXT)[0],
        attempted_at=NOW + timedelta(hours=3),
    )

    with pytest.raises(CostCoordinationError, match="bounded hold deadline"):
        DeterministicCostCoordinator().coordinate(_request(attempts=(attempt,)))


def test_public_coordinator_has_no_agent_or_effect_methods() -> None:
    names = set(dir(DeterministicCostCoordinator))

    assert not names & {"approve", "execute", "audit", "rollback", "call_agent"}


def test_package_coordination_has_no_agent_import_or_authority_operation() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "src/fdai_cost_governance/coordination.py"
    ).read_text(encoding="utf-8")

    assert "fdai.agents" not in source
    assert ".approve(" not in source
    assert ".execute(" not in source
    assert ".rollback(" not in source
    assert ".append_audit" not in source
