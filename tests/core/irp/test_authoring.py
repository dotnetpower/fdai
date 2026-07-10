"""Tests for IRP authoring (readiness gate + pretest)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.irp import (
    HistoricalIncident,
    PlanNotReadyError,
    PlanRequirement,
    PlanStatus,
    RequirementKind,
    ResponsePlan,
    ResponseStep,
    activate,
    evaluate_readiness,
    pretest_plan,
)

_NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)

_ALL_KINDS = (
    RequirementKind.STOP_CONDITION,
    RequirementKind.ROLLBACK_DEFINED,
    RequirementKind.BLAST_RADIUS_BOUNDED,
    RequirementKind.APPROVER_ASSIGNED,
    RequirementKind.NOTIFY_CHANNEL,
)


def _plan(*, satisfied: bool, trigger: str = "rate_limit") -> ResponsePlan:
    return ResponsePlan(
        plan_id="plan-1",
        name="AOAI 429 response",
        trigger_signal=trigger,
        steps=(
            ResponseStep(
                step_id="s1",
                action_ref="aoai.increase_tpm_quota",
                description="Raise TPM quota",
            ),
        ),
        requirements=tuple(
            PlanRequirement(kind=kind, description=kind.value, satisfied=satisfied)
            for kind in _ALL_KINDS
        ),
        approver_role="approver",
        notify_channels=("teams://sre",),
        created_by="op@example.com",
        created_at=_NOW,
    )


def test_readiness_lists_unmet_requirements() -> None:
    report = evaluate_readiness(_plan(satisfied=False))
    assert report.blocked is True
    assert set(report.unmet) == set(_ALL_KINDS)


def test_activate_blocked_when_requirements_unmet() -> None:
    with pytest.raises(PlanNotReadyError):
        activate(_plan(satisfied=False))


def test_activate_succeeds_when_all_requirements_met() -> None:
    activated = activate(_plan(satisfied=True))
    assert activated.status is PlanStatus.ACTIVE


def _plan_with_requirements(requirements: tuple[PlanRequirement, ...]) -> ResponsePlan:
    return ResponsePlan(
        plan_id="plan-2",
        name="partial plan",
        trigger_signal="rate_limit",
        steps=(ResponseStep(step_id="s1", action_ref="a", description="d"),),
        requirements=requirements,
        approver_role="approver",
        notify_channels=("teams://sre",),
        created_by="op@example.com",
        created_at=_NOW,
    )


def test_activate_refuses_plan_with_no_requirements() -> None:
    # H10: omitting requirements entirely MUST NOT bypass the safety gate.
    plan = _plan_with_requirements(())
    report = evaluate_readiness(plan)
    assert report.blocked is True
    assert set(report.unmet) == set(_ALL_KINDS)  # all five mandated, none satisfied
    with pytest.raises(PlanNotReadyError):
        activate(plan)


def test_activate_refuses_plan_missing_one_mandatory_requirement() -> None:
    # Four satisfied, NOTIFY_CHANNEL omitted -> still blocked.
    present = tuple(
        PlanRequirement(kind=kind, description=kind.value, satisfied=True)
        for kind in _ALL_KINDS
        if kind is not RequirementKind.NOTIFY_CHANNEL
    )
    plan = _plan_with_requirements(present)
    report = evaluate_readiness(plan)
    assert report.blocked is True
    assert report.unmet == (RequirementKind.NOTIFY_CHANNEL,)
    with pytest.raises(PlanNotReadyError):
        activate(plan)


def test_activate_refuses_when_a_requirement_is_present_but_unsatisfied() -> None:
    present = tuple(
        PlanRequirement(
            kind=kind,
            description=kind.value,
            satisfied=(kind is not RequirementKind.ROLLBACK_DEFINED),
        )
        for kind in _ALL_KINDS
    )
    plan = _plan_with_requirements(present)
    report = evaluate_readiness(plan)
    assert report.unmet == (RequirementKind.ROLLBACK_DEFINED,)
    with pytest.raises(PlanNotReadyError):
        activate(plan)


def test_pretest_matches_incident_resolved_by_plan_action() -> None:
    plan = _plan(satisfied=True)
    incidents = (
        HistoricalIncident(
            incident_ref="inc-1",
            signals=("rate_limit",),
            resolved_by_action="aoai.increase_tpm_quota",
        ),
        HistoricalIncident(
            incident_ref="inc-2",
            signals=("rate_limit",),
            resolved_by_action="something_else",
        ),
        HistoricalIncident(
            incident_ref="inc-3",
            signals=("db_cpu",),  # does not trigger this plan
            resolved_by_action="aoai.increase_tpm_quota",
        ),
    )

    report = pretest_plan(plan, incidents)

    assert report.total == 2  # only rate_limit incidents count
    assert report.matched == 1
    assert report.unmatched_incident_refs == ("inc-2",)
    assert report.coverage == pytest.approx(0.5)


def test_pretest_zero_triggering_incidents_is_zero_coverage() -> None:
    report = pretest_plan(
        _plan(satisfied=True),
        (HistoricalIncident(incident_ref="i", signals=("db_cpu",)),),
    )
    assert report.total == 0
    assert report.coverage == 0.0
