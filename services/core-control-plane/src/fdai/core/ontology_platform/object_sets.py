"""Bounded object-set execution over the ontology store."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyInstanceStore,
    OntologyObjectRecord,
)

from .interfaces import CompiledInterfaceCatalog
from .models import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
    ObjectSetTruncationReason,
    OntologyInstancePathDefinition,
)

_STORE_QUERY_LIMIT = 1000
_EXACT_ID_BATCH_SIZE = 128


class ObjectSetService:
    def __init__(
        self,
        *,
        store: OntologyInstanceStore,
        interfaces: CompiledInterfaceCatalog,
        object_type_names: frozenset[str],
    ) -> None:
        self._store = store
        self._interfaces = interfaces
        self._object_type_names = object_type_names

    async def materialize(self, definition: ObjectSetDefinition) -> ObjectSetMaterialization:
        concrete_types = self._resolve_types(definition)
        source_truncation_reason: ObjectSetTruncationReason | None = None
        if definition.traversal is not None:
            graph = await self._store.traverse(
                root_ids=definition.root_ids,
                link_types=definition.traversal.link_types,
                direction=definition.traversal.direction,
                max_depth=definition.traversal.max_depth,
                limit=definition.limit,
            )
            if graph.truncated:
                source_truncation_reason = ObjectSetTruncationReason.TRAVERSAL_LIMIT
        else:
            exact_ids = _exact_id_values(definition.predicates)
            if exact_ids is not None:
                graph = await _query_exact_ids(
                    self._store,
                    object_types=concrete_types,
                    resource_ids=exact_ids,
                    predicates=definition.predicates,
                    limit=definition.limit,
                )
                source_truncation_reason = (
                    ObjectSetTruncationReason.RESULT_LIMIT if graph.truncated else None
                )
            else:
                graph = None
            filters = {
                item.property: item.equals
                for item in definition.predicates
                if item.operator is ObjectPredicateOperator.EQUALS
            }
            has_memory_predicates = len(filters) != len(definition.predicates)
            if graph is None:
                graph = await self._store.query_objects(
                    object_types=concrete_types,
                    property_equals=filters,
                    limit=_STORE_QUERY_LIMIT if has_memory_predicates else definition.limit,
                )
                if graph.truncated:
                    source_truncation_reason = (
                        ObjectSetTruncationReason.CANDIDATE_LIMIT
                        if has_memory_predicates
                        else ObjectSetTruncationReason.RESULT_LIMIT
                    )
        graph = cast(OntologyGraphSnapshot, graph)
        graph, result_limited = _filter_graph(
            graph,
            concrete_types=concrete_types,
            predicates=definition.predicates,
            limit=definition.limit,
        )
        truncation_reason = source_truncation_reason
        if truncation_reason is None and result_limited:
            truncation_reason = ObjectSetTruncationReason.RESULT_LIMIT
        return ObjectSetMaterialization(
            definition=definition,
            graph=graph,
            concrete_types=concrete_types,
            truncated=graph.truncated,
            truncation_reason=truncation_reason,
        )

    async def materialize_instance_path(
        self,
        definition: OntologyInstancePathDefinition,
    ) -> OntologyGraphSnapshot:
        """Read one bounded multi-type path candidate graph in a single store snapshot."""

        return await self._store.traverse_from_type(
            root_object_type=definition.root_selector.name,
            link_types=tuple(step.link_type for step in definition.steps),
            direction="both",
            max_depth=len(definition.steps),
            limit=_STORE_QUERY_LIMIT,
        )

    def _resolve_types(self, definition: ObjectSetDefinition) -> tuple[str, ...]:
        selector = definition.selector
        if selector.kind is ObjectSelectorKind.INTERFACE:
            return self._interfaces.resolve(selector.name)
        if selector.name not in self._object_type_names:
            raise ValueError(f"unknown ontology ObjectType {selector.name!r}")
        return (selector.name,)


def _exact_id_values(predicates: Sequence[ObjectPredicate]) -> tuple[str, ...] | None:
    """Return an exact id selector suitable for bounded per-id store reads."""
    for predicate in predicates:
        if predicate.property != "id":
            continue
        if predicate.operator is ObjectPredicateOperator.EQUALS and isinstance(
            predicate.equals, str
        ):
            return (predicate.equals,)
        if predicate.operator is ObjectPredicateOperator.IN:
            values = tuple(value for value in predicate.values if isinstance(value, str))
            if len(values) == len(predicate.values):
                return values
    return None


async def _query_exact_ids(
    store: OntologyInstanceStore,
    *,
    object_types: Sequence[str],
    resource_ids: Sequence[str],
    predicates: Sequence[ObjectPredicate],
    limit: int,
) -> OntologyGraphSnapshot:
    """Read selected ids in fixed-size store batches and stop after the result bound."""
    results: list[OntologyGraphSnapshot] = []
    matching_count = 0
    stopped_early = False
    for offset in range(0, len(resource_ids), _EXACT_ID_BATCH_SIZE):
        batch = resource_ids[offset : offset + _EXACT_ID_BATCH_SIZE]
        graph = await store.query_objects(
            object_types=object_types,
            object_ids=batch,
            limit=len(batch),
            include_relationships=False,
        )
        results.append(graph)
        matching_count += sum(
            item.object_type in object_types and _matches_all(item, predicates)
            for item in graph.objects
        )
        if matching_count > limit:
            stopped_early = offset + len(batch) < len(resource_ids)
            break
    objects = tuple(item for graph in results for item in graph.objects)
    generations = {
        graph.source_generation for graph in results if graph.source_generation is not None
    }
    if len(generations) > 1:
        raise ValueError("exact id reads returned mixed source generations")
    return OntologyGraphSnapshot(
        objects=objects,
        links=(),
        truncated=stopped_early or matching_count > limit,
        source_complete=all(graph.source_complete for graph in results),
        source_generation=next(iter(generations), None),
    )


def _filter_graph(
    graph: OntologyGraphSnapshot,
    *,
    concrete_types: Sequence[str],
    predicates: Sequence[ObjectPredicate],
    limit: int,
) -> tuple[OntologyGraphSnapshot, bool]:
    selected_types = set(concrete_types)
    matches = tuple(
        item
        for item in graph.objects
        if item.object_type in selected_types and _matches_all(item, predicates)
    )
    result_limited = len(matches) > limit
    truncated = graph.truncated or result_limited
    selected = matches[:limit]
    selected_ids = {item.id for item in selected}
    links = tuple(
        link for link in graph.links if link.from_id in selected_ids and link.to_id in selected_ids
    )
    return (
        OntologyGraphSnapshot(
            objects=selected,
            links=links,
            truncated=truncated,
            source_complete=graph.source_complete,
            source_generation=graph.source_generation,
        ),
        result_limited,
    )


def _matches_all(
    record: OntologyObjectRecord,
    predicates: Sequence[ObjectPredicate],
) -> bool:
    return all(_matches_predicate(record.properties, predicate) for predicate in predicates)


def _matches_predicate(properties: Mapping[str, Any], predicate: ObjectPredicate) -> bool:
    present = predicate.property in properties
    if predicate.operator is ObjectPredicateOperator.EXISTS:
        return present
    if predicate.operator is ObjectPredicateOperator.ABSENT:
        return not present
    if not present:
        return False

    value = properties[predicate.property]
    if predicate.operator is ObjectPredicateOperator.EQUALS:
        return _values_equal(value, predicate.equals)
    if predicate.operator is ObjectPredicateOperator.NOT_EQUALS:
        return not _values_equal(value, predicate.equals)
    if predicate.operator is ObjectPredicateOperator.IN:
        return any(_values_equal(value, candidate) for candidate in predicate.values)
    if predicate.operator is ObjectPredicateOperator.AT_LEAST:
        return _ordered_compare(value, predicate.equals, at_least=True)
    if predicate.operator is ObjectPredicateOperator.AT_MOST:
        return _ordered_compare(value, predicate.equals, at_least=False)
    return _contains(value, predicate.equals)


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    return bool(left == right)


def _ordered_compare(left: Any, right: Any, *, at_least: bool) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    try:
        return bool(left >= right if at_least else left <= right)
    except TypeError:
        return False


def _contains(container: Any, member: Any) -> bool:
    if not isinstance(container, (str, Mapping, Sequence)) or isinstance(
        container, (bytes, bytearray)
    ):
        return False
    try:
        return member in container
    except TypeError:
        return False


__all__ = ["ObjectSetService"]
