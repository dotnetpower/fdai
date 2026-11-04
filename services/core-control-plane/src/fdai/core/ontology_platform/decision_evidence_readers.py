"""Evidence readers that bind the decision FunctionTypes to the runtime ontology graph.

Every reader is read-only and fails toward ``unknown``. A truncated, incomplete, conflicted,
synthetic, or stale source never becomes an optimistic default: it surfaces as an incomplete
traversal or an unobserved factor, and the decision function then closes its gate. Graph
freshness comes from the Resources' own state-fact metadata, so a graph with no observed
metadata is unobserved rather than fresh. A reading is advice and grants no authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Protocol

from fdai.shared.contracts.execution_outcomes import (
    ExecutionLifecycleDisposition,
    execution_lifecycle_disposition,
)
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyInstanceStore,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactLane,
    state_fact_metadata_values,
)

from .decision_functions import (
    MAX_DEPTH,
    BlastRadiusEvidence,
    BlastRadiusEvidenceReader,
    ChangeRiskEvidence,
    CostOfDelayEvidence,
    ImpactedResource,
    assess_blast_radius,
)
from .recent_resource_changes import RecentResourceChangeReader

DEPENDENCY_LINK_TYPES: Final = ("depends_on", "runtime_calls")
SERVICE_LINK_TYPES: Final = ("workload_runs_on", "workload_depends_on", "implemented_by")
_RECOVERY_LINK_TYPE: Final = "recovery_targets_resource"
_SERVICE_PATH_DEPTH: Final = 3
_FAILED_CHANGE_STATUSES: Final = frozenset({"failed", "canceled", "cancelled"})
_CRITICALITY_RANK: Final = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_SHADOW_MODE: Final = "shadow"
_READY_RECOVERY_STATUS: Final = "ready"
_MAX_CHANGE_READ: Final = 20

Clock = Callable[[], datetime]


class ChangeWindowActivityReader(Protocol):
    async def is_active(self, *, target_ref: str, at: datetime) -> bool: ...


def _aware_now(clock: Clock) -> datetime:
    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("decision evidence clock MUST be timezone-aware")
    return now


def _complete(graph: OntologyGraphSnapshot) -> bool:
    return graph.source_complete and not graph.truncated


class OntologyBlastRadiusEvidenceReader:
    """Weigh the dependents of one Resource by the reviewed criticality of their services."""

    def __init__(
        self,
        store: OntologyInstanceStore,
        *,
        clock: Clock = lambda: datetime.now(UTC),
        max_depth: int = 3,
        resource_limit: int = 1_000,
        service_limit: int = 1_000,
    ) -> None:
        if not 1 <= max_depth <= MAX_DEPTH:
            raise ValueError("blast radius max_depth is outside the reviewed bound")
        if not 1 <= resource_limit <= 1_000 or not 1 <= service_limit <= 1_000:
            raise ValueError("blast radius limits MUST be between 1 and 1000")
        self._store = store
        self._clock = clock
        self._max_depth = max_depth
        self._resource_limit = resource_limit
        self._service_limit = service_limit

    async def read(self, *, target_ref: str) -> BlastRadiusEvidence | None:
        target = await self._store.get_object(target_ref)
        if target is None or target.object_type != "Resource":
            return None
        now = _aware_now(self._clock)
        graph = await self._store.traverse(
            root_ids=(target_ref,),
            root_object_types=("Resource",),
            link_types=DEPENDENCY_LINK_TYPES,
            direction="incoming",
            max_depth=self._max_depth,
            limit=self._resource_limit,
        )
        complete = _complete(graph)
        records = {item.id: item for item in graph.objects if item.object_type == "Resource"}
        records.setdefault(target_ref, target)
        depths, dependents = _dependent_depths(graph, target_ref, records)
        frontier = tuple(sorted(ref for ref, depth in depths.items() if depth == self._max_depth))
        if complete and frontier and await self._has_deeper_dependents(frontier, depths):
            complete = False
        reached = tuple(sorted(depths))
        services = await self._store.traverse(
            root_ids=reached,
            root_object_types=("Resource",),
            link_types=SERVICE_LINK_TYPES,
            direction="incoming",
            max_depth=_SERVICE_PATH_DEPTH,
            limit=self._service_limit,
        )
        complete = complete and _complete(services)
        criticality = _inherit_from_dependents(
            _criticality_by_resource(services, reached, now), depths, dependents
        )
        if not _fresh_observation(tuple(records[ref] for ref in reached), now):
            complete = False
        generation = graph.source_generation or services.source_generation or "unversioned"
        return BlastRadiusEvidence(
            resources=tuple(
                ImpactedResource(ref, depths[ref], criticality.get(ref)) for ref in reached
            ),
            traversal_complete=complete,
            source_generation=generation,
            observed_at=now,
        )

    async def _has_deeper_dependents(
        self,
        frontier: tuple[str, ...],
        depths: Mapping[str, int],
    ) -> bool:
        probe = await self._store.traverse(
            root_ids=frontier,
            root_object_types=("Resource",),
            link_types=DEPENDENCY_LINK_TYPES,
            direction="incoming",
            max_depth=1,
            limit=self._resource_limit,
        )
        if not _complete(probe):
            return True
        return any(
            item.object_type == "Resource" and item.id not in depths for item in probe.objects
        )


def _dependent_depths(
    graph: OntologyGraphSnapshot,
    target_ref: str,
    records: Mapping[str, OntologyObjectRecord],
) -> tuple[dict[str, int], dict[str, set[str]]]:
    """Breadth-first depth of each dependent, following stored links toward the target."""

    dependents: dict[str, set[str]] = {}
    for link in graph.links:
        if link.link_type in DEPENDENCY_LINK_TYPES:
            dependents.setdefault(link.to_id, set()).add(link.from_id)
    depths = {target_ref: 0}
    frontier = [target_ref]
    while frontier:
        following: list[str] = []
        for ref in frontier:
            for dependent in sorted(dependents.get(ref, ())):
                if dependent in records and dependent not in depths:
                    depths[dependent] = depths[ref] + 1
                    following.append(dependent)
        frontier = following
    return depths, dependents


def _inherit_from_dependents(
    own: Mapping[str, str],
    depths: Mapping[str, int],
    dependents: Mapping[str, set[str]],
) -> dict[str, str]:
    """Let a Resource carry the highest criticality of the Resources that depend on it."""

    effective = dict(own)
    for ref in sorted(depths, key=lambda item: -depths[item]):
        for dependent in dependents.get(ref, ()):
            if dependent not in depths or depths[dependent] <= depths[ref]:
                continue
            inherited = effective.get(dependent)
            if inherited is None:
                continue
            current = effective.get(ref)
            if current is None or _CRITICALITY_RANK[inherited] > _CRITICALITY_RANK[current]:
                effective[ref] = inherited
    return effective


def _criticality_by_resource(
    graph: OntologyGraphSnapshot,
    resource_refs: tuple[str, ...],
    now: datetime,
) -> dict[str, str]:
    """Highest reviewed criticality among the services that depend on each Resource."""

    objects = {item.id: item for item in graph.objects}
    predecessors: dict[str, set[str]] = {}
    for link in graph.links:
        if link.link_type in SERVICE_LINK_TYPES:
            predecessors.setdefault(link.to_id, set()).add(link.from_id)
    result: dict[str, str] = {}
    for ref in resource_refs:
        seen = {ref}
        frontier = [ref]
        ranks: list[int] = []
        unrecognized = False
        for _depth in range(_SERVICE_PATH_DEPTH):
            following: list[str] = []
            for node in frontier:
                for predecessor in sorted(predecessors.get(node, ())):
                    if predecessor in seen:
                        continue
                    seen.add(predecessor)
                    following.append(predecessor)
                    record = objects.get(predecessor)
                    if record is None or record.object_type != "BusinessService":
                        continue
                    if not _service_in_effect(record.properties, now):
                        continue
                    value = str(record.properties.get("criticality") or "").strip().lower()
                    if value in _CRITICALITY_RANK:
                        ranks.append(_CRITICALITY_RANK[value])
                    else:
                        unrecognized = True
            frontier = following
        if ranks and not unrecognized:
            highest = max(ranks)
            result[ref] = next(name for name, rank in _CRITICALITY_RANK.items() if rank == highest)
    return result


def _service_in_effect(properties: Mapping[str, Any], now: datetime) -> bool:
    effective_to = _timestamp(properties.get("effective_to"))
    effective_from = _timestamp(properties.get("effective_from"))
    if effective_from is not None and effective_from > now:
        return False
    return effective_to is None or effective_to > now


def _fresh_observation(records: tuple[OntologyObjectRecord, ...], now: datetime) -> bool:
    """Require some observed metadata, and no conflicted, synthetic, or stale metadata."""

    seen = False
    for record in records:
        provider_properties = record.properties.get("properties")
        if not isinstance(provider_properties, Mapping):
            continue
        raw = provider_properties.get(STATE_FACT_METADATA_PROPERTY)
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            return False
        try:
            facts = state_fact_metadata_values(raw)
        except ValueError:
            return False
        for fact in facts:
            if fact.lane is not StateFactLane.OBSERVED:
                continue
            seen = True
            ceiling = timedelta(seconds=fact.freshness_ceiling_seconds)
            if (
                fact.synthetic
                or fact.conflicts
                or fact.completeness < 1.0
                or now - fact.evidence_cutoff > ceiling
            ):
                return False
    return seen


@dataclass(frozen=True, slots=True)
class ChangeRiskLookbacks:
    """Reviewed look-back windows for the change-risk factors."""

    failed_change: timedelta = timedelta(days=7)
    recovery_rehearsal: timedelta = timedelta(days=30)
    dry_run: timedelta = timedelta(days=30)

    def __post_init__(self) -> None:
        for window in (self.failed_change, self.recovery_rehearsal, self.dry_run):
            if window <= timedelta(0):
                raise ValueError("change risk look-back windows MUST be positive")


class OntologyChangeRiskEvidenceReader:
    """Observe the change-risk factors for one Resource without defaulting any of them."""

    def __init__(
        self,
        store: OntologyInstanceStore,
        *,
        blast_radius: BlastRadiusEvidenceReader,
        change_windows: ChangeWindowActivityReader,
        recent_changes: RecentResourceChangeReader | None = None,
        lookbacks: ChangeRiskLookbacks | None = None,
        clock: Clock = lambda: datetime.now(UTC),
        query_limit: int = 500,
    ) -> None:
        if query_limit < 1:
            raise ValueError("change risk query_limit MUST be positive")
        self._store = store
        self._blast_radius = blast_radius
        self._change_windows = change_windows
        self._recent_changes = recent_changes
        self._lookbacks = lookbacks or ChangeRiskLookbacks()
        self._clock = clock
        self._query_limit = query_limit

    async def read(self, *, target_ref: str) -> ChangeRiskEvidence | None:
        target = await self._store.get_object(target_ref)
        if target is None or target.object_type != "Resource":
            return None
        now = _aware_now(self._clock)
        return ChangeRiskEvidence(
            blast_radius_tier=await self._blast_tier(target_ref),
            change_window_active=await self._change_windows.is_active(
                target_ref=target_ref, at=now
            ),
            recent_failed_changes=await self._failed_changes(target_ref, now),
            rollback_tested=await self._rollback_tested(target_ref, now),
            dry_run_passed=await self._dry_run_passed(target_ref, now),
            source_generation=f"ontology-graph:{target.revision}",
            observed_at=now,
        )

    async def _blast_tier(self, target_ref: str) -> str | None:
        evidence = await self._blast_radius.read(target_ref=target_ref)
        if evidence is None:
            return None
        result = assess_blast_radius(evidence, target_ref=target_ref, max_tier="high")
        tier = result["tier"]
        return tier if result["complete"] is True and isinstance(tier, str) else None

    async def _failed_changes(self, target_ref: str, now: datetime) -> int | None:
        if self._recent_changes is None:
            return None
        read = await self._recent_changes.read_recent_resource_changes(
            start_at=now - self._lookbacks.failed_change,
            end_at=now,
            known_at=now,
            limit=_MAX_CHANGE_READ,
        )
        if not read.complete:
            return None
        key = target_ref.casefold()
        return sum(
            1
            for change in read.changes
            if change.subject_ref.casefold() == key
            and (change.operation_status or "").strip().casefold() in _FAILED_CHANGE_STATUSES
        )

    async def _rollback_tested(self, target_ref: str, now: datetime) -> bool | None:
        graph = await self._store.traverse(
            root_ids=(target_ref,),
            root_object_types=("Resource",),
            link_types=(_RECOVERY_LINK_TYPE,),
            direction="incoming",
            max_depth=1,
            limit=self._query_limit,
        )
        if not _complete(graph):
            return None
        cutoff = now - self._lookbacks.recovery_rehearsal
        for record in graph.objects:
            if record.object_type != "RecoveryPlan":
                continue
            properties = record.properties
            rehearsed = _timestamp(properties.get("last_rehearsed_at"))
            expires = _timestamp(properties.get("expires_at"))
            if (
                str(properties.get("status") or "").strip().casefold() == _READY_RECOVERY_STATUS
                and rehearsed is not None
                and rehearsed >= cutoff
                and expires is not None
                and expires > now
            ):
                return True
        return False

    async def _dry_run_passed(self, target_ref: str, now: datetime) -> bool | None:
        graph = await self._store.query_objects(
            object_types=("ActionRun",),
            property_equals={"target_ref": target_ref},
            limit=self._query_limit,
            include_relationships=False,
        )
        if not _complete(graph):
            return None
        cutoff = now - self._lookbacks.dry_run
        for record in graph.objects:
            properties = record.properties
            ended = _timestamp(properties.get("ended_at"))
            if (
                str(properties.get("mode") or "").strip().casefold() == _SHADOW_MODE
                and execution_lifecycle_disposition(properties.get("status"))
                is ExecutionLifecycleDisposition.ACCEPTED
                and ended is not None
                and cutoff <= ended <= now
            ):
                return True
        return False


class OntologyCostOfDelayEvidenceReader:
    """Derive an hourly cost basis from the newest complete, non-synthetic observation."""

    def __init__(
        self,
        store: OntologyInstanceStore,
        *,
        metric: str,
        max_observation_age: timedelta,
        clock: Clock = lambda: datetime.now(UTC),
        query_limit: int = 200,
    ) -> None:
        if not metric.strip():
            raise ValueError("cost of delay metric MUST be non-empty")
        if max_observation_age <= timedelta(0) or query_limit < 1:
            raise ValueError("cost of delay bounds MUST be positive")
        self._store = store
        self._metric = metric
        self._max_age = max_observation_age
        self._clock = clock
        self._query_limit = query_limit

    async def read(self, *, target_ref: str) -> CostOfDelayEvidence | None:
        target = await self._store.get_object(target_ref)
        if target is None or target.object_type != "Resource":
            return None
        now = _aware_now(self._clock)
        graph = await self._store.query_objects(
            object_types=("CostObservation",),
            property_equals={"target_ref": target_ref, "metric": self._metric},
            limit=self._query_limit,
            include_relationships=False,
        )
        basis = f"cost-observation:{target_ref}:{self._metric}"
        if not _complete(graph):
            return CostOfDelayEvidence(None, None, basis, now)
        newest: tuple[datetime, OntologyObjectRecord, Decimal] | None = None
        for record in graph.objects:
            rate = self._hourly_rate(record.properties, now)
            end = _timestamp(record.properties.get("period_end"))
            if rate is None or end is None:
                continue
            if newest is None or end > newest[0]:
                newest = (end, record, rate)
        if newest is None:
            return CostOfDelayEvidence(None, None, basis, now)
        _end, record, rate = newest
        currency = str(record.properties.get("currency") or "").strip()
        return CostOfDelayEvidence(
            hourly_cost_amount=rate,
            currency=currency or None,
            basis_ref=str(record.properties.get("evidence_ref") or basis),
            observed_at=now,
        )

    def _hourly_rate(self, properties: Mapping[str, Any], now: datetime) -> Decimal | None:
        if properties.get("complete") is not True or properties.get("synthetic") is not False:
            return None
        start = _timestamp(properties.get("period_start"))
        end = _timestamp(properties.get("period_end"))
        observed = _timestamp(properties.get("observed_at"))
        if start is None or end is None or observed is None or end <= start:
            return None
        if observed > now or now - observed > self._max_age:
            return None
        raw = properties.get("value")
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str, Decimal)):
            return None
        try:
            value = Decimal(str(raw))
        except InvalidOperation:
            return None
        if not value.is_finite() or value < 0:
            return None
        hours = Decimal(str((end - start).total_seconds())) / Decimal(3600)
        return value / hours


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


__all__ = [
    "DEPENDENCY_LINK_TYPES",
    "SERVICE_LINK_TYPES",
    "ChangeRiskLookbacks",
    "ChangeWindowActivityReader",
    "OntologyBlastRadiusEvidenceReader",
    "OntologyChangeRiskEvidenceReader",
    "OntologyCostOfDelayEvidenceReader",
]
