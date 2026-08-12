"""Build graph Dynamic requests from verified Azure ontology evidence."""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.core.assurance_twin.graph_effect import (
    GraphIntervention,
    GraphTopologyEdge,
)
from fdai.core.assurance_twin.graph_runtime import GraphDynamicSimulationRequest
from fdai.core.assurance_twin.state_trajectory import (
    DynamicInvariant,
    InvariantOperator,
    OperationalStateTrajectory,
    StateSlice,
    TrajectoryKind,
)
from fdai.core.operational_context import (
    OperationalContextEvidencePath,
    OperationalContextSnapshot,
)
from fdai.core.tiers.t1_lightweight import LearnedAction
from fdai.shared.contracts.models import Event, OntologyActionType
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_OBJECTIVE_TYPES = frozenset(
    {"ArchitectureConstraint", "CostObjective", "RecoveryObjective", "ServiceObjective"}
)
_MAX_BUILD_TIMEOUT_SECONDS = 10.0
_MAX_INTERVENTIONS = 32
_MAX_INVARIANTS = 256


@dataclass(frozen=True, slots=True)
class AzureGraphEvidencePins:
    """Immutable identities shared by every graph evidence read."""

    ontology_release: str
    graph_revision: str
    inventory_generation: str
    evidence_cutoff: datetime
    base_snapshot_id: str
    target_revision: int
    model_cutoff: datetime

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.ontology_release) is None:
            raise ValueError("graph evidence ontology_release MUST be a SHA-256 digest")
        for name, value in (
            ("graph_revision", self.graph_revision),
            ("inventory_generation", self.inventory_generation),
            ("base_snapshot_id", self.base_snapshot_id),
        ):
            if not value.strip():
                raise ValueError(f"graph evidence {name} MUST be non-empty")
        if self.evidence_cutoff.tzinfo is None or self.model_cutoff.tzinfo is None:
            raise ValueError("graph evidence cutoffs MUST be timezone-aware")
        if self.target_revision < 0:
            raise ValueError("graph evidence target_revision MUST be non-negative")


