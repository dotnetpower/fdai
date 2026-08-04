"""Bounded graph-wide Dynamic effect propagation."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.core.assurance_twin.effect_model import CausalEvidenceGrade, EffectModelStatus
from fdai.core.assurance_twin.state_trajectory import (
    OperationalStateTrajectory,
    StateSlice,
    TrajectoryKind,
)

_DIGEST = re.compile(r"^(?:sha256:)?[a-f0-9]{64}$")
_MAX_EDGES = 4096
_MAX_MODELS = 256
_MAX_INTERVENTIONS = 32
_MAX_PATH_DEPTH = 5
_MAX_PATH_FRONTIER = 4096


@dataclass(frozen=True, slots=True)
class GraphTopologyEdge:
    source_ref: str
    source_type: str
    link_type: str
    target_ref: str
    target_type: str

    def __post_init__(self) -> None:
        for value in (
            self.source_ref,
            self.source_type,
            self.link_type,
            self.target_ref,
            self.target_type,
        ):
            _text(value, "graph topology edge")

    @property
    def key(self) -> tuple[str, str, str, str]:
        return self.source_ref, self.link_type, self.target_ref, self.target_type


@dataclass(frozen=True, slots=True)
class GraphIntervention:
    intervention_id: str
    trigger_ref: str
    source_ref: str
    source_type: str
    metric: str
    delta: float
    effective_at: datetime

    def __post_init__(self) -> None:
        for value in (
            self.intervention_id,
            self.trigger_ref,
            self.source_ref,
            self.source_type,
            self.metric,
        ):
            _text(value, "graph intervention")
        _aware(self.effective_at, "graph intervention effective_at")
        if not math.isfinite(self.delta):
            raise ValueError("graph intervention delta MUST be finite")


@dataclass(frozen=True, slots=True)
class GraphEffectModel:
    model_id: str
    version: str
    revision: int
    status: EffectModelStatus
    trigger_ref: str
    source_type: str
    link_path: tuple[str, ...]
    target_type: str
    target_metric: str
    propagation_lag_seconds: int
    gain: float
    offset: float
    interval_radius: float
    evidence_grade: CausalEvidenceGrade
    causal_evidence_receipt_digest: str
    learned_through: datetime
    sample_count: int = 0
    mean_absolute_error: float = 0.0
    applied_observation_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value in (
            self.model_id,
            self.version,
            self.trigger_ref,
            self.source_type,
            self.target_type,
            self.target_metric,
        ):
            _text(value, "graph effect model")
        if not 1 <= self.revision or self.sample_count < 0:
            raise ValueError("graph effect model revision and sample_count MUST be valid")
        if not self.link_path or len(self.link_path) > _MAX_PATH_DEPTH:
            raise ValueError(
                f"graph effect model link_path MUST contain 1..{_MAX_PATH_DEPTH} links"
            )
        for link_type in self.link_path:
            _text(link_type, "graph effect link type")
        if self.propagation_lag_seconds < 0:
            raise ValueError("graph effect propagation lag MUST be non-negative")
        if (
            any(
                not math.isfinite(value)
                for value in (
                    self.gain,
                    self.offset,
                    self.interval_radius,
                    self.mean_absolute_error,
                )
            )
            or self.interval_radius < 0.0
            or self.mean_absolute_error < 0.0
        ):
            raise ValueError("graph effect model numeric values MUST be finite and bounded")
        if _DIGEST.fullmatch(self.causal_evidence_receipt_digest) is None:
            raise ValueError("graph effect model causal receipt MUST be SHA-256")
        if (
            len(self.applied_observation_digests) > 64
            or len(self.applied_observation_digests) != len(set(self.applied_observation_digests))
            or any(_DIGEST.fullmatch(item) is None for item in self.applied_observation_digests)
        ):
            raise ValueError("graph effect applied observation digests MUST be unique and bounded")
        _aware(self.learned_through, "graph effect learned_through")

    @property
    def ref(self) -> str:
        return f"{self.model_id}@{self.version}:r{self.revision}"


@dataclass(frozen=True, slots=True)
class EffectInteractionTerm:
    interaction_id: str
    trigger_refs: tuple[str, ...]
    target_ref: str
    metric: str
    delta: float
    lag_seconds: int
    model_ref: str
    evidence_grade: CausalEvidenceGrade
    status: EffectModelStatus = EffectModelStatus.ACTIVE

    def __post_init__(self) -> None:
        _text(self.interaction_id, "interaction id")
        _text(self.target_ref, "interaction target")
        _text(self.metric, "interaction metric")
        _text(self.model_ref, "interaction model_ref")
        if len(self.trigger_refs) < 2 or self.trigger_refs != tuple(sorted(set(self.trigger_refs))):
            raise ValueError("interaction trigger_refs MUST contain two or more sorted unique refs")
        if not math.isfinite(self.delta) or self.lag_seconds < 0:
            raise ValueError("interaction delta and lag MUST be valid")


@dataclass(frozen=True, slots=True)
class GraphDynamicSimulationResult:
    active_trajectory: OperationalStateTrajectory
    challenger_trajectory: OperationalStateTrajectory | None
    requires_review: bool
    reason_codes: tuple[str, ...]
    max_divergence: float | None


def simulate_graph_effects(
    *,
    baseline: OperationalStateTrajectory,
    topology: tuple[GraphTopologyEdge, ...],
    interventions: tuple[GraphIntervention, ...],
    active_models: tuple[GraphEffectModel, ...],
    challenger_models: tuple[GraphEffectModel, ...] = (),
    interaction_terms: tuple[EffectInteractionTerm, ...] = (),
    divergence_threshold: float = 0.0,
    max_slices: int = 4096,
) -> GraphDynamicSimulationResult:
    """Propagate interventions over exact typed paths without selecting execution."""

    _validate_request(
        baseline=baseline,
        topology=topology,
        interventions=interventions,
        active_models=active_models,
        challenger_models=challenger_models,
        divergence_threshold=divergence_threshold,
        max_slices=max_slices,
    )
    active, active_reasons = _simulate_model_set(
        baseline=baseline,
        topology=topology,
        interventions=interventions,
        models=active_models,
        interaction_terms=interaction_terms,
        max_slices=max_slices,
    )
    challenger: OperationalStateTrajectory | None = None
    challenger_reasons: tuple[str, ...] = ()
    divergence: float | None = None
    if challenger_models:
        challenger, challenger_reasons = _simulate_model_set(
            baseline=baseline,
            topology=topology,
            interventions=interventions,
            models=challenger_models,
            interaction_terms=interaction_terms,
            max_slices=max_slices,
        )
        divergence = _trajectory_divergence(active, challenger)
    reasons = list((*active_reasons, *challenger_reasons))
    if divergence is not None and divergence > divergence_threshold:
        reasons.append("active_challenger_divergence")
    if any(
        model.evidence_grade
        not in {CausalEvidenceGrade.QUASI_EXPERIMENTAL, CausalEvidenceGrade.INTERVENTIONAL}
        for model in active_models
    ):
        reasons.append("causal_evidence_below_quasi_experimental")
    normalized_reasons = tuple(sorted(set(reasons)))
    return GraphDynamicSimulationResult(
        active_trajectory=active,
        challenger_trajectory=challenger,
        requires_review=bool(normalized_reasons),
        reason_codes=normalized_reasons,
        max_divergence=divergence,
    )


def _simulate_model_set(
    *,
    baseline: OperationalStateTrajectory,
    topology: tuple[GraphTopologyEdge, ...],
    interventions: tuple[GraphIntervention, ...],
    models: tuple[GraphEffectModel, ...],
    interaction_terms: tuple[EffectInteractionTerm, ...],
    max_slices: int,
) -> tuple[OperationalStateTrajectory, tuple[str, ...]]:
    adjacency = _adjacency(topology)
    baseline_values = _latest_values(baseline)
    effects: dict[tuple[str, str, datetime], tuple[float, set[str], str]] = {}
    reasons: list[str] = []
    matched_interventions: set[str] = set()
    for intervention in sorted(interventions, key=_intervention_key):
        matching_models = tuple(
            model
            for model in models
            if model.trigger_ref == intervention.trigger_ref
            and model.source_type == intervention.source_type
        )
        if not matching_models:
            reasons.append("active_model_unavailable")
            continue
        for model in matching_models:
            if model.learned_through > baseline.evidence_cutoff:
                raise ValueError("graph effect model crosses the baseline evidence cutoff")
            targets, cycle_detected, frontier_truncated = _follow_path(
                source_ref=intervention.source_ref,
                source_type=intervention.source_type,
                link_path=model.link_path,
                adjacency=adjacency,
            )
            if cycle_detected:
                reasons.append("dependency_cycle_detected")
            if frontier_truncated:
                reasons.append("path_frontier_cap_exceeded")
            if not targets:
                reasons.append("effect_path_unavailable")
                continue
            matched_interventions.add(intervention.intervention_id)
            for target_ref, target_type in targets:
                if target_type != model.target_type:
                    reasons.append("effect_target_type_mismatch")
                    continue
                effective_at = intervention.effective_at + timedelta(
                    seconds=model.propagation_lag_seconds
                )
                if effective_at > baseline.horizon_end:
                    reasons.append("effect_outside_horizon")
                    continue
                baseline_value = baseline_values.get((target_ref, model.target_metric))
                if baseline_value is None:
                    reasons.append("target_baseline_unavailable")
                    continue
                effect_delta = intervention.delta * model.gain + model.offset
                if not math.isfinite(effect_delta):
                    raise ValueError("graph effect arithmetic MUST remain finite")
                _merge_effect(
                    effects,
                    key=(target_ref, model.target_metric, effective_at.astimezone(UTC)),
                    delta=effect_delta,
                    model_ref=model.ref,
                    object_type=target_type,
                )
    matched_trigger_refs = {
        item.trigger_ref for item in interventions if item.intervention_id in matched_interventions
    }
    model_status = models[0].status if models else EffectModelStatus.ACTIVE
    for interaction in sorted(interaction_terms, key=lambda item: item.interaction_id):
        if interaction.status is not model_status:
            continue
        if not set(interaction.trigger_refs) <= matched_trigger_refs:
            reasons.append("interaction_incomplete_upstream")
            continue
        if interaction.evidence_grade not in {
            CausalEvidenceGrade.QUASI_EXPERIMENTAL,
            CausalEvidenceGrade.INTERVENTIONAL,
        }:
            reasons.append("interaction_causal_evidence_below_quasi_experimental")
        effective_at = max(item.effective_at for item in interventions) + timedelta(
            seconds=interaction.lag_seconds
        )
        if effective_at > baseline.horizon_end:
            reasons.append("interaction_outside_horizon")
            continue
        baseline_value = baseline_values.get((interaction.target_ref, interaction.metric))
        if baseline_value is None:
            reasons.append("interaction_baseline_unavailable")
            continue
        object_type = _object_type(baseline, interaction.target_ref)
        _merge_effect(
            effects,
            key=(interaction.target_ref, interaction.metric, effective_at.astimezone(UTC)),
            delta=interaction.delta,
            model_ref=interaction.model_ref,
            object_type=object_type,
        )
    if len(effects) + len(baseline.slices) > max_slices:
        reasons.append("trajectory_slice_cap_exceeded")
        effects = dict(sorted(effects.items())[: max(0, max_slices - len(baseline.slices))])
    slices = [
        StateSlice(
            object_ref=item.object_ref,
            object_type=item.object_type,
            metric=item.metric,
            value=item.value,
            effective_at=item.effective_at,
            model_ref=f"baseline:{baseline.digest}",
        )
        for item in baseline.slices
    ]
    for key, (delta, model_refs, object_type) in sorted(effects.items()):
        target_ref, metric, effective_at = key
        baseline_value = baseline_values[(target_ref, metric)]
        predicted_value = baseline_value + delta
        if not math.isfinite(predicted_value):
            raise ValueError("graph trajectory prediction MUST remain finite")
        slices.append(
            StateSlice(
                object_ref=target_ref,
                object_type=object_type,
                metric=metric,
                value=predicted_value,
                effective_at=effective_at,
                model_ref="+".join(sorted(model_refs)),
            )
        )
    slices.sort(key=lambda item: item.key)
    if len(matched_interventions) != len(interventions):
        reasons.append("unmodeled_intervention")
    normalized_reasons = tuple(sorted(set(reasons)))
    truncation_reasons = tuple(
        reason
        for reason in normalized_reasons
        if reason in {"trajectory_slice_cap_exceeded", "path_frontier_cap_exceeded"}
    )
    truncated = bool(truncation_reasons)
    return (
        OperationalStateTrajectory(
            kind=TrajectoryKind.PREDICTED,
            ontology_release=baseline.ontology_release,
            graph_revision=baseline.graph_revision,
            inventory_generation=baseline.inventory_generation,
            base_snapshot_id=baseline.base_snapshot_id,
            evidence_cutoff=baseline.evidence_cutoff,
            horizon_end=baseline.horizon_end,
            slices=tuple(slices),
            intervention_refs=tuple(item.intervention_id for item in interventions),
            source_watermarks=baseline.source_watermarks,
            complete=not normalized_reasons,
            truncated=truncated,
            truncation_reasons=truncation_reasons,
        ),
        normalized_reasons,
    )


def _validate_request(
    *,
    baseline: OperationalStateTrajectory,
    topology: tuple[GraphTopologyEdge, ...],
    interventions: tuple[GraphIntervention, ...],
    active_models: tuple[GraphEffectModel, ...],
    challenger_models: tuple[GraphEffectModel, ...],
    divergence_threshold: float,
    max_slices: int,
) -> None:
    if baseline.kind is not TrajectoryKind.OBSERVED or not baseline.complete or baseline.truncated:
        raise ValueError("graph Dynamic baseline MUST be a complete observed trajectory")
    if not topology or len(topology) > _MAX_EDGES:
        raise ValueError(f"graph topology MUST contain 1..{_MAX_EDGES} edges")
    if tuple(edge.key for edge in topology) != tuple(sorted(edge.key for edge in topology)):
        raise ValueError("graph topology MUST use deterministic order")
    if not interventions or len(interventions) > _MAX_INTERVENTIONS:
        raise ValueError(f"graph interventions MUST contain 1..{_MAX_INTERVENTIONS} values")
    if (
        not active_models
        or len(active_models) > _MAX_MODELS
        or len(challenger_models) > _MAX_MODELS
    ):
        raise ValueError("graph effect model sets MUST be non-empty and bounded")
    if any(model.status is not EffectModelStatus.ACTIVE for model in active_models):
        raise ValueError("active graph model set MUST contain only active models")
    if any(model.status is not EffectModelStatus.CHALLENGER for model in challenger_models):
        raise ValueError("challenger graph model set MUST contain only challenger models")
    if not math.isfinite(divergence_threshold) or divergence_threshold < 0.0:
        raise ValueError("graph divergence threshold MUST be finite and non-negative")
    if not 1 <= max_slices <= 4096:
        raise ValueError("graph trajectory max_slices MUST be in [1, 4096]")


def _adjacency(
    topology: tuple[GraphTopologyEdge, ...],
) -> Mapping[str, tuple[GraphTopologyEdge, ...]]:
    rows: dict[str, list[GraphTopologyEdge]] = {}
    for edge in topology:
        rows.setdefault(edge.source_ref, []).append(edge)
    return {
        source_ref: tuple(sorted(edges, key=lambda item: item.key))
        for source_ref, edges in rows.items()
    }


def _follow_path(
    *,
    source_ref: str,
    source_type: str,
    link_path: tuple[str, ...],
    adjacency: Mapping[str, tuple[GraphTopologyEdge, ...]],
) -> tuple[tuple[tuple[str, str], ...], bool, bool]:
    frontier: tuple[tuple[str, str, frozenset[str]], ...] = (
        (source_ref, source_type, frozenset({source_ref})),
    )
    cycle_detected = False
    frontier_truncated = False
    for link_type in link_path:
        next_frontier: list[tuple[str, str, frozenset[str]]] = []
        for current_ref, current_type, visited in frontier:
            for edge in adjacency.get(current_ref, ()):
                if edge.source_type != current_type or edge.link_type != link_type:
                    continue
                if edge.target_ref in visited:
                    cycle_detected = True
                    continue
                next_frontier.append(
                    (edge.target_ref, edge.target_type, visited | {edge.target_ref})
                )
        ordered = sorted(next_frontier, key=lambda item: (item[0], item[1], sorted(item[2])))
        if len(ordered) > _MAX_PATH_FRONTIER:
            frontier_truncated = True
            ordered = ordered[:_MAX_PATH_FRONTIER]
        frontier = tuple(ordered)
        if not frontier:
            break
    targets = tuple(sorted({(item[0], item[1]) for item in frontier}))
    return targets, cycle_detected, frontier_truncated


def _latest_values(trajectory: OperationalStateTrajectory) -> dict[tuple[str, str], float]:
    latest: dict[tuple[str, str], tuple[datetime, float]] = {}
    for item in trajectory.slices:
        key = item.object_ref, item.metric
        current = latest.get(key)
        if current is None or item.effective_at > current[0]:
            latest[key] = item.effective_at, item.value
    return {key: value for key, (_, value) in latest.items()}


def _object_type(trajectory: OperationalStateTrajectory, object_ref: str) -> str:
    matches = {item.object_type for item in trajectory.slices if item.object_ref == object_ref}
    if len(matches) != 1:
        raise ValueError("interaction target object type is unavailable or ambiguous")
    return next(iter(matches))


def _merge_effect(
    effects: dict[tuple[str, str, datetime], tuple[float, set[str], str]],
    *,
    key: tuple[str, str, datetime],
    delta: float,
    model_ref: str,
    object_type: str,
) -> None:
    prior_delta, refs, prior_type = effects.get(key, (0.0, set(), object_type))
    if prior_type != object_type:
        raise ValueError("graph effects disagree on target object type")
    combined = prior_delta + delta
    if not math.isfinite(combined):
        raise ValueError("combined graph effect MUST remain finite")
    effects[key] = combined, {*refs, model_ref}, object_type


def _trajectory_divergence(
    active: OperationalStateTrajectory,
    challenger: OperationalStateTrajectory,
) -> float | None:
    active_values = {item.key: item.value for item in active.slices}
    challenger_values = {item.key: item.value for item in challenger.slices}
    common = set(active_values).intersection(challenger_values)
    if not common:
        return None
    divergence = max(abs(active_values[key] - challenger_values[key]) for key in common)
    if not math.isfinite(divergence):
        raise ValueError("graph divergence arithmetic MUST remain finite")
    return divergence


def _intervention_key(item: GraphIntervention) -> tuple[datetime, str]:
    return item.effective_at.astimezone(UTC), item.intervention_id


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def _text(value: str, name: str) -> None:
    if not value.strip() or len(value) > 512 or any(ord(character) < 32 for character in value):
        raise ValueError(f"{name} MUST be bounded and non-empty")


__all__ = [
    "EffectInteractionTerm",
    "GraphDynamicSimulationResult",
    "GraphEffectModel",
    "GraphIntervention",
    "GraphTopologyEdge",
    "simulate_graph_effects",
]
