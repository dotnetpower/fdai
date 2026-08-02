from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.decision_case import ObjectiveEffect
from fdai.core.operational_context import OperationalContextSnapshot
from fdai.core.operational_planning import (
    CandidateDisposition,
    ConstraintEvaluation,
    ConstraintStatus,
    PlanCandidate,
    PlanningRequest,
    SimulationReceipt,
    SimulationStatus,
    SpecialistContribution,
    build_operational_plan,
)
from fdai.shared.contracts.models import Autonomy

NOW = datetime(2026, 8, 3, tzinfo=UTC)


def _effect(objective: str, utility: float) -> ObjectiveEffect:
    return ObjectiveEffect(objective, utility, 0.9, objective, 0.0, 1.0, 300)


def _context() -> OperationalContextSnapshot:
    return OperationalContextSnapshot(
        snapshot_id="a" * 64,
        target_resource_id="resource-example",
        cutoff=NOW,
        recorded_at=NOW,
        catalog_versions=(("ontology", "1.0.0"),),
        service_ids=("service-example",),
        workload_ids=("workload-example",),
        objective_ids=("reliability", "cost"),
        service_objective_ids=("reliability",),
        recovery_objective_ids=(),
        cost_objective_ids=("cost",),
        constraint_ids=("slo",),
        ownership_ids=(),
        dependency_ids=(),
        source_freshness=(),
        evidence_links=(),
        evidence_paths=(),
        temporal_exclusions=(),
        stale_sources=(),
        conflicts=(),
        autonomy_ceiling=Autonomy.ENFORCE_AUTO,
    )


def _candidate(
    candidate_id: str,
    reliability: float,
    cost: float,
    *,
    constraint_status: ConstraintStatus = ConstraintStatus.PASSED,
    simulation_status: SimulationStatus = SimulationStatus.SUCCEEDED,
    snapshot_id: str = "a" * 64,
) -> PlanCandidate:
    contribution = SpecialistContribution(
        agent="Freyr",
        domain="capacity",
        recommendation=candidate_id,
        observed_at=NOW,
        impact=0.8,
        evidence_refs=("forecast:capacity",),
        logic_receipt_refs=("logic-invocation:" + "b" * 64,),
    )
    constraint = ConstraintEvaluation(
        "slo",
        constraint_status,
        3,
        "slo_check",
        ("objective:slo",),
    )
    simulation = SimulationReceipt(
        receipt_id=f"simulation:{candidate_id}",
        candidate_id=candidate_id,
        snapshot_id=snapshot_id,
        logic_invocation_id="logic-invocation:" + "b" * 64,
        status=simulation_status,
        started_at=NOW,
        completed_at=NOW,
        evidence_refs=("twin:receipt",),
    )
    return PlanCandidate(
        candidate_id,
        "ops.scale-out",
        (_effect("reliability", reliability), _effect("cost", cost)),
        (contribution,),
        (constraint,),
        (simulation,),
        ("forecast:capacity", "twin:receipt"),
    )


def _request(candidates: tuple[PlanCandidate, ...]) -> PlanningRequest:
    return PlanningRequest(
        process_id="process-example",
        correlation_id="correlation-example",
        logic_release_digest="sha256:" + "c" * 64,
        context=_context(),
        no_action_effects=(_effect("reliability", -0.8), _effect("cost", 0.0)),
        protected_objective_ids=("reliability",),
        candidates=candidates,
        objective_weights=(("reliability", 1.0), ("cost", 0.7)),
        created_at=NOW,
    )


def test_hard_constraints_precede_pareto_and_weighted_selection() -> None:
    unsafe = _candidate("unsafe-cheap", -0.4, 1.0, constraint_status=ConstraintStatus.FAILED)
    dominated = _candidate("dominated", 0.5, -0.5)
    selected = _candidate("selected", 0.8, -0.2)

    plan = build_operational_plan(_request((unsafe, dominated, selected)))

    dispositions = {item.candidate_id: item.disposition for item in plan.assessments}
    assert plan.selection.selected_option_id == "selected"
    assert dispositions == {
        "unsafe-cheap": CandidateDisposition.INELIGIBLE,
        "dominated": CandidateDisposition.DOMINATED,
        "selected": CandidateDisposition.SELECTED,
    }
    assert plan.decision_case.process_id == "process-example"
    assert plan.decision_case.logic_release_digest == "sha256:" + "c" * 64


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (
            _candidate("unknown", 0.8, -0.2, constraint_status=ConstraintStatus.UNKNOWN),
            "constraint:slo:unknown",
        ),
        (
            _candidate("timeout", 0.8, -0.2, simulation_status=SimulationStatus.TIMED_OUT),
            "timed_out",
        ),
        (_candidate("stale", 0.8, -0.2, snapshot_id="d" * 64), "stale_snapshot"),
    ],
)
def test_incomplete_evidence_holds_without_selection(candidate: PlanCandidate, reason: str) -> None:
    plan = build_operational_plan(_request((candidate,)))

    assert plan.complete is False
    assert plan.selection.selected_option_id is None
    assert reason in plan.assessments[0].reasons[0]


def test_plan_and_decision_identity_cover_receipts() -> None:
    candidate = _candidate("selected", 0.8, -0.2)
    first = build_operational_plan(_request((candidate,)))
    changed = PlanCandidate(
        candidate.candidate_id,
        candidate.action_type,
        candidate.effects,
        candidate.contributions,
        candidate.constraints,
        candidate.simulations,
        (*candidate.evidence_refs, "simulation:new"),
    )
    revised = build_operational_plan(_request((changed,)))

    assert revised.plan_id != first.plan_id
    assert revised.decision_case.case_id != first.decision_case.case_id


def test_candidate_limit_fails_closed_instead_of_truncating() -> None:
    candidates = tuple(_candidate(f"candidate-{index}", 0.8, -0.2) for index in range(33))

    with pytest.raises(ValueError, match="hard limit"):
        _request(candidates)
