from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.impact_analysis import (
    AffectedSet,
    ImpactAnalyzer,
    ObjectiveBound,
    TelemetryRequirements,
    compile_impact_envelope,
)
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)

_NOW = datetime(2026, 7, 31, tzinfo=UTC)


class _Store:
    async def traverse(self, **_kwargs: object) -> OntologyGraphSnapshot:
        return OntologyGraphSnapshot(
            objects=(
                OntologyObjectRecord("resource-a", "Resource", {"id": "resource-a"}),
                OntologyObjectRecord("workload-a", "Workload", {"id": "workload-a"}),
                OntologyObjectRecord("service-a", "BusinessService", {"id": "service-a"}),
                OntologyObjectRecord("slo-a", "ServiceObjective", {"id": "slo-a"}),
                OntologyObjectRecord(
                    "audit-a",
                    "Resource",
                    {"id": "audit-a", "control_dependency": True},
                ),
            ),
            links=(
                OntologyLinkRecord("workload_runs_on", "workload-a", "resource-a"),
                OntologyLinkRecord("implemented_by", "service-a", "workload-a"),
                OntologyLinkRecord("service_has_service_objective", "service-a", "slo-a"),
            ),
        )


async def test_analyzer_classifies_affected_set() -> None:
    affected = await ImpactAnalyzer(store=_Store()).analyze(
        direct_target_ids=("resource-a",),
    )
    assert affected.direct_targets == ("resource-a",)
    assert affected.runtime_dependents == ("audit-a", "workload-a")
    assert affected.control_dependencies == ("audit-a",)
    assert affected.protected_services == ("service-a",)
    assert affected.protected_objectives == ("slo-a",)
    assert affected.complete


async def test_stale_graph_blocks_complete_affected_set() -> None:
    affected = await ImpactAnalyzer(store=_Store()).analyze(
        direct_target_ids=("resource-a",),
        graph_fresh=False,
    )
    assert affected.incomplete_reasons == ("graph_stale",)
    assert not affected.complete


def _complete_set() -> AffectedSet:
    return AffectedSet(
        direct_targets=("resource-a",),
        runtime_dependents=("workload-a",),
        protected_services=("service-a",),
        protected_objectives=("slo-a",),
        control_dependencies=(),
        graph_revision="graph-1",
    )


def _compile(affected: AffectedSet | None = None, **overrides: object):  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "decision_case_id": "decision-1",
        "affected_set": affected or _complete_set(),
        "action_type_cap": 10,
        "decision_cap": 2,
        "max_dependency_depth": 2,
        "max_duration_seconds": 60,
        "objective_bounds": (ObjectiveBound(metric="availability", lower=99.0),),
        "required_signals": ("pod_restart",),
        "forbidden_signals": ("security_event",),
        "telemetry_requirements": TelemetryRequirements(
            required_sources=("metrics",),
            freshness_seconds=60,
            cadence_seconds=10,
        ),
        "uncertainty": 0.1,
        "expires_at": _NOW,
    }
    values.update(overrides)
    return compile_impact_envelope(**values)  # type: ignore[arg-type]


def test_compiler_uses_tighter_cap_and_projects_ontology() -> None:
    envelope = _compile()
    assert envelope.max_affected_resources == 2
    assert envelope.affected_resource_ids == ("resource-a", "workload-a")
    assert envelope.to_ontology_object().object_type == "ImpactEnvelope"


def test_compiler_refuses_incomplete_or_over_cap_impact() -> None:
    with pytest.raises(ValueError, match="complete"):
        _compile(
            AffectedSet(
                direct_targets=("resource-a",),
                runtime_dependents=(),
                protected_services=(),
                protected_objectives=(),
                control_dependencies=(),
                graph_revision="graph-1",
                incomplete_reasons=("graph_stale",),
            )
        )
    with pytest.raises(ValueError, match="effective impact cap"):
        _compile(decision_cap=1)


def test_envelope_rejects_signal_that_is_required_and_forbidden() -> None:
    with pytest.raises(ValueError, match="both required and forbidden"):
        _compile(forbidden_signals=("pod_restart",))
