"""Bounded object-set execution over the ontology store."""

from __future__ import annotations

from fdai.shared.providers.ontology_instance import OntologyInstanceStore

from .interfaces import CompiledInterfaceCatalog
from .models import (
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
)


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
        if definition.traversal is not None:
            graph = await self._store.traverse(
                root_ids=definition.root_ids,
                link_types=definition.traversal.link_types,
                direction=definition.traversal.direction,
                max_depth=definition.traversal.max_depth,
                limit=definition.limit,
            )
            selected = tuple(
                item for item in graph.objects if item.object_type in set(concrete_types)
            )
            graph = graph.__class__(objects=selected, links=graph.links, truncated=graph.truncated)
        else:
            filters = {item.property: item.equals for item in definition.predicates}
            if len(filters) != len(definition.predicates):
                raise ValueError("object-set predicates MUST name unique properties")
            graph = await self._store.query_objects(
                object_types=concrete_types,
                property_equals=filters,
                limit=definition.limit,
            )
        return ObjectSetMaterialization(
            definition=definition,
            graph=graph,
            concrete_types=concrete_types,
            truncated=graph.truncated,
            truncation_reason="result_limit" if graph.truncated else None,
        )

    def _resolve_types(self, definition: ObjectSetDefinition) -> tuple[str, ...]:
        selector = definition.selector
        if selector.kind is ObjectSelectorKind.INTERFACE:
            return self._interfaces.resolve(selector.name)
        if selector.name not in self._object_type_names:
            raise ValueError(f"unknown ontology ObjectType {selector.name!r}")
        return (selector.name,)


__all__ = ["ObjectSetService"]
