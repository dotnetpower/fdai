"""Graph-wide Dynamic effect propagation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.assurance_twin import (
    CausalEvidenceGrade,
    DynamicInvariant,
    EffectInteractionTerm,
    EffectModelStatus,
    GraphEffectModel,
    GraphIntervention,
    GraphTopologyEdge,
    InvariantOperator,
    InvariantStatus,
    OperationalStateTrajectory,
    StateSlice,
    TrajectoryKind,
    simulate_graph_effects,
)

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


def _baseline() -> OperationalStateTrajectory:
    return OperationalStateTrajectory(
        kind=TrajectoryKind.OBSERVED,
        ontology_release="sha256:" + "a" * 64,
        graph_revision="graph-1",
        inventory_generation="inventory-1",
        base_snapshot_id="snapshot-1",
        evidence_cutoff=_NOW,
        horizon_end=_NOW + timedelta(minutes=5),
        slices=(
            StateSlice(
                "resource:api",
                "Resource",
                "replicas",
                2.0,
                _NOW,
                evidence_refs=("inventory:api",),
                independent_observer=True,
            ),
            StateSlice(
                "service:checkout",
                "BusinessService",
                "latency_p99_ms",
                50.0,
                _NOW,
                evidence_refs=("metric:latency",),
                independent_observer=True,
            ),
        ),
        source_watermarks=("inventory:1", "metrics:1"),
    )


def _topology() -> tuple[GraphTopologyEdge, ...]:
    return (
        GraphTopologyEdge(
            "resource:api",
            "Resource",
            "supports",
            "workload:checkout",
            "Workload",
        ),
        GraphTopologyEdge(
            "workload:checkout",
            "Workload",
            "implements",
            "service:checkout",
            "BusinessService",
        ),
    )


def _model(
    *,
    status: EffectModelStatus = EffectModelStatus.ACTIVE,
    gain: float = 5.0,
    grade: CausalEvidenceGrade = CausalEvidenceGrade.QUASI_EXPERIMENTAL,
) -> GraphEffectModel:
    return GraphEffectModel(
        model_id="graph-effect.scale-latency",
        version="1.0.0",
        revision=1,
        status=status,
        trigger_ref="ops.scale-out",
        source_type="Resource",
        link_path=("supports", "implements"),
        target_type="BusinessService",
        target_metric="latency_p99_ms",
        propagation_lag_seconds=30,
        gain=gain,
        offset=0.0,
        interval_radius=2.0,
        evidence_grade=grade,
        causal_evidence_receipt_digest="b" * 64,
        learned_through=_NOW,
    )


def _intervention(
    intervention_id: str = "intervention:scale",
    trigger_ref: str = "ops.scale-out",
) -> GraphIntervention:
    return GraphIntervention(
        intervention_id,
        trigger_ref,
        "resource:api",
        "Resource",
        "replicas",
        2.0,
        _NOW,
    )


def _invariants(*, threshold: float = 100.0) -> tuple[DynamicInvariant, ...]:
    return (
        DynamicInvariant(
            invariant_id="slo.checkout.latency",
            metric="latency_p99_ms",
            operator=InvariantOperator.LESS_THAN_OR_EQUAL,
            threshold=threshold,
            target_ref="service:checkout",
        ),
    )


def test_graph_effect_propagates_over_exact_typed_path() -> None:
    result = simulate_graph_effects(
        baseline=_baseline(),
        topology=_topology(),
        interventions=(_intervention(),),
        active_models=(_model(),),
        invariants=_invariants(),
    )

    predicted = next(
        item
        for item in result.active_trajectory.slices
        if item.effective_at == _NOW + timedelta(seconds=30)
    )
    assert predicted.object_ref == "service:checkout"
    assert predicted.value == 60.0
    assert result.requires_review is False


def test_graph_simulation_is_order_stable() -> None:
    first = simulate_graph_effects(
        baseline=_baseline(),
        topology=_topology(),
        interventions=(_intervention(),),
        active_models=(_model(),),
        invariants=_invariants(),
    )
    second = simulate_graph_effects(
        baseline=_baseline(),
        topology=_topology(),
        interventions=(_intervention(),),
        active_models=(_model(),),
        invariants=_invariants(),
    )

    assert first.active_trajectory.digest == second.active_trajectory.digest


def test_challenger_divergence_requires_review_but_does_not_change_active() -> None:
    result = simulate_graph_effects(
        baseline=_baseline(),
        topology=_topology(),
        interventions=(_intervention(),),
        active_models=(_model(gain=5.0),),
        challenger_models=(_model(status=EffectModelStatus.CHALLENGER, gain=12.0),),
        invariants=_invariants(),
        divergence_threshold=5.0,
    )

    active_value = result.active_trajectory.slices[-1].value
    challenger_value = result.challenger_trajectory.slices[-1].value  # type: ignore[union-attr]
    assert active_value == 60.0
    assert challenger_value == 74.0
    assert result.max_divergence == 14.0
    assert "active_challenger_divergence" in result.reason_codes


def test_unmodeled_intervention_never_returns_complete_prediction() -> None:
    result = simulate_graph_effects(
        baseline=_baseline(),
        topology=_topology(),
        interventions=(_intervention(trigger_ref="ops.unknown"),),
        active_models=(_model(),),
        invariants=_invariants(),
    )

    assert result.requires_review is True
    assert result.active_trajectory.complete is False
    assert "unmodeled_intervention" in result.reason_codes


def test_low_causal_grade_requires_review() -> None:
    result = simulate_graph_effects(
        baseline=_baseline(),
        topology=_topology(),
        interventions=(_intervention(),),
        active_models=(_model(grade=CausalEvidenceGrade.PREDICTIVE_PRECEDENCE),),
        invariants=_invariants(),
    )

    assert result.requires_review is True
    assert "causal_evidence_below_quasi_experimental" in result.reason_codes


def test_interaction_term_is_applied_without_linear_assumption() -> None:
    second = _intervention("intervention:cache", "ops.warm-cache")
    cache_model = replace(_model(), trigger_ref="ops.warm-cache", gain=-2.0)
    result = simulate_graph_effects(
        baseline=_baseline(),
        topology=_topology(),
        interventions=(_intervention(), second),
        active_models=(_model(), cache_model),
        invariants=_invariants(),
        interaction_terms=(
            EffectInteractionTerm(
                "interaction:scale-cache",
                ("ops.scale-out", "ops.warm-cache"),
                "service:checkout",
                "latency_p99_ms",
                -3.0,
                30,
                "interaction-model@1.0.0",
                CausalEvidenceGrade.QUASI_EXPERIMENTAL,
            ),
        ),
    )

    predicted = next(
        item
        for item in result.active_trajectory.slices
        if item.effective_at == _NOW + timedelta(seconds=30)
    )
    assert predicted.value == 53.0


def test_interaction_requires_every_upstream_trigger_to_be_modeled() -> None:
    unknown = _intervention("intervention:unknown", "ops.unknown")
    result = simulate_graph_effects(
        baseline=_baseline(),
        topology=_topology(),
        interventions=(_intervention(), unknown),
        active_models=(_model(),),
        invariants=_invariants(),
        interaction_terms=(
            EffectInteractionTerm(
                "interaction:incomplete",
                ("ops.scale-out", "ops.unknown"),
                "service:checkout",
                "latency_p99_ms",
                -100.0,
                30,
                "interaction-model@1.0.0",
                CausalEvidenceGrade.QUASI_EXPERIMENTAL,
            ),
        ),
    )

    predicted = next(
        item
        for item in result.active_trajectory.slices
        if item.effective_at == _NOW + timedelta(seconds=30)
    )
    assert predicted.value == 60.0
    assert "interaction_incomplete_upstream" in result.reason_codes


def test_path_frontier_is_bounded_and_marks_trajectory_truncated() -> None:
    first_hop = tuple(
        GraphTopologyEdge("resource:api", "Resource", "hop-1", f"mid:{index}", "Mid")
        for index in range(50)
    )
    second_hop = tuple(
        GraphTopologyEdge(f"mid:{mid}", "Mid", "hop-2", f"target:{target}", "Target")
        for mid in range(50)
        for target in range(50)
    )
    third_hop = tuple(
        GraphTopologyEdge(f"target:{target}", "Target", "hop-3", f"leaf:{leaf}", "Leaf")
        for target in range(50)
        for leaf in range(2)
    )
    topology = tuple(sorted((*first_hop, *second_hop, *third_hop), key=lambda item: item.key))
    baseline_slices = [*_baseline().slices]
    baseline_slices.extend(
        StateSlice(
            f"leaf:{leaf}",
            "Leaf",
            "latency_p99_ms",
            10.0,
            _NOW,
            evidence_refs=(f"metric:leaf:{leaf}",),
            independent_observer=True,
        )
        for leaf in range(2)
    )
    baseline = replace(
        _baseline(), slices=tuple(sorted(baseline_slices, key=lambda item: item.key))
    )
    model = replace(
        _model(),
        link_path=("hop-1", "hop-2", "hop-3"),
        target_type="Leaf",
    )

    result = simulate_graph_effects(
        baseline=baseline,
        topology=topology,
        interventions=(_intervention(),),
        active_models=(model,),
        invariants=_invariants(),
    )

    assert result.requires_review is True
    assert result.active_trajectory.truncated is True
    assert "path_frontier_cap_exceeded" in result.reason_codes


def test_cycle_or_missing_path_fails_toward_review() -> None:
    cyclic = tuple(
        sorted(
            (
                *_topology(),
                GraphTopologyEdge(
                    "service:checkout",
                    "BusinessService",
                    "supports",
                    "resource:api",
                    "Resource",
                ),
            ),
            key=lambda item: item.key,
        )
    )
    cyclic_model = replace(
        _model(),
        link_path=("supports", "implements", "supports"),
        target_type="Resource",
        target_metric="replicas",
    )

    result = simulate_graph_effects(
        baseline=_baseline(),
        topology=cyclic,
        interventions=(_intervention(),),
        active_models=(cyclic_model,),
        invariants=_invariants(),
    )

    assert result.requires_review is True
    assert "dependency_cycle_detected" in result.reason_codes


def test_invariant_violation_requires_review_with_evaluated_result() -> None:
    result = simulate_graph_effects(
        baseline=_baseline(),
        topology=_topology(),
        interventions=(_intervention(),),
        active_models=(_model(),),
        invariants=_invariants(threshold=55.0),
    )

    assert result.requires_review is True
    assert "dynamic_invariant_violated" in result.reason_codes
    assert result.invariant_results[0].status is InvariantStatus.VIOLATED


def test_unscorable_invariant_requires_review_with_exact_reason() -> None:
    result = simulate_graph_effects(
        baseline=_baseline(),
        topology=_topology(),
        interventions=(_intervention(),),
        active_models=(_model(),),
        invariants=(
            DynamicInvariant(
                invariant_id="capacity.unavailable",
                metric="available_capacity",
                operator=InvariantOperator.GREATER_THAN_OR_EQUAL,
                threshold=1.0,
            ),
        ),
    )

    assert result.requires_review is True
    assert "dynamic_invariant_unscorable" in result.reason_codes
    assert result.invariant_results[0].status is InvariantStatus.UNSCORABLE
    assert result.invariant_results[0].reason == "matching_state_unavailable"


def test_graph_simulation_rejects_future_model_and_unsorted_topology() -> None:
    with pytest.raises(ValueError, match="deterministic order"):
        simulate_graph_effects(
            baseline=_baseline(),
            topology=tuple(reversed(_topology())),
            interventions=(_intervention(),),
            active_models=(_model(),),
            invariants=_invariants(),
        )
    with pytest.raises(ValueError, match="crosses the baseline evidence cutoff"):
        simulate_graph_effects(
            baseline=_baseline(),
            topology=_topology(),
            interventions=(_intervention(),),
            active_models=(replace(_model(), learned_through=_NOW + timedelta(seconds=1)),),
            invariants=_invariants(),
        )


def test_graph_model_identity_rejects_control_characters() -> None:
    with pytest.raises(ValueError, match="bounded and non-empty"):
        replace(_model(), trigger_ref="ops.scale-out\x00other")
