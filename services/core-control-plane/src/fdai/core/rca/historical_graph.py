"""Materialize bounded incident evidence from retained bitemporal topology."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import asdict, replace
from datetime import UTC, datetime

from fdai.core.ontology_platform.topology_history import TopologyHistoryReader, graph_at
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyLinkRecord

from .incident_graph import (
    DEFAULT_CAUSAL_LINKS,
    CausalIncidentGraph,
    IncidentGraphBounds,
    _encode,
    _encoded_graph,
    _link_issues,
    _object_issues,
    _reachable_ids,
)


class HistoricalCausalIncidentGraphMaterializer:
    """Read one pinned release at event time using only then-known retained evidence."""

    def __init__(
        self, *, history: TopologyHistoryReader, release_digest: str | None = None
    ) -> None:
        if release_digest is not None and (
            not isinstance(release_digest, str)
            or not release_digest.startswith("sha256:")
            or len(release_digest) != 71
            or any(char not in "0123456789abcdef" for char in release_digest[7:])
        ):
            raise ValueError("historical causal graph requires an exact release digest")
        self._history = history
        self._release = release_digest

    async def materialize(
        self,
        *,
        incident_id: str,
        root_ids: tuple[str, ...],
        evidence_cutoff: datetime,
        known_at: datetime,
        bounds: IncidentGraphBounds | None = None,
        link_types: tuple[str, ...] = DEFAULT_CAUSAL_LINKS,
    ) -> CausalIncidentGraph:
        if (
            not isinstance(incident_id, str)
            or not incident_id.strip()
            or not isinstance(root_ids, (list, tuple))
            or not isinstance(link_types, (list, tuple))
            or not root_ids
            or not link_types
            or any(
                not isinstance(value, str) or not value.strip()
                for value in (*root_ids, *link_types)
            )
        ):
            raise ValueError("historical incident identity, roots and link types are required")
        incident_id = incident_id.strip()
        root_ids = tuple(dict.fromkeys(item.strip() for item in root_ids))
        link_types = tuple(dict.fromkeys(item.strip() for item in link_types))
        if evidence_cutoff.utcoffset() is None or known_at.utcoffset() is None:
            raise ValueError("historical incident cutoffs MUST be timezone-aware")
        if evidence_cutoff > known_at:
            raise ValueError("historical incident evidence cutoff MUST NOT exceed known_at")
        cutoff, knowledge = evidence_cutoff.astimezone(UTC), known_at.astimezone(UTC)
        limits = bounds or IncidentGraphBounds()
        if len(set(root_ids)) > limits.max_nodes:
            raise ValueError("historical incident roots exceed max_nodes")
        deadline = asyncio.get_running_loop().time() + limits.timeout_seconds
        async with asyncio.timeout(limits.timeout_seconds):
            batches = await self._history.read(as_of=cutoff, known_at=knowledge)
            if (
                sum(len(batch.object_revisions) + len(batch.link_revisions) for batch in batches)
                > 20_000
            ):
                raise ValueError("historical causal graph exceeds 20000 retained revisions")
            view = graph_at(batches, as_of=cutoff, known_at=knowledge)
            reasons: set[str] = set()
            if not view.complete:
                reasons.add("historical_source_incomplete")
            if len(view.ontology_release_digests) != 1 or (
                self._release is not None and view.ontology_release_digests != (self._release,)
            ):
                reasons.add("historical_release_mismatch")
            generations = frozenset(view.provider_generation_refs)
            selected_batches = tuple(
                batch for batch in batches if batch.revision_id in view.revision_ids
            )
            active_batch = max(
                selected_batches,
                key=lambda item: (item.effective_at, item.recorded_at, item.revision_id),
                default=None,
            )
            baseline_times = {
                (batch.effective_at, batch.recorded_at)
                for batch in selected_batches
                if batch.complete_snapshot
            }
            conflict_batches = tuple(
                batch
                for batch in batches
                if batch.effective_at <= cutoff
                and batch.recorded_at <= knowledge
                and (
                    batch.revision_id in view.revision_ids
                    or (
                        batch.complete_snapshot
                        and (batch.effective_at, batch.recorded_at) in baseline_times
                    )
                )
            )
            winning_link_times: dict[tuple[str, str, str], tuple[datetime, datetime]] = {}
            for batch in selected_batches:
                for link_revision in batch.link_revisions:
                    if link_revision.effective_at <= cutoff:
                        times = (link_revision.effective_at, link_revision.recorded_at)
                        winning_link_times[link_revision.key] = max(
                            times, winning_link_times.get(link_revision.key, times)
                        )
            possible_links = tuple(
                OntologyLinkRecord(item.link_type, item.from_id, item.to_id)
                for batch in conflict_batches
                for item in batch.link_revisions
                if item.link_type in link_types and item.effective_at <= cutoff
            )
            possible_ids = {
                item.object_id
                for batch in conflict_batches
                for item in batch.object_revisions
                if item.effective_at <= cutoff
            }
            conflict_ids, conflict_caps = _reachable_ids(
                possible_ids, possible_links, root_ids, limits
            )
            reasons.update(conflict_caps)
            selected_links = tuple(
                link for link in view.graph.links if link.link_type in link_types
            )
            selected_ids, selected_caps = _reachable_ids(
                {record.id for record in view.graph.objects}, selected_links, root_ids, limits
            )
            reasons.update(selected_caps)
            seen_revisions: dict[tuple[object, ...], tuple[object, ...]] = {}
            baselines: dict[tuple[datetime, datetime], bytes] = {}
            endpoint_types = {record.id: record.object_type for record in view.graph.objects}
            for batch in conflict_batches:
                if batch.complete_snapshot:
                    baseline_key = (batch.effective_at, batch.recorded_at)
                    content = _encode(
                        {
                            "objects": sorted(
                                (
                                    item.object_id,
                                    item.object_type,
                                    item.deleted,
                                    item.properties_json,
                                )
                                for item in batch.object_revisions
                                if item.object_id in conflict_ids
                            ),
                            "links": sorted(
                                (*item.key, item.deleted, item.properties_json)
                                for item in batch.link_revisions
                                if {item.from_id, item.to_id} <= conflict_ids
                                and item.link_type in link_types
                            ),
                        }
                    )
                    if baseline_key in baselines and baselines[baseline_key] != content:
                        reasons.add("historical_equal_time_conflict")
                    baselines[baseline_key] = content
                for item in batch.object_revisions:
                    if item.object_id not in conflict_ids or item.effective_at > cutoff:
                        continue
                    key = ("object", item.object_id, item.effective_at, item.recorded_at)
                    value = (item.deleted, item.object_type, item.properties_json)
                    if key in seen_revisions and seen_revisions[key] != value:
                        reasons.add("historical_equal_time_conflict")
                    seen_revisions[key] = value
                for link_revision in batch.link_revisions:
                    if (
                        not {link_revision.from_id, link_revision.to_id} <= conflict_ids
                        or link_revision.effective_at > cutoff
                        or link_revision.link_type not in link_types
                    ):
                        continue
                    link_key = (
                        "link",
                        *link_revision.key,
                        link_revision.effective_at,
                        link_revision.recorded_at,
                    )
                    link_value = (
                        link_revision.deleted,
                        link_revision.from_type,
                        link_revision.to_type,
                        link_revision.properties_json,
                    )
                    if (
                        batch.revision_id in view.revision_ids
                        and not link_revision.deleted
                        and winning_link_times.get(link_revision.key)
                        == (link_revision.effective_at, link_revision.recorded_at)
                        and {link_revision.from_id, link_revision.to_id} <= selected_ids
                        and (
                            endpoint_types.get(link_revision.from_id) != link_revision.from_type
                            or endpoint_types.get(link_revision.to_id) != link_revision.to_type
                        )
                    ):
                        reasons.add("historical_endpoint_type_mismatch")
                    if link_key in seen_revisions and seen_revisions[link_key] != link_value:
                        reasons.add("historical_equal_time_conflict")
                    seen_revisions[link_key] = link_value
            eligible_objects = []
            for record in view.graph.objects:
                if record.id not in selected_ids:
                    continue
                issues = _object_issues(record, cutoff, known_at=knowledge)
                # Retained revisions independently bind effective/recorded time even when
                # the ObjectType has no timestamp property.
                issues.discard("object_time_missing")
                reasons.update(issues)
                if not issues:
                    eligible_objects.append(record)
            object_ids = {record.id for record in eligible_objects}
            eligible_links = []
            for link in selected_links:
                if not {link.from_id, link.to_id} <= selected_ids:
                    continue
                issues = _link_issues(
                    link, cutoff, None, known_at=knowledge, generations=generations
                )
                reasons.update(issues)
                if not issues and {link.from_id, link.to_id} <= object_ids:
                    eligible_links.append(link)
            reached, caps = _reachable_ids(object_ids, tuple(eligible_links), root_ids, limits)
            reasons.update(caps)
            if not set(root_ids) <= reached:
                reasons.add("historical_root_missing")
            snapshot = OntologyGraphSnapshot(
                objects=tuple(
                    sorted(
                        (record for record in eligible_objects if record.id in reached),
                        key=lambda record: record.id,
                    )
                ),
                links=tuple(
                    link for link in eligible_links if {link.from_id, link.to_id} <= reached
                ),
                truncated=bool(caps or selected_caps),
                source_complete=view.complete and not reasons,
                source_generation=view.digest,
                source_incomplete_reason="historical_evidence_incomplete" if reasons else None,
            )
            returned_bytes = len(_encoded_graph(snapshot)) + len(
                _encode(
                    {
                        "source_evidence_refs": view.evidence_refs,
                        "provider_generation_refs": view.provider_generation_refs,
                    }
                )
            )
            if returned_bytes > limits.max_bytes:
                raise ValueError("historical causal graph exceeds max_bytes")
            revision = hashlib.sha256(
                _encode(
                    {
                        "incident_id": incident_id,
                        "roots": sorted(set(root_ids)),
                        "link_types": sorted(set(link_types)),
                        "bounds": asdict(limits),
                        "release": view.ontology_release_digests,
                        "source_digest": view.digest,
                        "retained_input_digest": hashlib.sha256(
                            _encode(
                                {
                                    "batches": [
                                        asdict(
                                            replace(
                                                batch,
                                                object_revisions=tuple(
                                                    sorted(
                                                        batch.object_revisions,
                                                        key=lambda item: (
                                                            item.object_id,
                                                            item.effective_at,
                                                            item.properties_json,
                                                        ),
                                                    )
                                                ),
                                                link_revisions=tuple(
                                                    sorted(
                                                        batch.link_revisions,
                                                        key=lambda item: (
                                                            item.key,
                                                            item.effective_at,
                                                            item.properties_json,
                                                        ),
                                                    )
                                                ),
                                            )
                                        )
                                        for batch in sorted(
                                            conflict_batches,
                                            key=lambda item: (item.recorded_at, item.revision_id),
                                        )
                                    ],
                                }
                            )
                        ).hexdigest(),
                        "snapshot_digest": hashlib.sha256(_encoded_graph(snapshot)).hexdigest(),
                        "cutoff": cutoff,
                        "known_at": knowledge,
                        "reasons": sorted(reasons),
                    }
                )
            ).hexdigest()
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError(
                    "historical incident graph materialization exceeded its deadline"
                )
            return CausalIncidentGraph(
                incident_id=incident_id,
                evidence_cutoff=cutoff,
                graph_revision=revision,
                snapshot=snapshot,
                incomplete_reasons=tuple(sorted(reasons)),
                known_at=knowledge,
                source_evidence_refs=view.evidence_refs,
                provider_generation_refs=view.provider_generation_refs,
                active_provider_generation=(
                    active_batch.provider_generation_ref if active_batch is not None else None
                ),
            )
