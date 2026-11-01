"""Bounded time-consistent incident graph materialization."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
    normalize_json_value,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactMetadata,
    state_fact_metadata_values,
)

DEFAULT_CAUSAL_LINKS = (
    "contains",
    "attached_to",
    "depends_on",
    "implemented_by",
    "workload_runs_on",
    "workload_depends_on",
    "hypothesis_explains_finding",
    "hypothesis_claims_change",
    "hypothesis_claims_experiment",
    "evidence_supports_hypothesis",
    "evidence_refutes_hypothesis",
    "outcome_tests_hypothesis",
)
_TIME_PROPERTIES = (
    "observed_at",
    "occurred_at",
    "opened_at",
    "created_at",
    "proposed_at",
    "started_at",
    "updated_at",
    "evidence_cutoff",
    "effective_at",
    "recorded_at",
)


@dataclass(frozen=True, slots=True)
class IncidentGraphBounds:
    max_depth: int = 2
    max_nodes: int = 500
    max_bytes: int = 4 * 1024 * 1024
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if type(self.max_depth) is not int or not 1 <= self.max_depth <= 5:
            raise ValueError("max_depth MUST be in [1, 5]")
        if type(self.max_nodes) is not int or not 1 <= self.max_nodes <= 1000:
            raise ValueError("max_nodes MUST be in [1, 1000]")
        if type(self.max_bytes) is not int or self.max_bytes < 1:
            raise ValueError("max_bytes MUST be positive")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds MUST be finite and positive")


@dataclass(frozen=True, slots=True)
class CausalIncidentGraph:
    incident_id: str
    evidence_cutoff: datetime
    graph_revision: str
    snapshot: OntologyGraphSnapshot
    incomplete_reasons: tuple[str, ...] = ()
    known_at: datetime | None = None
    source_evidence_refs: tuple[str, ...] = ()
    provider_generation_refs: tuple[str, ...] = ()
    active_provider_generation: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.incident_id.strip()
            or not self.graph_revision.strip()
            or self.evidence_cutoff.tzinfo is None
            or self.evidence_cutoff.utcoffset() is None
            or (
                self.known_at is not None
                and (self.known_at.tzinfo is None or self.known_at.utcoffset() is None)
            )
        ):
            raise ValueError("CausalIncidentGraph requires non-empty ids and aware timestamps")

    @property
    def complete(self) -> bool:
        return (
            self.snapshot.source_complete
            and not self.snapshot.truncated
            and not self.incomplete_reasons
        )


class CausalIncidentGraphMaterializer:
    def __init__(self, *, store: OntologyInstanceStore) -> None:
        self._store = store

    async def materialize(
        self,
        *,
        incident_id: str,
        root_ids: tuple[str, ...],
        evidence_cutoff: datetime,
        bounds: IncidentGraphBounds | None = None,
        link_types: tuple[str, ...] = DEFAULT_CAUSAL_LINKS,
    ) -> CausalIncidentGraph:
        """Return bounded candidates, never historical proof from the current-state store.

        The cutoff bounds both event time and knowledge time. Late-recorded facts require a
        retained historical context, which ``OntologyInstanceStore.traverse`` cannot supply.
        """
        if (
            not isinstance(incident_id, str)
            or not incident_id.strip()
            or not root_ids
            or any(not isinstance(item, str) or not item.strip() for item in root_ids)
        ):
            raise ValueError("incident_id and root_ids MUST be non-empty")
        if not link_types or any(
            not isinstance(item, str) or not item.strip() for item in link_types
        ):
            raise ValueError("link_types MUST be non-empty")
        if evidence_cutoff.utcoffset() is None:
            raise ValueError("evidence_cutoff MUST be timezone-aware")
        incident_id = incident_id.strip()
        root_ids = tuple(dict.fromkeys(item.strip() for item in root_ids))
        link_types = tuple(dict.fromkeys(item.strip() for item in link_types))
        evidence_cutoff = evidence_cutoff.astimezone(UTC)
        active_bounds = bounds or IncidentGraphBounds()
        if len(set(root_ids)) > active_bounds.max_nodes:
            raise ValueError("root_ids exceed max_nodes")
        deadline = asyncio.get_running_loop().time() + active_bounds.timeout_seconds
        try:
            raw = await asyncio.wait_for(
                self._store.traverse(
                    root_ids=root_ids,
                    link_types=link_types,
                    direction="both",
                    max_depth=active_bounds.max_depth,
                    limit=active_bounds.max_nodes,
                ),
                timeout=active_bounds.timeout_seconds,
            )
        except TimeoutError as exc:
            raise TimeoutError("causal incident graph traversal exceeded its deadline") from exc

        # Current-state traversal has neither a cutoff selector nor retained revisions.
        reasons = {"historical_topology_unavailable"}
        if not raw.source_complete:
            reasons.add("source_incomplete")
        if raw.source_generation is None:
            reasons.add("source_generation_missing")
        if raw.truncated:
            reasons.add("source_truncated")
        candidates: list[OntologyObjectRecord] = []
        for item in raw.objects:
            issues = _object_issues(item, evidence_cutoff)
            reasons.update(issues)
            if not issues:
                candidates.append(item)
        candidate_ids = {item.id for item in candidates}
        eligible_links: list[OntologyLinkRecord] = []
        for link in raw.links:
            if link.link_type not in link_types:
                reasons.add("link_type_not_requested")
                continue
            issues = _link_issues(link, evidence_cutoff, raw.source_generation)
            reasons.update(issues)
            if not issues and link.from_id in candidate_ids and link.to_id in candidate_ids:
                eligible_links.append(link)
        object_ids, capped = _reachable_ids(
            candidate_ids, tuple(eligible_links), root_ids, active_bounds
        )
        if candidate_ids - object_ids:
            reasons.add("objects_outside_eligible_paths")
        reasons.update(capped)
        objects = tuple(
            sorted((item for item in candidates if item.id in object_ids), key=lambda item: item.id)
        )
        links = tuple(
            link
            for link in eligible_links
            if link.from_id in object_ids and link.to_id in object_ids
        )
        if not set(root_ids) <= object_ids:
            reasons.add("root_missing_or_after_cutoff")
        if len(raw.objects) > active_bounds.max_nodes:
            reasons.add("node_cap_exceeded")
        truncated = raw.truncated or bool(capped) or "node_cap_exceeded" in reasons
        snapshot = replace(raw, objects=objects, links=links, truncated=truncated)
        if len(_encoded_graph(snapshot)) > active_bounds.max_bytes:
            reasons.add("byte_cap_exceeded")
            snapshot = replace(snapshot, objects=(), links=(), truncated=True)
            if len(_encoded_graph(snapshot)) > active_bounds.max_bytes:
                raise ValueError("max_bytes cannot contain causal incident graph source metadata")
        receipt = {
            "incident_id": incident_id,
            "evidence_cutoff": evidence_cutoff,
            "root_ids": sorted(set(root_ids)),
            "link_types": sorted(set(link_types)),
            "bounds": {
                "max_depth": active_bounds.max_depth,
                "max_nodes": active_bounds.max_nodes,
                "max_bytes": active_bounds.max_bytes,
                "timeout_seconds": active_bounds.timeout_seconds,
            },
            "source_digest": hashlib.sha256(_encoded_graph(raw)).hexdigest(),
            "snapshot_digest": hashlib.sha256(_encoded_graph(snapshot)).hexdigest(),
            "incomplete_reasons": sorted(reasons),
        }
        revision = hashlib.sha256(_encode(receipt)).hexdigest()
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("causal incident graph materialization exceeded its deadline")
        return CausalIncidentGraph(
            incident_id=incident_id,
            evidence_cutoff=evidence_cutoff,
            graph_revision=revision,
            snapshot=snapshot,
            incomplete_reasons=tuple(sorted(reasons)),
        )


def _object_issues(
    record: OntologyObjectRecord, cutoff: datetime, *, known_at: datetime | None = None
) -> set[str]:
    issues = _property_time_issues(record.properties, cutoff, prefix="object", known_at=known_at)
    has_time = any(key in record.properties for key in _TIME_PROPERTIES)
    if STATE_FACT_METADATA_PROPERTY in record.properties:
        has_time = True
        metadata = record.properties[STATE_FACT_METADATA_PROPERTY]
        try:
            if not isinstance(metadata, Mapping):
                raise ValueError("state fact metadata MUST be a mapping")
            for fact in state_fact_metadata_values(metadata):
                issues.update(
                    f"object_{reason}" for reason in _fact_issues(fact, cutoff, known_at=known_at)
                )
        except ValueError:
            issues.add("object_metadata_invalid")
    if not has_time:
        issues.add("object_time_missing")
    return issues


def _property_time_issues(
    properties: Mapping[str, object],
    cutoff: datetime,
    *,
    prefix: str,
    known_at: datetime | None = None,
) -> set[str]:
    issues: set[str] = set()
    for key in _TIME_PROPERTIES:
        if key not in properties:
            continue
        raw = properties[key]
        try:
            value = (
                datetime.fromisoformat(raw.replace("Z", "+00:00")) if isinstance(raw, str) else raw
            )
            if not isinstance(value, datetime) or value.utcoffset() is None:
                issues.add(f"{prefix}_time_invalid")
            else:
                bound = (known_at or cutoff) if key == "recorded_at" else cutoff
                if value > bound:
                    issues.add(f"{prefix}_after_cutoff")
        except ValueError:
            issues.add(f"{prefix}_time_invalid")
    return issues


def _link_issues(
    link: OntologyLinkRecord,
    cutoff: datetime,
    generation: str | None,
    *,
    known_at: datetime | None = None,
    generations: frozenset[str] | None = None,
) -> set[str]:
    raw = link.properties.get(LINK_OBSERVATION_METADATA_PROPERTY)
    if raw is None:
        return {"link_metadata_missing"}
    try:
        if not isinstance(raw, Mapping):
            raise ValueError("link observation metadata MUST be a mapping")
        metadata = LinkObservationMetadata.from_mapping(raw)
    except ValueError:
        return {"link_metadata_invalid"}
    issues = _property_time_issues(link.properties, cutoff, prefix="link", known_at=known_at)
    issues.update(
        f"link_{reason}" for reason in _fact_issues(metadata.state_fact, cutoff, known_at=known_at)
    )
    if not metadata.verified:
        issues.add("link_unverified")
    accepted_generations = generations if generations is not None else frozenset({generation})
    if (
        metadata.inventory_generation is not None
        and metadata.inventory_generation not in accepted_generations
    ):
        issues.add("link_generation_mismatch")
    return issues


def _fact_issues(
    metadata: StateFactMetadata, cutoff: datetime, *, known_at: datetime | None = None
) -> set[str]:
    issues: set[str] = set()
    if metadata.effective_at > cutoff or metadata.evidence_cutoff > cutoff:
        issues.add("after_cutoff")
    if metadata.recorded_at > (known_at or cutoff):
        issues.add("not_known_at_cutoff")
    if (cutoff - metadata.effective_at).total_seconds() > metadata.freshness_ceiling_seconds:
        issues.add("stale")
    if metadata.completeness != 1:
        issues.add("incomplete")
    if metadata.synthetic:
        issues.add("synthetic")
    if metadata.conflicts:
        issues.add("conflicting")
    return issues


def _reachable_ids(
    candidates: set[str],
    links: tuple[OntologyLinkRecord, ...],
    roots: tuple[str, ...],
    bounds: IncidentGraphBounds,
) -> tuple[set[str], set[str]]:
    """Recompute reachability after evidence rejection; discarded paths cannot bridge nodes."""
    adjacency: dict[str, set[str]] = {}
    for link in links:
        adjacency.setdefault(link.from_id, set()).add(link.to_id)
        adjacency.setdefault(link.to_id, set()).add(link.from_id)
    visited = set(roots) & candidates
    frontier = visited
    reasons: set[str] = set()
    for _ in range(bounds.max_depth):
        next_ids = set().union(*(adjacency.get(item, set()) for item in frontier)) - visited
        available = bounds.max_nodes - len(visited)
        if len(next_ids) > available:
            next_ids = set(sorted(next_ids)[:available])
            reasons.add("node_cap_exceeded")
        visited |= next_ids
        frontier = next_ids
        if not frontier:
            break
    if set().union(*(adjacency.get(item, set()) for item in frontier)) - visited:
        reasons.add("depth_cap_exceeded")
    return visited, reasons


def _encoded_graph(snapshot: OntologyGraphSnapshot) -> bytes:
    # Sort by full canonical content so repeated endpoint identities cannot make order matter.
    payload = {
        "objects": sorted(
            [
                {
                    "id": item.id,
                    "type": item.object_type,
                    "revision": item.revision,
                    "properties": item.properties,
                    "type_ref": item.type_ref.model_dump(mode="json") if item.type_ref else None,
                }
                for item in snapshot.objects
            ],
            key=_encode,
        ),
        "links": sorted(
            [
                {
                    "type": item.link_type,
                    "from": item.from_id,
                    "to": item.to_id,
                    "properties": item.properties,
                    "type_ref": item.type_ref.model_dump(mode="json") if item.type_ref else None,
                }
                for item in snapshot.links
            ],
            key=_encode,
        ),
        "truncated": snapshot.truncated,
        "source_complete": snapshot.source_complete,
        "source_generation": snapshot.source_generation,
        "source_incomplete_reason": snapshot.source_incomplete_reason,
    }
    return _encode(payload)


def _encode(
    payload: Mapping[str, object],
) -> bytes:
    return json.dumps(
        normalize_json_value(payload), allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode()


__all__ = [
    "CausalIncidentGraph",
    "CausalIncidentGraphMaterializer",
    "DEFAULT_CAUSAL_LINKS",
    "IncidentGraphBounds",
]
