"""Strict Azure adapters for graph-wide Dynamic simulation evidence.

The adapter reads a promoted inventory projection, admits only complete and
independently verified topology, and builds an A0 request. It owns no provider
mutation client, executor identity, approval verifier, or promotion writer.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Mapping
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
    OperationalStateTrajectory,
    StateSlice,
    TrajectoryKind,
)
from fdai.core.tiers.t1_lightweight import LearnedAction
from fdai.shared.contracts.models import Event

_MAX_OBJECTS = 128
_MAX_EDGES = 4096
_MAX_METRICS_PER_OBJECT = 64
_MAX_REFS = 256
_MAX_HORIZON = timedelta(days=7)
_MAX_FRESHNESS = timedelta(days=365)


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value.removeprefix("sha256:")) == 64
        and all(character in "0123456789abcdef" for character in value.removeprefix("sha256:"))
    )


def _digest_text(value: Mapping[str, object], key: str) -> str:
    item = _text(value, key)
    if not _is_digest(item):
        raise ValueError(f"Azure graph snapshot {key} MUST be a SHA-256 digest")
    return item


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item or len(item) > 1024:
        raise ValueError(f"Azure graph snapshot {key} MUST be bounded text")
    return item


def _timestamp(value: Mapping[str, object], key: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, key).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Azure graph snapshot {key} MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _string_tuple(
    value: Mapping[str, object],
    key: str,
    *,
    maximum: int = _MAX_REFS,
) -> tuple[str, ...]:
    item = value.get(key)
    if (
        not isinstance(item, list)
        or not 1 <= len(item) <= maximum
        or any(not isinstance(part, str) or not part for part in item)
    ):
        raise ValueError(f"Azure graph snapshot {key} MUST be a bounded string array")
    result = tuple(item)
    if len(result) != len(set(result)):
        raise ValueError(f"Azure graph snapshot {key} MUST be unique")
    return result


@dataclass(frozen=True, slots=True)
class AzureGraphStateObject:
    """One revision-pinned observed object used by the graph baseline."""

    object_ref: str
    object_type: str
    revision: str
    metrics: Mapping[str, float]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.object_ref or not self.object_type or not self.revision:
            raise ValueError("Azure graph object identity MUST be non-empty")
        if not 1 <= len(self.metrics) <= _MAX_METRICS_PER_OBJECT:
            raise ValueError("Azure graph object metrics MUST be bounded")
        if any(
            not isinstance(name, str)
            or not name
            or not isinstance(raw, (int, float))
            or isinstance(raw, bool)
            or not math.isfinite(float(raw))
            for name, raw in self.metrics.items()
        ):
            raise ValueError("Azure graph object metrics MUST contain finite numbers")
        if (
            not 1 <= len(self.evidence_refs) <= _MAX_REFS
            or len(self.evidence_refs) != len(set(self.evidence_refs))
            or any(not _is_digest(item) for item in self.evidence_refs)
        ):
            raise ValueError("Azure graph object evidence refs MUST be unique SHA-256 digests")


@dataclass(frozen=True, slots=True)
class AzureVerifiedGraphLink:
    """One typed topology edge with independent observation verification."""

    edge: GraphTopologyEdge
    observed_at: datetime
    freshness_seconds: int
    observation_source: str
    verifier_identity: str
    evidence_refs: tuple[str, ...]
    complete: bool
    verified: bool
    synthetic: bool = False
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("Azure graph link observed_at MUST be timezone-aware")
        if not 1 <= self.freshness_seconds <= int(_MAX_FRESHNESS.total_seconds()):
            raise ValueError("Azure graph link freshness MUST be positive and bounded")
        if (
            not self.observation_source
            or not self.verifier_identity
            or self.observation_source == self.verifier_identity
        ):
            raise ValueError("Azure graph link requires an independent verifier")
        if (
            not 1 <= len(self.evidence_refs) <= _MAX_REFS
            or len(self.evidence_refs) != len(set(self.evidence_refs))
            or any(not _is_digest(item) for item in self.evidence_refs)
        ):
            raise ValueError("Azure graph link evidence refs MUST be unique SHA-256 digests")
        if len(self.conflicts) > 32 or len(self.conflicts) != len(set(self.conflicts)):
            raise ValueError("Azure graph link conflicts MUST be unique and bounded")

    def trusted_at(self, cutoff: datetime) -> bool:
        """Return whether the link can enter a production simulation topology."""

        observed_at = self.observed_at.astimezone(UTC)
        return (
            self.complete
            and self.verified
            and not self.synthetic
            and not self.conflicts
            and observed_at <= cutoff
            and cutoff - observed_at <= timedelta(seconds=self.freshness_seconds)
        )


@dataclass(frozen=True, slots=True)
class AzureGraphOperationalSnapshot:
    """One exact, bounded graph baseline from promoted inventory evidence."""

    resource_ref: str
    ontology_release_digest: str
    graph_revision: str
    inventory_generation: str
    base_snapshot_id: str
    observed_at: datetime
    objects: tuple[AzureGraphStateObject, ...]
    links: tuple[AzureVerifiedGraphLink, ...]
    source_watermarks: tuple[str, ...]
    complete: bool
    truncated: bool

    def __post_init__(self) -> None:
        if not self.resource_ref:
            raise ValueError("Azure graph snapshot resource_ref MUST be non-empty")
        if not _is_digest(self.ontology_release_digest):
            raise ValueError("Azure graph snapshot ontology release MUST be a SHA-256 digest")
        if not self.graph_revision or not self.inventory_generation or not self.base_snapshot_id:
            raise ValueError("Azure graph snapshot exact identities MUST be non-empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("Azure graph snapshot observed_at MUST be timezone-aware")
        if not 1 <= len(self.objects) <= _MAX_OBJECTS or len(self.links) > _MAX_EDGES:
            raise ValueError("Azure graph snapshot objects and links MUST be bounded")
        object_refs = tuple(item.object_ref for item in self.objects)
        if len(object_refs) != len(set(object_refs)) or self.resource_ref not in object_refs:
            raise ValueError(
                "Azure graph snapshot object identities MUST be unique and include target"
            )
        if not 1 <= len(self.source_watermarks) <= _MAX_REFS or len(self.source_watermarks) != len(
            set(self.source_watermarks)
        ):
            raise ValueError("Azure graph snapshot source watermarks MUST be unique and bounded")
        if self.complete == self.truncated:
            raise ValueError("Azure graph snapshot completeness and truncation are inconsistent")
        objects = {item.object_ref: item for item in self.objects}
        for link in self.links:
            source = objects.get(link.edge.source_ref)
            target = objects.get(link.edge.target_ref)
            if (
                source is None
                or target is None
                or source.object_type != link.edge.source_type
                or target.object_type != link.edge.target_type
            ):
                raise ValueError("Azure graph link endpoints do not match snapshot objects")


class AzureGraphOperationalSnapshotSource(Protocol):
    async def get(self, resource_ref: str) -> AzureGraphOperationalSnapshot | None: ...


AzureGraphInventoryContextReader = Callable[[str], Awaitable[Mapping[str, object] | None]]


class AzureCachedGraphOperationalSnapshotSource:
    """Decode graph Dynamic evidence from a promoted inventory context."""

    def __init__(self, reader: AzureGraphInventoryContextReader) -> None:
        self._reader = reader

    async def get(self, resource_ref: str) -> AzureGraphOperationalSnapshot | None:
        value = await self._reader(resource_ref)
        if value is None:
            return None
        props = value.get("props")
        if not isinstance(props, Mapping):
            raise ValueError("Azure inventory graph context props MUST be an object")
        operational = props.get("operational_context")
        if not isinstance(operational, Mapping):
            raise ValueError("Azure inventory graph context lacks operational_context")
        graph = operational.get("graph_dynamic")
        if not isinstance(graph, Mapping):
            return None
        required = {
            "ontology_release_digest",
            "graph_revision",
            "inventory_generation",
            "base_snapshot_id",
            "observed_at",
            "objects",
            "links",
            "source_watermarks",
            "complete",
            "truncated",
        }
        if set(graph) != required:
            raise ValueError("Azure inventory graph_dynamic has unexpected fields")
        raw_objects = graph.get("objects")
        raw_links = graph.get("links")
        if not isinstance(raw_objects, list) or not isinstance(raw_links, list):
            raise ValueError("Azure graph objects and links MUST be arrays")
        objects = tuple(_object(item) for item in raw_objects)
        links = tuple(_link(item) for item in raw_links)
        resource_id = value.get("resource_id")
        if not isinstance(resource_id, str) or resource_id.casefold() != resource_ref.casefold():
            raise ValueError("Azure inventory graph target identity changed")
        return AzureGraphOperationalSnapshot(
            resource_ref=resource_id,
            ontology_release_digest=_digest_text(graph, "ontology_release_digest"),
            graph_revision=_text(graph, "graph_revision"),
            inventory_generation=_text(graph, "inventory_generation"),
            base_snapshot_id=_text(graph, "base_snapshot_id"),
            observed_at=_timestamp(graph, "observed_at"),
            objects=objects,
            links=links,
            source_watermarks=_string_tuple(graph, "source_watermarks", maximum=128),
            complete=_boolean(graph, "complete"),
            truncated=_boolean(graph, "truncated"),
        )


def _object(value: object) -> AzureGraphStateObject:
    if not isinstance(value, Mapping) or set(value) != {
        "object_ref",
        "object_type",
        "revision",
        "metrics",
        "evidence_refs",
    }:
        raise ValueError("Azure graph object has unexpected fields")
    return AzureGraphStateObject(
        object_ref=_text(value, "object_ref"),
        object_type=_text(value, "object_type"),
        revision=_text(value, "revision"),
        metrics=_metrics(value),
        evidence_refs=_string_tuple(value, "evidence_refs"),
    )


def _link(value: object) -> AzureVerifiedGraphLink:
    if not isinstance(value, Mapping) or set(value) != {
        "source_ref",
        "source_type",
        "link_type",
        "target_ref",
        "target_type",
        "observed_at",
        "freshness_seconds",
        "observation_source",
        "verifier_identity",
        "evidence_refs",
        "complete",
        "verified",
        "synthetic",
        "conflicts",
    }:
        raise ValueError("Azure graph link has unexpected fields")
    conflicts_raw = value.get("conflicts")
    if not isinstance(conflicts_raw, list) or any(
        not isinstance(item, str) for item in conflicts_raw
    ):
        raise ValueError("Azure graph link conflicts MUST be an array")
    freshness = value.get("freshness_seconds")
    if not isinstance(freshness, int) or isinstance(freshness, bool):
        raise ValueError("Azure graph link freshness_seconds MUST be an integer")
    return AzureVerifiedGraphLink(
        edge=GraphTopologyEdge(
            source_ref=_text(value, "source_ref"),
            source_type=_text(value, "source_type"),
            link_type=_text(value, "link_type"),
            target_ref=_text(value, "target_ref"),
            target_type=_text(value, "target_type"),
        ),
        observed_at=_timestamp(value, "observed_at"),
        freshness_seconds=freshness,
        observation_source=_text(value, "observation_source"),
        verifier_identity=_text(value, "verifier_identity"),
        evidence_refs=_string_tuple(value, "evidence_refs"),
        complete=_boolean(value, "complete"),
        verified=_boolean(value, "verified"),
        synthetic=_boolean(value, "synthetic"),
        conflicts=tuple(conflicts_raw),
    )


def _boolean(value: Mapping[str, object], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"Azure graph snapshot {key} MUST be boolean")
    return item


def _metrics(value: Mapping[str, object]) -> Mapping[str, float]:
    raw_metrics = value.get("metrics")
    if not isinstance(raw_metrics, Mapping):
        raise ValueError("Azure graph object metrics MUST be an object")
    metrics: dict[str, float] = {}
    for name, raw in raw_metrics.items():
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(raw, (int, float))
            or isinstance(raw, bool)
            or not math.isfinite(float(raw))
        ):
            raise ValueError("Azure graph object metrics MUST contain finite numbers")
        metrics[name] = float(raw)
    return metrics


@dataclass(frozen=True, slots=True)
class AzureGraphDynamicPolicy:
    """Reviewed action-specific graph request policy."""

    action_type_ref: str
    metric: str
    effect_delta: float
    horizon: timedelta
    invariants: tuple[DynamicInvariant, ...]
    divergence_threshold: float = 0.0
    max_snapshot_age: timedelta = timedelta(minutes=5)
    max_edges: int = _MAX_EDGES
    max_slices: int = 4096

    def __post_init__(self) -> None:
        if not self.action_type_ref.startswith("action-type:") or not self.metric:
            raise ValueError("Azure graph Dynamic policy identity MUST be exact and non-empty")
        if not math.isfinite(self.effect_delta):
            raise ValueError("Azure graph Dynamic effect_delta MUST be finite")
        if not timedelta(0) < self.horizon <= _MAX_HORIZON:
            raise ValueError("Azure graph Dynamic horizon MUST be positive and bounded")
        if not self.invariants or len(self.invariants) > 256:
            raise ValueError("Azure graph Dynamic invariants MUST be non-empty and bounded")
        if not math.isfinite(self.divergence_threshold) or self.divergence_threshold < 0:
            raise ValueError("Azure graph Dynamic divergence threshold MUST be non-negative")
        if self.max_snapshot_age <= timedelta(0):
            raise ValueError("Azure graph Dynamic max_snapshot_age MUST be positive")
        if not 1 <= self.max_edges <= _MAX_EDGES or not 1 <= self.max_slices <= 4096:
            raise ValueError("Azure graph Dynamic request bounds are invalid")


class AzureGraphDynamicSimulationRequestProvider:
    """Build exact graph Dynamic requests from trusted promoted evidence."""

    def __init__(
        self,
        *,
        snapshots: AzureGraphOperationalSnapshotSource,
        policies: Mapping[str, AzureGraphDynamicPolicy],
        max_future_skew: timedelta = timedelta(minutes=1),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not policies or len(policies) > 64:
            raise ValueError("Azure graph Dynamic policies MUST contain 1..64 entries")
        if max_future_skew < timedelta(0):
            raise ValueError("Azure graph Dynamic future skew MUST be non-negative")
        self._snapshots = snapshots
        self._policies = dict(policies)
        self._max_future_skew = max_future_skew
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def build(
        self,
        *,
        event: Event,
        action: LearnedAction,
    ) -> GraphDynamicSimulationRequest | None:
        policy = self._policies.get(action.action_type)
        if policy is None:
            return None
        resource_ref = _resource_ref(event)
        snapshot = await self._snapshots.get(resource_ref)
        if snapshot is None:
            return None
        evaluated_at = self._clock()
        if evaluated_at.tzinfo is None:
            raise TypeError("Azure graph Dynamic clock MUST return an aware datetime")
        evaluated_at = evaluated_at.astimezone(UTC)
        cutoff = snapshot.observed_at.astimezone(UTC)
        if (
            snapshot.resource_ref.casefold() != resource_ref.casefold()
            or not snapshot.complete
            or snapshot.truncated
            or not snapshot.links
            or not evaluated_at - policy.max_snapshot_age
            <= cutoff
            <= evaluated_at + self._max_future_skew
            or len(snapshot.links) > policy.max_edges
            or any(not link.trusted_at(cutoff) for link in snapshot.links)
        ):
            return None
        target = next(item for item in snapshot.objects if item.object_ref == snapshot.resource_ref)
        if policy.metric not in target.metrics:
            return None
        slices = tuple(
            sorted(
                (
                    StateSlice(
                        object_ref=item.object_ref,
                        object_type=item.object_type,
                        metric=metric,
                        value=float(value),
                        effective_at=cutoff,
                        evidence_refs=item.evidence_refs,
                        independent_observer=True,
                    )
                    for item in snapshot.objects
                    for metric, value in item.metrics.items()
                ),
                key=lambda item: item.key,
            )
        )
        if len(slices) > policy.max_slices:
            return None
        baseline = OperationalStateTrajectory(
            kind=TrajectoryKind.OBSERVED,
            ontology_release=snapshot.ontology_release_digest,
            graph_revision=snapshot.graph_revision,
            inventory_generation=snapshot.inventory_generation,
            base_snapshot_id=snapshot.base_snapshot_id,
            evidence_cutoff=cutoff,
            horizon_end=cutoff + policy.horizon,
            slices=slices,
            source_watermarks=tuple(
                sorted(
                    {
                        *snapshot.source_watermarks,
                        *(
                            f"target-revision:{item.object_ref}:{item.revision}"
                            for item in snapshot.objects
                        ),
                    }
                )
            ),
        )
        intervention_ref = (
            f"{policy.action_type_ref}#target={target.object_ref}@{target.revision}"
            f"#experiment={action.signature}"
        )
        return GraphDynamicSimulationRequest(
            baseline=baseline,
            topology=tuple(link.edge for link in snapshot.links),
            interventions=(
                GraphIntervention(
                    intervention_id=intervention_ref,
                    trigger_ref=policy.action_type_ref,
                    source_ref=target.object_ref,
                    source_type=target.object_type,
                    metric=policy.metric,
                    delta=policy.effect_delta,
                    effective_at=cutoff,
                ),
            ),
            invariants=policy.invariants,
            divergence_threshold=policy.divergence_threshold,
            max_slices=policy.max_slices,
        )


def _resource_ref(event: Event) -> str:
    if event.resource_ref:
        return event.resource_ref
    resource = event.payload.get("resource")
    if isinstance(resource, Mapping) and isinstance(resource.get("id"), str):
        return str(resource["id"])
    raise ValueError("Azure graph Dynamic evidence requires an exact resource_ref")


__all__ = [
    "AzureCachedGraphOperationalSnapshotSource",
    "AzureGraphDynamicPolicy",
    "AzureGraphDynamicSimulationRequestProvider",
    "AzureGraphOperationalSnapshot",
    "AzureGraphOperationalSnapshotSource",
    "AzureGraphStateObject",
    "AzureVerifiedGraphLink",
]
