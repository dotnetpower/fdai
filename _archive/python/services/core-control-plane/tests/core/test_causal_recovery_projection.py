from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.impact_analysis import (
    AffectedSet,
    ImpactEnvelopeProjector,
    ObjectiveBound,
    TelemetryRequirements,
    compile_impact_envelope,
)
from fdai.core.rca.hypothesis import (
    CausalEvidenceAssessment,
    build_causal_hypothesis,
)
from fdai.core.rca.projection import CausalHypothesisProjector, CausalProjectionConflictError
from fdai.core.recovery import (
    RecoveryAction,
    RecoveryPlanProjector,
    RecoveryStrategy,
    compile_recovery_plan,
)
from fdai.shared.contracts.models import CausalEvidenceGrade
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord

_NOW = datetime(2026, 7, 31, tzinfo=UTC)
_ProjectionCall = tuple[tuple[OntologyObjectRecord, ...], tuple[OntologyLinkRecord, ...]]


class _Store:
    def __init__(self) -> None:
        self.existing: OntologyObjectRecord | None = None
        self.calls: list[_ProjectionCall] = []

    async def get_object(self, _object_id: str) -> OntologyObjectRecord | None:
        return self.existing

    async def replace_subgraph(
        self,
        *,
        objects: tuple[OntologyObjectRecord, ...],
        links: tuple[OntologyLinkRecord, ...],
        **_kwargs: object,
    ) -> None:
        self.calls.append((objects, links))


def _hypothesis():  # type: ignore[no-untyped-def]
    return build_causal_hypothesis(
        incident_id="incident-1",
        cause_ref="change-1",
        effect_ref="finding-1",
        mechanism="deployment_error",
        graph_revision="graph-1",
        evidence_cutoff=_NOW,
        method_version="causal-v1",
        evidence_grade=CausalEvidenceGrade.PREDICTIVE_PRECEDENCE,
        assessment=CausalEvidenceAssessment(
            temporal_precedence=1.0,
            topological_reachability=1.0,
            mechanism_fit=1.0,
            intervention_consistency=0.5,
            evidence_completeness=1.0,
            supporting_refs=("evidence-1",),
        ),
        created_at=_NOW,
    )


async def test_causal_projection_writes_object_and_all_evidence_links_atomically() -> None:
    store = _Store()
    hypothesis = _hypothesis()
    await CausalHypothesisProjector(store=store).project(
        hypothesis,
        finding_id="finding-1",
        change_ids=("change-1",),
        supporting_evidence_ids=("evidence-1",),
        refuting_evidence_ids=("evidence-2",),
        outcome_ids=("outcome-1",),
        previous_hypothesis_id="causal-prior",
    )
    objects, links = store.calls[0]
    assert objects == (hypothesis.to_ontology_object(),)
    assert {item.link_type for item in links} == {
        "hypothesis_explains_finding",
        "hypothesis_claims_change",
        "evidence_supports_hypothesis",
        "evidence_refutes_hypothesis",
        "outcome_tests_hypothesis",
        "hypothesis_precedes_hypothesis",
    }


async def test_causal_projection_rejects_same_id_with_different_content() -> None:
    store = _Store()
    hypothesis = _hypothesis()
    store.existing = OntologyObjectRecord(
        id=hypothesis.hypothesis_id,
        object_type="CausalHypothesis",
        properties={"id": hypothesis.hypothesis_id},
    )
    with pytest.raises(CausalProjectionConflictError, match="content changed"):
        await CausalHypothesisProjector(store=store).project(
            hypothesis,
            finding_id="finding-1",
        )


def _envelope():  # type: ignore[no-untyped-def]
    return compile_impact_envelope(
        decision_case_id="decision-1",
        affected_set=AffectedSet(
            direct_targets=("resource-1",),
            runtime_dependents=(),
            protected_services=("service-1",),
            protected_objectives=("slo-1",),
            control_dependencies=(),
            graph_revision="graph-1",
        ),
        action_type_cap=1,
        decision_cap=1,
        max_dependency_depth=2,
        max_duration_seconds=60,
        objective_bounds=(ObjectiveBound("availability", lower=99.0),),
        required_signals=("pod_restart",),
        forbidden_signals=("security_event",),
        telemetry_requirements=TelemetryRequirements(("metrics",), 60, 10),
        uncertainty=0.1,
        expires_at=_NOW + timedelta(hours=1),
    )


async def test_impact_and_recovery_projection_link_runtime_objects() -> None:
    impact_store = _Store()
    envelope = _envelope()
    await ImpactEnvelopeProjector(store=impact_store).project(
        envelope,
        experiment_ids=("experiment-1",),
        action_option_ids=("option-1",),
    )
    assert {item.link_type for item in impact_store.calls[0][1]} == {
        "envelope_bounds_experiment",
        "envelope_bounds_action_option",
        "envelope_protects_objective",
    }

    action = RecoveryAction(
        action_id="restore",
        action_type_ref="ops.restore-service",
        action_type_version="1.0.0",
        target_ref="resource-1",
        compensation_action_type_ref="ops.undo-restore",
        stop_conditions=("time_box",),
        rollback_ref="rollback:restore",
    )
    plan = compile_recovery_plan(
        strategy=RecoveryStrategy.STATE_FORWARD,
        workflow_ref="recover-service",
        workflow_version="1.0.0",
        catalog_digest="catalog-1",
        actions=(action,),
        impact_envelope_id=envelope.envelope_id,
        recovery_objective_ref="rto-1",
        verification_probes=("health",),
        direct_target_ids=("resource-1",),
        graph_revision="graph-1",
        dry_run_receipt="dry-run-1",
        last_rehearsed_at=_NOW,
        expires_at=_NOW + timedelta(hours=1),
    )
    recovery_store = _Store()
    await RecoveryPlanProjector(store=recovery_store).project(
        plan,
        hypothesis_id="causal-1",
        process_id="process-1",
    )
    assert {item.link_type for item in recovery_store.calls[0][1]} == {
        "recovery_addresses_hypothesis",
        "recovery_targets_resource",
        "recovery_realized_as_process",
    }
