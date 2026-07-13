"""In-memory reference implementation of the runtime ontology graph."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from fdai.shared.contracts.models import OntologyLinkType, OntologyObjectType
from fdai.shared.providers.ontology_instance import (
    OntologyDirection,
    OntologyGraphSnapshot,
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
    validate_link_record,
    validate_object_record,
)


class InMemoryOntologyInstanceStore:
    """Deterministic ontology store for tests and local development."""

    def __init__(
        self,
        *,
        object_types: Sequence[OntologyObjectType],
        link_types: Sequence[OntologyLinkType],
    ) -> None:
        self._object_types = {item.name: item for item in object_types}
        self._link_types = {item.name: item for item in link_types}
        self._objects: dict[str, OntologyObjectRecord] = {}
        self._links: dict[tuple[str, str, str], OntologyLinkRecord] = {}

    async def upsert_object(
        self,
        record: OntologyObjectRecord,
        *,
        expected_revision: int | None = None,
    ) -> OntologyObjectRecord:
        validate_object_record(record, self._object_types)
        existing = self._objects.get(record.id)
        current_revision = existing.revision if existing is not None else 0
        if expected_revision is not None and expected_revision != current_revision:
            raise OntologyInstanceValidationError(
                f"ontology object {record.id!r} revision mismatch: "
                f"expected {expected_revision}, current {current_revision}"
            )
        if existing is not None and existing.object_type != record.object_type:
            raise OntologyInstanceValidationError(
                f"ontology object {record.id!r} cannot change type "
                f"from {existing.object_type} to {record.object_type}"
            )
        stored = replace(record, revision=current_revision + 1)
        self._objects[stored.id] = stored
        return stored

    async def upsert_link(self, record: OntologyLinkRecord) -> None:
        validate_link_record(record, link_types=self._link_types, objects=self._objects)
        self._links[(record.from_id, record.link_type, record.to_id)] = record

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
        return self._objects.get(object_id)

    async def query_objects(
        self,
        *,
        object_types: Sequence[str] = (),
        property_equals: Mapping[str, Any] | None = None,
        limit: int = 100,
    ) -> OntologyGraphSnapshot:
        _validate_limit(limit)
        selected_types = set(object_types)
        filters = property_equals or {}
        matches = [
            item
            for item in sorted(self._objects.values(), key=lambda value: value.id)
            if (not selected_types or item.object_type in selected_types)
            and all(item.properties.get(key) == value for key, value in filters.items())
        ]
        truncated = len(matches) > limit
        objects = tuple(matches[:limit])
        identifiers = {item.id for item in objects}
        links = tuple(
            link
            for _, link in sorted(self._links.items())
            if link.from_id in identifiers and link.to_id in identifiers
        )
        return OntologyGraphSnapshot(objects=objects, links=links, truncated=truncated)

    async def traverse(
        self,
        *,
        root_ids: Sequence[str],
        link_types: Sequence[str] = (),
        direction: OntologyDirection = "outgoing",
        max_depth: int = 1,
        limit: int = 500,
    ) -> OntologyGraphSnapshot:
        _validate_limit(limit)
        if not 1 <= max_depth <= 5:
            raise ValueError("max_depth MUST be in [1, 5]")
        if direction not in {"outgoing", "incoming", "both"}:
            raise ValueError("direction MUST be outgoing, incoming, or both")
        allowed_links = set(link_types)
        queue = deque((root_id, 0) for root_id in root_ids if root_id in self._objects)
        visited: set[str] = set()
        included_links: dict[tuple[str, str, str], OntologyLinkRecord] = {}
        truncated = False
        while queue:
            object_id, depth = queue.popleft()
            if object_id in visited:
                continue
            if len(visited) >= limit:
                truncated = True
                break
            visited.add(object_id)
            if depth >= max_depth:
                continue
            for key, link in sorted(self._links.items()):
                if allowed_links and link.link_type not in allowed_links:
                    continue
                next_id: str | None = None
                if direction in {"outgoing", "both"} and link.from_id == object_id:
                    next_id = link.to_id
                elif direction in {"incoming", "both"} and link.to_id == object_id:
                    next_id = link.from_id
                if next_id is not None:
                    included_links[key] = link
                    queue.append((next_id, depth + 1))
        objects = tuple(self._objects[identifier] for identifier in sorted(visited))
        links = tuple(
            link
            for _, link in sorted(included_links.items())
            if link.from_id in visited and link.to_id in visited
        )
        return OntologyGraphSnapshot(objects=objects, links=links, truncated=truncated)


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= 1000:
        raise ValueError("limit MUST be in [1, 1000]")


__all__ = ["InMemoryOntologyInstanceStore"]
