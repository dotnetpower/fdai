"""Control-plane recovery plan sequencing and fencing invariants."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fdai.core.verticals.resilience.recovery_plan import (
    LEGAL_RECOVERY_TRANSITIONS,
    RecoveryMode,
    RecoveryObjectives,
    RecoveryPlan,
    RecoveryPlanError,
    RecoveryPlanStateMachine,
    RecoveryProfile,
    RecoveryState,
    RecoveryTransition,
)

_AT = datetime(2026, 7, 31, tzinfo=UTC)
_EVIDENCE = ("evidence://recovery/step",)


def _plan(
    *,
    primary_region: str = "primary-region",
    recovery_region: str = "recovery-region",
    revision: int = 1,
    scope: tuple[str, ...] = ("control-plane", "state-store", "event-bus"),
    objectives: RecoveryObjectives | None = None,
    stop_conditions: tuple[str, ...] = (
        "primary_fence_unverified",
        "state_integrity_failed",
    ),
    rollback_ref: str = "runbook://control-plane-failover",
    max_affected_resources: int = 8,
    state: RecoveryState = RecoveryState.DRAFT,
    recovery_epoch: int = 0,
) -> RecoveryPlan:
    return RecoveryPlan(
        plan_id="control-plane-regional-recovery",
        revision=revision,
        mode=RecoveryMode.DRILL,
        profile=RecoveryProfile.RESTORE,
        primary_region=primary_region,
        recovery_region=recovery_region,
        requester_ref="group:operations-requesters",
        scope=scope,
        objectives=objectives
        or RecoveryObjectives(
            rpo_seconds=3600.0,
            rto_seconds=7200.0,
            max_degraded_seconds=10800.0,
        ),
        stop_conditions=stop_conditions,
        rollback_ref=rollback_ref,
        max_affected_resources=max_affected_resources,
        state=state,
        recovery_epoch=recovery_epoch,
    )


def _transition(
    machine: RecoveryPlanStateMachine,
    plan: RecoveryPlan,
    target: RecoveryState,
    *,
    at: datetime = _AT,
) -> RecoveryPlan:
    approval_ref = (
        "approval://recovery/1"
        if target in {RecoveryState.APPROVED, RecoveryState.FAILBACK_READY}
        else None
    )
    if target is RecoveryState.ACTIVATING:
        epoch = 1
    elif target is RecoveryState.FAILING_BACK:
        epoch = 2
    elif plan.recovery_epoch > 0:
        epoch = plan.recovery_epoch
    else:
        epoch = None
    updated, _ = machine.transition(
        plan,
        target=target,
        actor_ref="group:reliability-approvers",
        at=at,
        evidence_refs=_EVIDENCE,
        approval_ref=approval_ref,
        recovery_epoch=epoch,
    )
    return updated


def test_full_failover_and_failback_sequence_is_accepted() -> None:
    machine = RecoveryPlanStateMachine()
    plan = _plan()
    expected = [
        RecoveryState.READY,
        RecoveryState.APPROVED,
        RecoveryState.ACTIVATING,
        RecoveryState.PRIMARY_FENCED,
        RecoveryState.STATE_RESTORED,
        RecoveryState.RUNTIME_STARTED,
        RecoveryState.AUDIT_VERIFIED,
        RecoveryState.EVENT_RECOVERY_READY,
        RecoveryState.TRAFFIC_SHIFTED,
        RecoveryState.SERVICE_VERIFIED,
        RecoveryState.ACTIVE_RECOVERY,
        RecoveryState.FAILBACK_READY,
        RecoveryState.FAILING_BACK,
        RecoveryState.PRIMARY_VERIFIED,
        RecoveryState.CLOSED,
    ]

    for offset, target in enumerate(expected):
        plan = _transition(machine, plan, target, at=_AT + timedelta(seconds=offset))

    assert plan.state is RecoveryState.CLOSED
    assert plan.recovery_epoch == 2


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RecoveryState.DRAFT, RecoveryState.APPROVED),
        (RecoveryState.READY, RecoveryState.ACTIVATING),
        (RecoveryState.APPROVED, RecoveryState.PRIMARY_FENCED),
        (RecoveryState.PRIMARY_FENCED, RecoveryState.RUNTIME_STARTED),
        (RecoveryState.STATE_RESTORED, RecoveryState.TRAFFIC_SHIFTED),
        (RecoveryState.ACTIVE_RECOVERY, RecoveryState.FAILING_BACK),
        (RecoveryState.CLOSED, RecoveryState.READY),
        (RecoveryState.HALTED, RecoveryState.READY),
        (RecoveryState.READY, RecoveryState.READY),
    ],
)
def test_state_machine_rejects_skips_regressions_and_terminal_edges(
    current: RecoveryState,
    target: RecoveryState,
) -> None:
    epoch = (
        1
        if current not in {RecoveryState.DRAFT, RecoveryState.READY, RecoveryState.APPROVED}
        else 0
    )
    plan = _plan(state=current, recovery_epoch=epoch)
    with pytest.raises(RecoveryPlanError, match="illegal recovery transition"):
        RecoveryPlanStateMachine().transition(
            plan,
            target=target,
            actor_ref="group:reliability-approvers",
            at=_AT,
            evidence_refs=_EVIDENCE,
            recovery_epoch=epoch or None,
        )


def test_every_active_state_can_halt_and_halted_is_terminal() -> None:
    machine = RecoveryPlanStateMachine()
    haltable = [
        state
        for state, targets in LEGAL_RECOVERY_TRANSITIONS.items()
        if RecoveryState.HALTED in targets
    ]
    assert haltable
    for state in haltable:
        plan = _plan(state=state, recovery_epoch=4)
        halted, transition = machine.transition(
            plan,
            target=RecoveryState.HALTED,
            actor_ref="group:operations",
            at=_AT,
            evidence_refs=("evidence://stop-condition/fired",),
            recovery_epoch=4,
        )
        assert halted.state is RecoveryState.HALTED
        assert transition.recovery_epoch == 4
        assert not LEGAL_RECOVERY_TRANSITIONS[halted.state]


def test_requester_cannot_self_approve() -> None:
    plan = _plan(state=RecoveryState.READY)
    with pytest.raises(RecoveryPlanError, match="MUST NOT approve"):
        RecoveryPlanStateMachine().transition(
            plan,
            target=RecoveryState.APPROVED,
            actor_ref=plan.requester_ref,
            at=_AT,
            evidence_refs=_EVIDENCE,
            approval_ref="approval://recovery/1",
        )


def test_requester_case_variant_cannot_self_approve() -> None:
    plan = _plan()
    plan = RecoveryPlan(
        plan_id=plan.plan_id,
        revision=plan.revision,
        mode=plan.mode,
        profile=plan.profile,
        primary_region=plan.primary_region,
        recovery_region=plan.recovery_region,
        requester_ref="GROUP:Operations-Requesters",
        scope=plan.scope,
        objectives=plan.objectives,
        stop_conditions=plan.stop_conditions,
        rollback_ref=plan.rollback_ref,
        max_affected_resources=plan.max_affected_resources,
        state=RecoveryState.READY,
    )
    with pytest.raises(RecoveryPlanError, match="MUST NOT approve"):
        RecoveryPlanStateMachine().transition(
            plan,
            target=RecoveryState.APPROVED,
            actor_ref="group:operations-requesters",
            at=_AT,
            evidence_refs=_EVIDENCE,
            approval_ref="approval://recovery/1",
        )


def test_approval_reference_is_required_only_on_approval() -> None:
    machine = RecoveryPlanStateMachine()
    with pytest.raises(RecoveryPlanError, match="requires approval_ref"):
        machine.transition(
            _plan(state=RecoveryState.READY),
            target=RecoveryState.APPROVED,
            actor_ref="group:reliability-approvers",
            at=_AT,
            evidence_refs=_EVIDENCE,
        )
    with pytest.raises(RecoveryPlanError, match="valid only"):
        machine.transition(
            _plan(),
            target=RecoveryState.READY,
            actor_ref="group:operations",
            at=_AT,
            evidence_refs=_EVIDENCE,
            approval_ref="approval://unexpected",
        )


def test_failback_requires_separate_approval_and_new_epoch() -> None:
    machine = RecoveryPlanStateMachine()
    active = _plan(state=RecoveryState.ACTIVE_RECOVERY, recovery_epoch=3)
    with pytest.raises(RecoveryPlanError, match="requires approval_ref"):
        machine.transition(
            active,
            target=RecoveryState.FAILBACK_READY,
            actor_ref="group:reliability-approvers",
            at=_AT,
            evidence_refs=_EVIDENCE,
            recovery_epoch=3,
        )
    failback_ready, _ = machine.transition(
        active,
        target=RecoveryState.FAILBACK_READY,
        actor_ref="group:reliability-approvers",
        at=_AT,
        evidence_refs=_EVIDENCE,
        approval_ref="approval://failback/1",
        recovery_epoch=3,
    )
    with pytest.raises(RecoveryPlanError, match="monotonically increasing"):
        machine.transition(
            failback_ready,
            target=RecoveryState.FAILING_BACK,
            actor_ref="group:operations",
            at=_AT,
            evidence_refs=_EVIDENCE,
            recovery_epoch=3,
        )


def test_activation_requires_new_epoch_and_later_steps_require_exact_epoch() -> None:
    machine = RecoveryPlanStateMachine()
    approved = _plan(state=RecoveryState.APPROVED)
    with pytest.raises(RecoveryPlanError, match="monotonically increasing"):
        machine.transition(
            approved,
            target=RecoveryState.ACTIVATING,
            actor_ref="group:operations",
            at=_AT,
            evidence_refs=_EVIDENCE,
        )
    activating, _ = machine.transition(
        approved,
        target=RecoveryState.ACTIVATING,
        actor_ref="group:operations",
        at=_AT,
        evidence_refs=_EVIDENCE,
        recovery_epoch=7,
    )
    with pytest.raises(RecoveryPlanError, match="match the active epoch"):
        machine.transition(
            activating,
            target=RecoveryState.PRIMARY_FENCED,
            actor_ref="group:operations",
            at=_AT,
            evidence_refs=_EVIDENCE,
            recovery_epoch=6,
        )


def test_transition_requires_timezone_and_bounded_unique_evidence() -> None:
    machine = RecoveryPlanStateMachine()
    with pytest.raises(RecoveryPlanError, match="timezone-aware"):
        machine.transition(
            _plan(),
            target=RecoveryState.READY,
            actor_ref="group:operations",
            at=datetime(2026, 7, 31),
            evidence_refs=_EVIDENCE,
        )
    for evidence in ((), ("evidence://same", "evidence://same")):
        with pytest.raises(RecoveryPlanError):
            machine.transition(
                _plan(),
                target=RecoveryState.READY,
                actor_ref="group:operations",
                at=_AT,
                evidence_refs=evidence,
            )


@pytest.mark.parametrize(
    "objectives",
    [
        RecoveryObjectives(rpo_seconds=0, rto_seconds=1, max_degraded_seconds=1),
        RecoveryObjectives(rpo_seconds=1, rto_seconds=2, max_degraded_seconds=2),
    ],
)
def test_valid_objectives_are_accepted(objectives: RecoveryObjectives) -> None:
    assert _plan(objectives=objectives).objectives == objectives


@pytest.mark.parametrize(
    "values",
    [
        {"rpo_seconds": float("nan"), "rto_seconds": 1, "max_degraded_seconds": 1},
        {"rpo_seconds": -1, "rto_seconds": 1, "max_degraded_seconds": 1},
        {"rpo_seconds": 0, "rto_seconds": float("inf"), "max_degraded_seconds": 1},
        {"rpo_seconds": 0, "rto_seconds": 2, "max_degraded_seconds": 1},
        {"rpo_seconds": False, "rto_seconds": 1, "max_degraded_seconds": 1},
    ],
)
def test_invalid_objectives_fail_closed(values: dict[str, float]) -> None:
    with pytest.raises(RecoveryPlanError):
        RecoveryObjectives(**values)


@pytest.mark.parametrize(
    "build",
    [
        lambda: _plan(primary_region="same", recovery_region="same"),
        lambda: _plan(revision=0),
        lambda: _plan(scope=()),
        lambda: _plan(scope=("control-plane", "control-plane")),
        lambda: _plan(scope=("a", "b"), max_affected_resources=1),
        lambda: _plan(stop_conditions=()),
        lambda: _plan(rollback_ref=""),
        lambda: _plan(state=RecoveryState.ACTIVATING, recovery_epoch=0),
        lambda: _plan(state=RecoveryState.READY, recovery_epoch=1),
    ],
)
def test_invalid_plan_shape_fails_closed(build: Callable[[], RecoveryPlan]) -> None:
    with pytest.raises(RecoveryPlanError):
        build()


def test_transition_is_immutable_and_idempotency_key_is_stable() -> None:
    plan = _plan()
    updated, first = RecoveryPlanStateMachine().transition(
        plan,
        target=RecoveryState.READY,
        actor_ref="group:operations",
        at=_AT,
        evidence_refs=_EVIDENCE,
    )
    _, redelivery = RecoveryPlanStateMachine().transition(
        plan,
        target=RecoveryState.READY,
        actor_ref="group:operations",
        at=_AT,
        evidence_refs=_EVIDENCE,
    )
    assert plan.state is RecoveryState.DRAFT
    assert updated.state is RecoveryState.READY
    assert first.idempotency_key == redelivery.idempotency_key
    with pytest.raises(FrozenInstanceError):
        updated.state = RecoveryState.CLOSED  # type: ignore[misc]


def test_idempotency_key_canonicalizes_equivalent_timezone_offsets() -> None:
    machine = RecoveryPlanStateMachine()
    plan = _plan()
    _, utc_transition = machine.transition(
        plan,
        target=RecoveryState.READY,
        actor_ref="group:operations",
        at=datetime(2026, 7, 31, 12, tzinfo=UTC),
        evidence_refs=_EVIDENCE,
    )
    _, offset_transition = machine.transition(
        plan,
        target=RecoveryState.READY,
        actor_ref="group:operations",
        at=datetime(2026, 7, 31, 21, tzinfo=timezone(timedelta(hours=9))),
        evidence_refs=_EVIDENCE,
    )
    assert utc_transition.idempotency_key == offset_transition.idempotency_key


@pytest.mark.parametrize(
    ("plan_id", "actor_ref"),
    [
        ("plan::ambiguous", "group:operations"),
        ("plan", "group::operations"),
    ],
)
def test_idempotency_fields_reject_reserved_separator(
    plan_id: str,
    actor_ref: str,
) -> None:
    if "::" in plan_id:
        with pytest.raises(RecoveryPlanError, match="reserved"):
            RecoveryPlan(
                plan_id=plan_id,
                revision=1,
                mode=RecoveryMode.DRILL,
                profile=RecoveryProfile.RESTORE,
                primary_region="primary-region",
                recovery_region="recovery-region",
                requester_ref="group:requesters",
                scope=("control-plane",),
                objectives=RecoveryObjectives(0, 1, 1),
                stop_conditions=("fence_failed",),
                rollback_ref="runbook://recovery",
                max_affected_resources=1,
            )
    else:
        with pytest.raises(RecoveryPlanError, match="reserved"):
            RecoveryPlanStateMachine().transition(
                _plan(),
                target=RecoveryState.READY,
                actor_ref=actor_ref,
                at=_AT,
                evidence_refs=_EVIDENCE,
            )


@pytest.mark.parametrize(
    "transition",
    [
        RecoveryTransition(
            plan_id="plan",
            revision=1,
            from_state=RecoveryState.DRAFT,
            to_state=RecoveryState.READY,
            actor_ref="group:operations",
            at=_AT,
            evidence_refs=_EVIDENCE,
            recovery_epoch=0,
        ),
    ],
)
def test_direct_valid_transition_is_accepted(transition: RecoveryTransition) -> None:
    assert transition.to_state is RecoveryState.READY


def test_direct_transition_construction_rejects_invalid_record() -> None:
    with pytest.raises(RecoveryPlanError, match="illegal recovery edge"):
        RecoveryTransition(
            plan_id="plan",
            revision=1,
            from_state=RecoveryState.DRAFT,
            to_state=RecoveryState.TRAFFIC_SHIFTED,
            actor_ref="group:operations",
            at=_AT,
            evidence_refs=_EVIDENCE,
            recovery_epoch=1,
        )
    with pytest.raises(RecoveryPlanError, match="timezone-aware"):
        RecoveryTransition(
            plan_id="plan",
            revision=1,
            from_state=RecoveryState.DRAFT,
            to_state=RecoveryState.READY,
            actor_ref="group:operations",
            at=datetime(2026, 7, 31),
            evidence_refs=_EVIDENCE,
            recovery_epoch=0,
        )


def test_recovery_epoch_is_bounded_to_signed_64_bit() -> None:
    with pytest.raises(RecoveryPlanError, match="recovery_epoch"):
        _plan(state=RecoveryState.ACTIVATING, recovery_epoch=2**63)


def test_transition_mapping_is_read_only() -> None:
    with pytest.raises(TypeError):
        LEGAL_RECOVERY_TRANSITIONS[RecoveryState.DRAFT] = frozenset()  # type: ignore[index]
