"""Pure graph-generation comparator for ontology direction migration review."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable

from .models import (
    ComparisonBounds,
    ComparisonDisposition,
    DirectionGraphGeneration,
    DirectionShadowReceipt,
    LinkRef,
    LinkReversal,
    QueryResultDelta,
    RebuildPointer,
    ReviewReason,
)

_Direction = str
_Adjacency = dict[tuple[str, str, _Direction], tuple[str, ...]]
_DEFAULT_BOUNDS = ComparisonBounds()


def compare_graph_generations(
    legacy: DirectionGraphGeneration,
    aligned: DirectionGraphGeneration,
    *,
    migration_revision: str,
    rebuild_pointer: RebuildPointer,
    bounds: ComparisonBounds = _DEFAULT_BOUNDS,
) -> DirectionShadowReceipt:
    """Compare two immutable generations without mutation or migration authority."""

    reasons = _generation_review_reasons(legacy, aligned)
    roots = tuple(sorted(set(legacy.object_ids) | set(aligned.object_ids)))
    if len(roots) > bounds.max_roots:
        roots = roots[: bounds.max_roots]
        reasons.add(ReviewReason.COMPARISON_TRUNCATED)

    legacy_adjacency = _adjacency(legacy)
    aligned_adjacency = _adjacency(aligned)
    added_links, removed_links, reversed_links = _link_differences(legacy, aligned)
    link_types = tuple(sorted({link.link_type for link in (*legacy.links, *aligned.links)}))

    directional = _directional_deltas(
        roots,
        link_types,
        legacy_adjacency,
        aligned_adjacency,
        bounds.traversal_depth,
    )
    contains = _single_relation_deltas(
        roots,
        query="contains_descendants",
        link_type="contains",
        direction="outgoing",
        legacy_adjacency=legacy_adjacency,
        aligned_adjacency=aligned_adjacency,
        depth=bounds.traversal_depth,
    )
    attached = _direct_relation_deltas(
        roots,
        query="attached_to_anchor",
        link_type="attached_to",
        direction="outgoing",
        legacy_adjacency=legacy_adjacency,
        aligned_adjacency=aligned_adjacency,
    )
    prerequisites = _single_relation_deltas(
        roots,
        query="depends_on_prerequisites",
        link_type="depends_on",
        direction="outgoing",
        legacy_adjacency=legacy_adjacency,
        aligned_adjacency=aligned_adjacency,
        depth=bounds.traversal_depth,
    )
    blast_radius = _blast_radius_deltas(
        roots,
        legacy_adjacency,
        aligned_adjacency,
        bounds.blast_radius_depth,
    )
    all_deltas = (*directional, *contains, *prerequisites, *blast_radius)
    if any(item.legacy_truncated or item.aligned_truncated for item in all_deltas):
        reasons.add(ReviewReason.COMPARISON_TRUNCATED)

    review_reasons = tuple(sorted(reasons, key=str))
    disposition = (
        ComparisonDisposition.REVIEW_REQUIRED if review_reasons else ComparisonDisposition.COMPLETE
    )
    return DirectionShadowReceipt(
        schema_version="1.0.0",
        comparator_version="direction-shadow-comparator.v1",
        disposition=disposition,
        review_reasons=review_reasons,
        migration_revision=migration_revision,
        prior_release_digest=legacy.ontology_release_digest,
        aligned_release_digest=aligned.ontology_release_digest,
        legacy_generation_digest=legacy.generation_digest,
        aligned_generation_digest=aligned.generation_digest,
        bounds=bounds,
        added_links=added_links,
        removed_links=removed_links,
        reversed_links=reversed_links,
        directional_query_deltas=directional,
        contains_descendant_deltas=contains,
        attached_anchor_deltas=attached,
        depends_prerequisite_deltas=prerequisites,
        blast_radius_deltas=blast_radius,
        blast_radius_policy="contains_outgoing+depends_on_incoming.v1",
        rebuild_pointer=rebuild_pointer,
        migration_ready=False,
        graph_mutation_authority=False,
        migration_execution_authority=False,
    )


def replay_matches(
    receipt: DirectionShadowReceipt,
    legacy: DirectionGraphGeneration,
    aligned: DirectionGraphGeneration,
) -> bool:
    """Recompute a receipt from its pinned inputs and compare exact content identity."""

    replayed = compare_graph_generations(
        legacy,
        aligned,
        migration_revision=receipt.migration_revision,
        rebuild_pointer=receipt.rebuild_pointer,
        bounds=receipt.bounds,
    )
    return replayed == receipt


def _generation_review_reasons(
    legacy: DirectionGraphGeneration,
    aligned: DirectionGraphGeneration,
) -> set[ReviewReason]:
    reasons: set[ReviewReason] = set()
    checks = (
        (
            legacy.ontology_release_digest is None,
            ReviewReason.LEGACY_RELEASE_UNBOUND,
        ),
        (
            aligned.ontology_release_digest is None,
            ReviewReason.ALIGNED_RELEASE_UNBOUND,
        ),
        (not legacy.complete, ReviewReason.LEGACY_GENERATION_INCOMPLETE),
        (not aligned.complete, ReviewReason.ALIGNED_GENERATION_INCOMPLETE),
        (legacy.truncated, ReviewReason.LEGACY_GENERATION_TRUNCATED),
        (aligned.truncated, ReviewReason.ALIGNED_GENERATION_TRUNCATED),
        (bool(legacy.missing_endpoint_ids), ReviewReason.LEGACY_MISSING_ENDPOINT),
        (bool(aligned.missing_endpoint_ids), ReviewReason.ALIGNED_MISSING_ENDPOINT),
        (
            not legacy.link_evidence_verified,
            ReviewReason.LEGACY_LINK_EVIDENCE_UNVERIFIED,
        ),
        (
            not aligned.link_evidence_verified,
            ReviewReason.ALIGNED_LINK_EVIDENCE_UNVERIFIED,
        ),
    )
    reasons.update(reason for failed, reason in checks if failed)
    return reasons


def _link_differences(
    legacy: DirectionGraphGeneration,
    aligned: DirectionGraphGeneration,
) -> tuple[tuple[LinkRef, ...], tuple[LinkRef, ...], tuple[LinkReversal, ...]]:
    legacy_keys = {link.key for link in legacy.links}
    aligned_keys = {link.key for link in aligned.links}
    removed = legacy_keys - aligned_keys
    added = aligned_keys - legacy_keys
    reversals: list[LinkReversal] = []
    paired_removed: set[tuple[str, str, str]] = set()
    paired_added: set[tuple[str, str, str]] = set()
    for link_type, from_id, to_id in sorted(removed):
        reverse = (link_type, to_id, from_id)
        if reverse not in added:
            continue
        paired_removed.add((link_type, from_id, to_id))
        paired_added.add(reverse)
        reversals.append(
            LinkReversal(
                legacy=LinkRef(link_type=link_type, from_id=from_id, to_id=to_id),
                aligned=LinkRef(link_type=link_type, from_id=to_id, to_id=from_id),
            )
        )
    added_refs = tuple(_link_ref(key) for key in sorted(added - paired_added))
    removed_refs = tuple(_link_ref(key) for key in sorted(removed - paired_removed))
    return added_refs, removed_refs, tuple(reversals)


def _directional_deltas(
    roots: tuple[str, ...],
    link_types: tuple[str, ...],
    legacy_adjacency: _Adjacency,
    aligned_adjacency: _Adjacency,
    depth: int,
) -> tuple[QueryResultDelta, ...]:
    deltas: list[QueryResultDelta] = []
    for root_id in roots:
        for link_type in link_types:
            for direction in ("incoming", "outgoing"):
                delta = _walk_delta(
                    query=f"traversal:{link_type}:{direction}",
                    root_id=root_id,
                    legacy_result=_walk(legacy_adjacency, root_id, link_type, direction, depth),
                    aligned_result=_walk(aligned_adjacency, root_id, link_type, direction, depth),
                )
                if delta is not None:
                    deltas.append(delta)
    return tuple(deltas)


def _single_relation_deltas(
    roots: tuple[str, ...],
    *,
    query: str,
    link_type: str,
    direction: _Direction,
    legacy_adjacency: _Adjacency,
    aligned_adjacency: _Adjacency,
    depth: int,
) -> tuple[QueryResultDelta, ...]:
    deltas = (
        _walk_delta(
            query=query,
            root_id=root_id,
            legacy_result=_walk(legacy_adjacency, root_id, link_type, direction, depth),
            aligned_result=_walk(aligned_adjacency, root_id, link_type, direction, depth),
        )
        for root_id in roots
    )
    return tuple(delta for delta in deltas if delta is not None)


def _direct_relation_deltas(
    roots: tuple[str, ...],
    *,
    query: str,
    link_type: str,
    direction: _Direction,
    legacy_adjacency: _Adjacency,
    aligned_adjacency: _Adjacency,
) -> tuple[QueryResultDelta, ...]:
    result: list[QueryResultDelta] = []
    for root_id in roots:
        legacy_ids = legacy_adjacency.get((link_type, root_id, direction), ())
        aligned_ids = aligned_adjacency.get((link_type, root_id, direction), ())
        delta = _result_delta(query, root_id, legacy_ids, aligned_ids, False, False)
        if delta is not None:
            result.append(delta)
    return tuple(result)


def _blast_radius_deltas(
    roots: tuple[str, ...],
    legacy_adjacency: _Adjacency,
    aligned_adjacency: _Adjacency,
    depth: int,
) -> tuple[QueryResultDelta, ...]:
    deltas = (
        _walk_delta(
            query="bounded_blast_radius",
            root_id=root_id,
            legacy_result=_blast_walk(legacy_adjacency, root_id, depth),
            aligned_result=_blast_walk(aligned_adjacency, root_id, depth),
        )
        for root_id in roots
    )
    return tuple(delta for delta in deltas if delta is not None)


def _walk_delta(
    *,
    query: str,
    root_id: str,
    legacy_result: tuple[tuple[str, ...], bool],
    aligned_result: tuple[tuple[str, ...], bool],
) -> QueryResultDelta | None:
    legacy_ids, legacy_truncated = legacy_result
    aligned_ids, aligned_truncated = aligned_result
    return _result_delta(
        query,
        root_id,
        legacy_ids,
        aligned_ids,
        legacy_truncated,
        aligned_truncated,
    )


def _result_delta(
    query: str,
    root_id: str,
    legacy_ids: tuple[str, ...],
    aligned_ids: tuple[str, ...],
    legacy_truncated: bool,
    aligned_truncated: bool,
) -> QueryResultDelta | None:
    if legacy_ids == aligned_ids and legacy_truncated == aligned_truncated and not legacy_truncated:
        return None
    return QueryResultDelta(
        query=query,
        root_id=root_id,
        legacy_ids=legacy_ids,
        aligned_ids=aligned_ids,
        added_ids=tuple(sorted(set(aligned_ids) - set(legacy_ids))),
        removed_ids=tuple(sorted(set(legacy_ids) - set(aligned_ids))),
        legacy_truncated=legacy_truncated,
        aligned_truncated=aligned_truncated,
    )


def _adjacency(generation: DirectionGraphGeneration) -> _Adjacency:
    values: defaultdict[tuple[str, str, _Direction], set[str]] = defaultdict(set)
    for link in generation.links:
        values[(link.link_type, link.from_id, "outgoing")].add(link.to_id)
        values[(link.link_type, link.to_id, "incoming")].add(link.from_id)
    return {key: tuple(sorted(targets)) for key, targets in values.items()}


def _walk(
    adjacency: _Adjacency,
    root_id: str,
    link_type: str,
    direction: _Direction,
    max_depth: int,
) -> tuple[tuple[str, ...], bool]:
    return _bounded_walk(
        root_id,
        max_depth,
        lambda node: adjacency.get((link_type, node, direction), ()),
    )


def _blast_walk(
    adjacency: _Adjacency,
    root_id: str,
    max_depth: int,
) -> tuple[tuple[str, ...], bool]:
    def neighbors(node: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                set(adjacency.get(("contains", node, "outgoing"), ()))
                | set(adjacency.get(("depends_on", node, "incoming"), ()))
            )
        )

    return _bounded_walk(root_id, max_depth, neighbors)


def _bounded_walk(
    root_id: str,
    max_depth: int,
    neighbors: Callable[[str], tuple[str, ...]],
) -> tuple[tuple[str, ...], bool]:
    seen = {root_id}
    reached: set[str] = set()
    queue: deque[tuple[str, int]] = deque(((root_id, 0),))
    truncated = False
    while queue:
        current, depth = queue.popleft()
        adjacent = neighbors(current)
        if depth >= max_depth:
            if any(item not in seen for item in adjacent):
                truncated = True
            continue
        for item in adjacent:
            if item in seen:
                continue
            seen.add(item)
            reached.add(item)
            queue.append((item, depth + 1))
    return tuple(sorted(reached)), truncated


def _link_ref(key: tuple[str, str, str]) -> LinkRef:
    link_type, from_id, to_id = key
    return LinkRef(link_type=link_type, from_id=from_id, to_id=to_id)


__all__ = ["compare_graph_generations", "replay_matches"]