@dataclass(frozen=True, slots=True)
class AzureGraphTopologyEvidence:
    """One bounded topology read under exact graph and inventory pins."""

    pins: AzureGraphEvidencePins
    graph: OntologyGraphSnapshot
    complete: bool = True
    synthetic: bool = False
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AzureGraphInventoryEvidence:
    """Current target identity and revision from authoritative inventory."""

    pins: AzureGraphEvidencePins
    target_ref: str
    target_type: str
    observed_at: datetime
    evidence_refs: tuple[str, ...]
    complete: bool = True
    truncated: bool = False
    synthetic: bool = False
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.target_ref.strip() or not self.target_type.strip():
            raise ValueError("graph inventory target identity MUST be non-empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("graph inventory observed_at MUST be timezone-aware")
        if not self.evidence_refs or any(not item.strip() for item in self.evidence_refs):
            raise ValueError("graph inventory evidence_refs MUST be non-empty")


@dataclass(frozen=True, slots=True)
class AzureGraphMetricObservation:
    """One normalized metric value with authoritative state-fact metadata."""

    object_ref: str
    object_type: str
    metric: str
    value: float
    metadata: StateFactMetadata

    def __post_init__(self) -> None:
        if not self.object_ref.strip() or not self.object_type.strip() or not self.metric.strip():
            raise ValueError("graph metric observation identity MUST be non-empty")
        if not math.isfinite(self.value):
            raise ValueError("graph metric observation value MUST be finite")


@dataclass(frozen=True, slots=True)
class AzureReviewedMetricSemantic:
    """Reviewed mapping from an ontology objective to a Dynamic invariant."""

    semantic_ref: str
    objective_ref: str
    objective_type: str
    objective_revision: int
    metric: str
    operator: InvariantOperator
    target_ref: str | None
    effective_from: datetime
    effective_to: datetime | None
    reviewed_at: datetime
    review_receipt_ref: str
    threshold_property: str | None = None
    threshold: float | None = None
    synthetic: bool = False
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.objective_type not in _OBJECTIVE_TYPES:
            raise ValueError("reviewed metric semantic objective_type is unsupported")
        for value in (
            self.semantic_ref,
            self.objective_ref,
            self.metric,
            self.review_receipt_ref,
        ):
            if not value.strip():
                raise ValueError("reviewed metric semantic identity MUST be non-empty")
        if self.objective_revision < 0:
            raise ValueError("reviewed metric semantic objective_revision MUST be non-negative")
        if any(item.tzinfo is None for item in (self.effective_from, self.reviewed_at)) or (
            self.effective_to is not None and self.effective_to.tzinfo is None
        ):
            raise ValueError("reviewed metric semantic timestamps MUST be timezone-aware")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("reviewed metric semantic effective interval is invalid")
        if (self.threshold_property is None) == (self.threshold is None):
            raise ValueError("reviewed metric semantic MUST declare one threshold source")
        if self.threshold is not None and not math.isfinite(self.threshold):
            raise ValueError("reviewed metric semantic threshold MUST be finite")


@dataclass(frozen=True, slots=True)
class AzureGraphMetricEvidence:
    """Complete baseline metrics and reviewed semantics under exact pins."""

    pins: AzureGraphEvidencePins
    observations: tuple[AzureGraphMetricObservation, ...]
    semantics: tuple[AzureReviewedMetricSemantic, ...]
    complete: bool = True
    truncated: bool = False
    synthetic: bool = False
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AzureGraphInterventionPolicy:
    """Reviewed bound for one ActionType's graph intervention."""

    metric: str
    delta: float
    max_abs_delta: float
    horizon: timedelta
    divergence_threshold: float = 0.0
    blast_radius_metric: str = "affected_resources"
    max_slices: int = 4096

    def __post_init__(self) -> None:
        if not self.metric.strip() or not self.blast_radius_metric.strip():
            raise ValueError("graph intervention policy metrics MUST be non-empty")
        if (
            not math.isfinite(self.delta)
            or not math.isfinite(self.max_abs_delta)
            or self.max_abs_delta <= 0.0
            or abs(self.delta) > self.max_abs_delta
        ):
            raise ValueError("graph intervention delta MUST be finite and bounded")
        if self.horizon <= timedelta(0):
            raise ValueError("graph intervention horizon MUST be positive")
        if not math.isfinite(self.divergence_threshold) or self.divergence_threshold < 0.0:
            raise ValueError("graph divergence threshold MUST be finite and non-negative")
        if not 1 <= self.max_slices <= 4096:
            raise ValueError("graph intervention max_slices MUST be in [1, 4096]")


class AzureGraphOperationalContextSource(Protocol):
    async def get(
        self, *, event: Event, action: LearnedAction
    ) -> OperationalContextSnapshot | None: ...


class AzureGraphTopologyEvidenceReader(Protocol):
    async def read(
        self, *, context: OperationalContextSnapshot
    ) -> AzureGraphTopologyEvidence | None: ...


class AzureGraphInventoryEvidenceReader(Protocol):
    async def read(
        self, *, context: OperationalContextSnapshot
    ) -> AzureGraphInventoryEvidence | None: ...


class AzureGraphMetricEvidenceReader(Protocol):
    async def read(
        self, *, context: OperationalContextSnapshot
    ) -> AzureGraphMetricEvidence | None: ...


class AzureGraphDynamicSimulationRequestProvider:
    """Build read-only graph requests or hold when production evidence is unusable.

    The observed baseline is the no-action branch. Exactly one configured, bounded
    intervention is added for the learned ActionType. Timeouts and evidence-quality
    failures return ``None``; caller cancellation and unexpected provider failures
    continue to propagate.
    """

    def __init__(
        self,
        *,
        contexts: AzureGraphOperationalContextSource,
        topology: AzureGraphTopologyEvidenceReader,
        inventory: AzureGraphInventoryEvidenceReader,
        metrics: AzureGraphMetricEvidenceReader,
        action_types: Mapping[str, OntologyActionType],
        policies: Mapping[str, AzureGraphInterventionPolicy],
        build_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 2.5,
    ) -> None:
        if not action_types or not policies:
            raise ValueError("graph Dynamic action types and policies MUST be non-empty")
        if not 0.0 < build_timeout_seconds <= _MAX_BUILD_TIMEOUT_SECONDS:
            raise ValueError("graph Dynamic build timeout MUST be in (0, 10]")
        if not 0.0 < read_timeout_seconds <= build_timeout_seconds:
            raise ValueError("graph Dynamic read timeout MUST fit the build timeout")
        self._contexts = contexts
        self._topology = topology
        self._inventory = inventory
        self._metrics = metrics
        self._action_types = dict(action_types)
        self._policies = dict(policies)
        self._build_timeout_seconds = build_timeout_seconds
        self._read_timeout_seconds = read_timeout_seconds

    async def build(
        self,
        *,
        event: Event,
        action: LearnedAction,
    ) -> GraphDynamicSimulationRequest | None:
        """Build one replay-pinned request within the configured total deadline."""

        if action.action_type not in self._policies:
            return None
        try:
            async with asyncio.timeout(self._build_timeout_seconds):
                return await self._build(event=event, action=action)
        except TimeoutError:
            return None

    async def _build(
        self,
        *,
        event: Event,
        action: LearnedAction,
    ) -> GraphDynamicSimulationRequest | None:
        context = await self._contexts.get(event=event, action=action)
        if context is None or not _context_is_usable(context):
            return None
        async with asyncio.TaskGroup() as group:
            topology_task = group.create_task(self._read_topology(context))
            inventory_task = group.create_task(self._read_inventory(context))
            metrics_task = group.create_task(self._read_metrics(context))
        topology = topology_task.result()
        inventory = inventory_task.result()
        metrics = metrics_task.result()
        if topology is None or inventory is None or metrics is None:
            return None
        if not _evidence_is_usable(context, topology, inventory, metrics):
            return None
        policy = self._policies[action.action_type]
        action_type = self._action_types.get(action.action_type)
        if action_type is None or action_type.blast_radius is None:
            return None
        blast_radius = action_type.blast_radius.max_affected_resources
        if blast_radius is None:
            return None
        edges = _verified_topology(context, topology)
        if edges is None:
            return None
        slices = _baseline_slices(context, topology, metrics)
        invariants = _dynamic_invariants(
            context=context,
            topology=topology,
            metrics=metrics,
            blast_radius_metric=policy.blast_radius_metric,
            max_affected_resources=blast_radius,
        )
        if slices is None or invariants is None:
            return None
        pins = topology.pins
        source_watermarks = tuple(
            sorted(
                {
                    "branch:no-action",
                    f"model-cutoff:{_timestamp(pins.model_cutoff)}",
                    f"target-revision:{pins.target_revision}",
                    *inventory.evidence_refs,
                }
            )
        )
        baseline = OperationalStateTrajectory(
            kind=TrajectoryKind.OBSERVED,
            ontology_release=pins.ontology_release,
            graph_revision=pins.graph_revision,
            inventory_generation=pins.inventory_generation,
            base_snapshot_id=pins.base_snapshot_id,
            evidence_cutoff=pins.evidence_cutoff,
            horizon_end=pins.evidence_cutoff + policy.horizon,
            slices=slices,
            source_watermarks=source_watermarks,
        )
        intervention = GraphIntervention(
            intervention_id=f"intervention:{event.event_id}:{action.action_type}",
            trigger_ref=action.action_type,
            source_ref=inventory.target_ref,
            source_type=inventory.target_type,
            metric=policy.metric,
            delta=policy.delta,
            effective_at=pins.evidence_cutoff,
        )
        return GraphDynamicSimulationRequest(
            baseline=baseline,
            topology=edges,
            interventions=(intervention,),
            invariants=invariants,
            divergence_threshold=policy.divergence_threshold,
            max_slices=policy.max_slices,
        )

    async def _read_topology(
        self, context: OperationalContextSnapshot
    ) -> AzureGraphTopologyEvidence | None:
        try:
            async with asyncio.timeout(self._read_timeout_seconds):
                return await self._topology.read(context=context)
        except TimeoutError:
            return None

    async def _read_inventory(
        self, context: OperationalContextSnapshot
    ) -> AzureGraphInventoryEvidence | None:
        try:
            async with asyncio.timeout(self._read_timeout_seconds):
                return await self._inventory.read(context=context)
        except TimeoutError:
            return None

    async def _read_metrics(
        self, context: OperationalContextSnapshot
    ) -> AzureGraphMetricEvidence | None:
        try:
            async with asyncio.timeout(self._read_timeout_seconds):
                return await self._metrics.read(context=context)
        except TimeoutError:
            return None


def _context_is_usable(context: OperationalContextSnapshot) -> bool:
    cutoff = context.cutoff.astimezone(UTC)
    return (
        not context.review_required
        and not context.stale_sources
        and not context.conflicts
        and all(
            item.observed_at.astimezone(UTC)
            <= cutoff
            <= item.observed_at.astimezone(UTC) + timedelta(seconds=item.max_age_seconds)
            for item in context.source_freshness
        )
    )


def _evidence_is_usable(
    context: OperationalContextSnapshot,
    topology: AzureGraphTopologyEvidence,
    inventory: AzureGraphInventoryEvidence,
    metrics: AzureGraphMetricEvidence,
) -> bool:
    pins = topology.pins
    if inventory.pins != pins or metrics.pins != pins:
        return False
    target_objects = tuple(
        item
        for item in topology.graph.objects
        if item.id.casefold() == inventory.target_ref.casefold()
    )
    if (
        pins.base_snapshot_id != context.snapshot_id
        or pins.evidence_cutoff != context.cutoff
        or pins.model_cutoff != pins.evidence_cutoff
        or pins.ontology_release not in {version for _, version in context.catalog_versions}
        or inventory.target_ref.casefold() != context.target_resource_id.casefold()
        or len(target_objects) != 1
        or target_objects[0].object_type != inventory.target_type
        or target_objects[0].revision != pins.target_revision
        or inventory.observed_at > pins.evidence_cutoff
        or topology.graph.truncated
    ):
        return False
    envelopes = (topology, inventory, metrics)
    return all(
        item.complete
        and not item.synthetic
        and not item.conflicts
        and not bool(getattr(item, "truncated", False))
        for item in envelopes
    )


def _verified_topology(
    context: OperationalContextSnapshot,
    topology: AzureGraphTopologyEvidence,
) -> tuple[GraphTopologyEdge, ...] | None:
    pins = topology.pins
    objects = {item.id: item for item in topology.graph.objects}
    paths = {
        (item.object_id, item.object_type, item.revision): item for item in context.evidence_paths
    }
    cutoff = pins.evidence_cutoff
    for item in objects.values():
        path = paths.get((item.id, item.object_type, item.revision))
        if path is None or not path.provenance_refs or not _effective_at(path, cutoff):
            return None
    context_links = {
        (item.link_type, item.from_id, item.to_id): item.observation_metadata
        for item in context.evidence_links
    }
    edges: list[GraphTopologyEdge] = []
    for link in topology.graph.links:
        source = objects.get(link.from_id)
        target = objects.get(link.to_id)
        raw_metadata = link.properties.get(LINK_OBSERVATION_METADATA_PROPERTY)
        if source is None or target is None or not isinstance(raw_metadata, Mapping):
            return None
        metadata = LinkObservationMetadata.from_mapping(raw_metadata)
        if (
            context_links.get((link.link_type, link.from_id, link.to_id)) != metadata
            or metadata.inventory_generation != pins.inventory_generation
            or not _link_metadata_is_usable(metadata, cutoff, context.recorded_at)
        ):
            return None
        edges.append(
            GraphTopologyEdge(
                source_ref=source.id,
                source_type=source.object_type,
                link_type=link.link_type,
                target_ref=target.id,
                target_type=target.object_type,
            )
        )
    ordered = tuple(sorted(edges, key=lambda item: item.key))
    return ordered if ordered else None


def _baseline_slices(
    context: OperationalContextSnapshot,
    topology: AzureGraphTopologyEvidence,
    metrics: AzureGraphMetricEvidence,
) -> tuple[StateSlice, ...] | None:
    object_ids = {item.id for item in topology.graph.objects}
    slices: list[StateSlice] = []
    seen: set[tuple[str, str]] = set()
    for observation in metrics.observations:
        key = observation.object_ref, observation.metric
        if (
            observation.object_ref not in object_ids
            or key in seen
            or not _state_fact_is_usable(
                observation.metadata,
                cutoff=metrics.pins.evidence_cutoff,
                recorded_at=context.recorded_at,
            )
        ):
            return None
        seen.add(key)
        slices.append(
            StateSlice(
                object_ref=observation.object_ref,
                object_type=observation.object_type,
                metric=observation.metric,
                value=observation.value,
                effective_at=metrics.pins.evidence_cutoff,
                evidence_refs=observation.metadata.evidence_refs,
                independent_observer=True,
            )
        )
    ordered = tuple(sorted(slices, key=lambda item: item.key))
    return ordered if ordered else None


def _dynamic_invariants(
    *,
    context: OperationalContextSnapshot,
    topology: AzureGraphTopologyEvidence,
    metrics: AzureGraphMetricEvidence,
    blast_radius_metric: str,
    max_affected_resources: int,
) -> tuple[DynamicInvariant, ...] | None:
    objects = {item.id: item for item in topology.graph.objects}
    expected_refs = set(
        (
            *context.service_objective_ids,
            *context.cost_objective_ids,
            *context.recovery_objective_ids,
            *context.constraint_ids,
        )
    )
    invariants: list[DynamicInvariant] = []
    covered: set[str] = set()
    for semantic in metrics.semantics:
        objective = objects.get(semantic.objective_ref)
        if (
            objective is None
            or semantic.objective_ref not in expected_refs
            or semantic.objective_type != objective.object_type
            or semantic.objective_revision != objective.revision
            or semantic.synthetic
            or semantic.conflicts
            or semantic.reviewed_at > context.recorded_at
            or not _semantic_effective_at(semantic, context.cutoff)
        ):
            return None
        threshold = _semantic_threshold(semantic, objective)
        if threshold is None:
            return None
        covered.add(semantic.objective_ref)
        invariants.append(
            DynamicInvariant(
                invariant_id=semantic.semantic_ref,
                metric=semantic.metric,
                operator=semantic.operator,
                threshold=threshold,
                target_ref=semantic.target_ref,
            )
        )
    if covered != expected_refs:
        return None
    invariants.append(
        DynamicInvariant(
            invariant_id="action-type.blast-radius",
            metric=blast_radius_metric,
            operator=InvariantOperator.LESS_THAN_OR_EQUAL,
            threshold=float(max_affected_resources),
        )
    )
    ordered = tuple(sorted(invariants, key=lambda item: item.invariant_id))
    if not 1 <= len(ordered) <= _MAX_INVARIANTS:
        return None
    if len({item.invariant_id for item in ordered}) != len(ordered):
        return None
    available_metrics = {(item.object_ref, item.metric) for item in metrics.observations}
    if any(
        invariant.target_ref is not None
        and (invariant.target_ref, invariant.metric) not in available_metrics
        for invariant in ordered
    ):
        return None
    return ordered


def _link_metadata_is_usable(
    metadata: LinkObservationMetadata,
    cutoff: datetime,
    recorded_at: datetime,
) -> bool:
    return (
        metadata.verified
        and metadata.verification_receipt_ref is not None
        and _state_fact_is_usable(metadata.state_fact, cutoff=cutoff, recorded_at=recorded_at)
    )


def _state_fact_is_usable(
    metadata: StateFactMetadata,
    *,
    cutoff: datetime,
    recorded_at: datetime,
) -> bool:
    return (
        metadata.lane is StateFactLane.OBSERVED
        and metadata.authority in {StateFactAuthority.PROVIDER, StateFactAuthority.TELEMETRY}
        and metadata.evidence_cutoff == cutoff
        and metadata.recorded_at <= recorded_at
        and metadata.effective_at
        <= cutoff
        <= metadata.effective_at + timedelta(seconds=metadata.freshness_ceiling_seconds)
        and metadata.completeness == 1.0
        and not metadata.synthetic
        and not metadata.conflicts
    )


def _effective_at(path: OperationalContextEvidencePath, cutoff: datetime) -> bool:
    return (path.effective_from is None or path.effective_from <= cutoff) and (
        path.effective_to is None or cutoff < path.effective_to
    )


def _semantic_effective_at(semantic: AzureReviewedMetricSemantic, cutoff: datetime) -> bool:
    return semantic.effective_from <= cutoff and (
        semantic.effective_to is None or cutoff < semantic.effective_to
    )


def _semantic_threshold(
    semantic: AzureReviewedMetricSemantic,
    objective: OntologyObjectRecord,
) -> float | None:
    raw = (
        semantic.threshold
        if semantic.threshold_property is None
        else objective.properties.get(semantic.threshold_property)
    )
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    return value if math.isfinite(value) else None


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "AzureGraphDynamicSimulationRequestProvider",
    "AzureGraphEvidencePins",
    "AzureGraphInterventionPolicy",
    "AzureGraphInventoryEvidence",
    "AzureGraphInventoryEvidenceReader",
    "AzureGraphMetricEvidence",
    "AzureGraphMetricEvidenceReader",
    "AzureGraphMetricObservation",
    "AzureGraphOperationalContextSource",
    "AzureGraphTopologyEvidence",
    "AzureGraphTopologyEvidenceReader",
    "AzureReviewedMetricSemantic",
]
