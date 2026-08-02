from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from fdai.core.decision_case import ActionOption, ObjectiveEffect
from fdai.core.operational_context import OperationalContextSnapshot
from fdai.core.operational_planning import (
    MAX_PLAN_EFFECTS,
    ConstraintEvaluation,
    ConstraintStatus,
    SimulationReceipt,
    SimulationStatus,
    SpecialistPlanningCoordinator,
)
from fdai.shared.contracts.models import Autonomy

NOW = datetime(2026, 8, 3, tzinfo=UTC)


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


class _PassedConstraints:
    async def evaluate(
        self, *, context: OperationalContextSnapshot, option: ActionOption
    ) -> tuple[ConstraintEvaluation, ...]:
        return (
            ConstraintEvaluation(
                "slo",
                ConstraintStatus.PASSED,
                3,
                "verified",
                (f"context:{context.snapshot_id}", *option.evidence_refs),
            ),
        )


class _Simulator:
    def __init__(self) -> None:
        self.calls = 0

    async def simulate(
        self,
        *,
        context: OperationalContextSnapshot,
        candidate_id: str,
        action_type: str | None,
        effects: tuple[ObjectiveEffect, ...],
        observed_at: datetime,
    ) -> SimulationReceipt:
        self.calls += 1
        return SimulationReceipt(
            receipt_id=f"simulation:{candidate_id}",
            candidate_id=candidate_id,
            snapshot_id=context.snapshot_id,
            logic_invocation_id="logic-invocation:" + "b" * 64,
            status=SimulationStatus.SUCCEEDED,
            started_at=observed_at,
            completed_at=observed_at,
            evidence_refs=(f"simulation:{action_type}", f"effects:{len(effects)}"),
        )


async def test_specialist_planning_enriches_existing_decision_case() -> None:
    coordinator = SpecialistPlanningCoordinator(
        logic_release_digest="sha256:" + "c" * 64,
        constraint_evaluator=_PassedConstraints(),
        simulator=_Simulator(),
    )

    projection = await coordinator.build(
        correlation_id="correlation-example",
        context=_context(),
        advice={"cost": "scale_down", "capacity": "scale_up"},
        impacts={"cost": 0.2, "capacity": 0.9},
        created_at=NOW,
    )

    assert projection is not None
    assert projection.selection.selected_option_id == "capacity:scale_up"
    mapping = projection.to_mapping()
    assert mapping["logic_release_digest"] == "sha256:" + "c" * 64
    assert mapping["operational_plan"]["complete"] is True
    options = mapping["options"]
    assert {tuple(option["proposing_agents"]) for option in options} == {("Njord",), ("Freyr",)}
    assert all(option["simulation_receipt_refs"] for option in options)


async def test_oversized_objective_set_is_rejected_before_simulation() -> None:
    simulator = _Simulator()
    coordinator = SpecialistPlanningCoordinator(
        logic_release_digest="sha256:" + "c" * 64,
        constraint_evaluator=_PassedConstraints(),
        simulator=simulator,
    )
    objectives = tuple(f"objective-{index}" for index in range(MAX_PLAN_EFFECTS + 1))

    with pytest.raises(ValueError, match="objective count exceeds"):
        await coordinator.build(
            correlation_id="correlation-example",
            context=replace(
                _context(),
                objective_ids=objectives,
                service_objective_ids=objectives,
                cost_objective_ids=(),
            ),
            advice={"capacity": "scale_up"},
            impacts={"capacity": 0.9},
            created_at=NOW,
        )

    assert simulator.calls == 0
