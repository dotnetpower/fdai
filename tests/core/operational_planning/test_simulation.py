from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fdai.core.decision_case import ObjectiveEffect
from fdai.core.operational_context import OperationalContextSnapshot
from fdai.core.operational_planning import PlanningProgram, ProgrammaticPlanningSimulator
from fdai.core.programmatic_pipeline.models import (
    ProgrammaticPipelineStats,
    ProgrammaticPipelineStatus,
    ProgrammaticToolPipelineResult,
)
from fdai.shared.contracts.models import (
    Autonomy,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
)
from fdai.shared.ontology.release import build_ontology_release

NOW = datetime(2026, 8, 3, tzinfo=UTC)


def _context() -> OperationalContextSnapshot:
    return OperationalContextSnapshot(
        snapshot_id="a" * 64,
        target_resource_id="resource-example",
        cutoff=NOW,
        recorded_at=NOW,
        catalog_versions=(("ontology", "1.0.0"),),
        service_ids=(),
        workload_ids=(),
        objective_ids=("reliability",),
        service_objective_ids=("reliability",),
        recovery_objective_ids=(),
        cost_objective_ids=(),
        constraint_ids=(),
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


def _program() -> PlanningProgram:
    source = "def main(): pass\n"
    declaration = OntologyFunctionType(
        name="simulate.capacity",
        version="1.0.0",
        kind=OntologyFunctionKind.DERIVE,
        artifact_digest="sha256:" + hashlib.sha256(source.encode()).hexdigest(),
        publisher="fdai",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    release = build_ontology_release(function_types=(declaration,))
    return PlanningProgram(
        function_ref=release.type_ref(OntologyDeclarationKind.FUNCTION, declaration.name),
        reviewed_source=source,
        source_digest=hashlib.sha256(source.encode()).hexdigest(),
        sandbox_profile_id="planning.capacity",
        allowed_read_tools=frozenset({"query_inventory"}),
    )


class _Runner:
    def __init__(self, result: ProgrammaticToolPipelineResult) -> None:
        self.result = result
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return self.result


def _result(
    status: ProgrammaticPipelineStatus,
    *,
    final_json: str | None,
) -> ProgrammaticToolPipelineResult:
    return ProgrammaticToolPipelineResult(
        run_id="placeholder",
        status=status,
        source_digest="b" * 64,
        stdout="",
        stderr="",
        final_json=final_json,
        receipt_refs=("pipeline-call:1",),
        stats=ProgrammaticPipelineStats(1, 1, 0, 10, 20, 5),
        complete=status is ProgrammaticPipelineStatus.SUCCEEDED,
    )


async def test_programmatic_simulator_returns_typed_effects_and_stable_identity() -> None:
    output = json.dumps(
        {
            "effects": [
                {
                    "objective_id": "reliability",
                    "utility": 0.8,
                    "confidence": 0.9,
                    "metric": "availability",
                    "expected_min": 0.99,
                    "expected_max": 1.0,
                    "observation_window_seconds": 300,
                }
            ],
            "requires_review": False,
            "reason_code": "within_bounds",
        }
    )
    runner = _Runner(_result(ProgrammaticPipelineStatus.SUCCEEDED, final_json=output))
    ticks = iter(
        (
            NOW,
            NOW + timedelta(seconds=1),
            NOW + timedelta(seconds=2),
            NOW + timedelta(seconds=3),
        )
    )
    simulator = ProgrammaticPlanningSimulator(
        runner=runner,
        program=_program(),
        clock=lambda: next(ticks),
    )
    values = dict(
        context=_context(),
        candidate_id="capacity:scale_up",
        action_type="ops.scale-out",
        effects=(ObjectiveEffect("reliability", 0.5, 0.8, "availability", 0.9, 1.0, 300),),
        observed_at=NOW,
    )

    first = await simulator.simulate(**values)
    replay = await simulator.simulate(**values)

    assert first.receipt_id == replay.receipt_id
    assert first.predicted_effects[0].utility == 0.8
    assert first.requires_review is False
    assert runner.requests[0].allowed_read_tools == frozenset({"query_inventory"})
    assert not hasattr(runner.requests[0], "credential_profile")


async def test_programmatic_simulator_holds_failed_or_malformed_output() -> None:
    failed = ProgrammaticPlanningSimulator(
        runner=_Runner(_result(ProgrammaticPipelineStatus.TIMED_OUT, final_json=None)),
        program=_program(),
        clock=lambda: NOW,
    )
    malformed = ProgrammaticPlanningSimulator(
        runner=_Runner(_result(ProgrammaticPipelineStatus.SUCCEEDED, final_json='{"effects": []}')),
        program=_program(),
        clock=lambda: NOW,
    )
    values = dict(
        context=_context(),
        candidate_id="capacity:scale_up",
        action_type="ops.scale-out",
        effects=(ObjectiveEffect("reliability", 0.5, 0.8, "availability", 0.9, 1.0, 300),),
        observed_at=NOW,
    )

    timed_out = await failed.simulate(**values)
    unscorable = await malformed.simulate(**values)

    assert timed_out.status.value == "timed_out"
    assert timed_out.requires_review is True
    assert unscorable.status.value == "unscorable"
    assert unscorable.predicted_effects == ()
