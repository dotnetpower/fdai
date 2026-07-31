"""Bounded time-consistent incident graph materialization."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
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
)


@dataclass(frozen=True, slots=True)
class IncidentGraphBounds:
    max_depth: int = 2
    max_nodes: int = 500
    max_bytes: int = 4 * 1024 * 1024
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_depth <= 5:
            raise ValueError("max_depth MUST be in [1, 5]")
        if not 1 <= self.max_nodes <= 1000:
            raise ValueError("max_nodes MUST be in [1, 1000]")
        if self.max_bytes < 1:
            raise ValueError("max_bytes MUST be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be positive")


@dataclass(frozen=True, slots=True)
class CausalIncidentGraph:
    incident_id: str
    evidence_cutoff: datetime
    graph_revision: str
    snapshot: OntologyGraphSnapshot
    incomplete_reasons: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.snapshot.truncated and not self.incomplete_reasons


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
        if not incident_id.strip() or not root_ids or any(not item.strip() for item in root_ids):
            raise ValueError("incident_id and root_ids MUST be non-empty")
        if evidence_cutoff.tzinfo is None:
            raise ValueError("evidence_cutoff MUST be timezone-aware")
        active_bounds = bounds or IncidentGraphBounds()
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

        objects = tuple(item for item in raw.objects if _at_or_before(item, evidence_cutoff))
        object_ids = {item.id for item in objects}
        links = tuple(
            link for link in raw.links if link.from_id in object_ids and link.to_id in object_ids
        )
        reasons: list[str] = []
        if not set(root_ids) <= object_ids:
            reasons.append("root_missing_or_after_cutoff")
        encoded = _encoded_graph(objects, links)
        truncated = raw.truncated or len(encoded) > active_bounds.max_bytes
        if len(encoded) > active_bounds.max_bytes:
            reasons.append("byte_cap_exceeded")
        snapshot = OntologyGraphSnapshot(objects=objects, links=links, truncated=truncated)
        revision = hashlib.sha256(
            b"|".join((incident_id.encode(), evidence_cutoff.isoformat().encode(), encoded))
        ).hexdigest()
        return CausalIncidentGraph(
            incident_id=incident_id,
            evidence_cutoff=evidence_cutoff,
            graph_revision=revision,
            snapshot=snapshot,
            incomplete_reasons=tuple(sorted(set(reasons))),
        )


def _at_or_before(record: OntologyObjectRecord, cutoff: datetime) -> bool:
    for key in _TIME_PROPERTIES:
        raw = record.properties.get(key)
        if raw is None:
            continue
        if isinstance(raw, datetime):
            value = raw
        elif isinstance(raw, str):
            try:
                value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return False
        else:
            return False
        return value.tzinfo is not None and value <= cutoff
    return True


def _encoded_graph(
    objects: tuple[OntologyObjectRecord, ...],
    links: tuple[OntologyLinkRecord, ...],
) -> bytes:
    payload = {
        "objects": [
            {
                "id": item.id,
                "type": item.object_type,
                "revision": item.revision,
                "properties": item.properties,
            }
            for item in sorted(objects, key=lambda item: item.id)
        ],
        "links": [
            {
                "type": item.link_type,
                "from": item.from_id,
                "to": item.to_id,
                "properties": item.properties,
            }
            for item in sorted(links, key=lambda item: (item.link_type, item.from_id, item.to_id))
        ],
    }
    return json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")).encode()


__all__ = [
    "CausalIncidentGraph",
    "CausalIncidentGraphMaterializer",
    "DEFAULT_CAUSAL_LINKS",
    "IncidentGraphBounds",
]
