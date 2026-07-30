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
    can_repeat_link,
    normalize_json_value,
    normalize_link_record,
    normalize_object_record,
    ontology_link_sort_key,
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
        record = normalize_object_record(record)
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
        record = normalize_link_record(record)
        validate_link_record(
            record,
            link_types=self._link_types,
            objects=self._objects,
            existing_links=tuple(self._links.values()),
        )
        self._links[(record.from_id, record.link_type, record.to_id)] = record

    async def replace_subgraph(
        self,
        *,
        objects: Sequence[OntologyObjectRecord],
        links: Sequence[OntologyLinkRecord],
        previous_object_ids: Sequence[str] = (),
        previous_link_keys: Sequence[tuple[str, str, str]] = (),
    ) -> None:
        normalized_objects = tuple(normalize_object_record(item) for item in objects)
        normalized_links = tuple(normalize_link_record(item) for item in links)
        if len({item.id for item in normalized_objects}) != len(normalized_objects):
            raise OntologyInstanceValidationError("replacement object ids MUST be unique")
        working_objects = dict(self._objects)
        working_links = dict(self._links)
        desired_ids = {item.id for item in normalized_objects}
        for object_id in set(previous_object_ids) - desired_ids:
            working_objects.pop(object_id, None)
            working_links = {
                key: link
                for key, link in working_links.items()
                if link.from_id != object_id and link.to_id != object_id
            }
        for key in previous_link_keys:
            working_links.pop(key, None)
        for object_record in normalized_objects:
            validate_object_record(object_record, self._object_types)
            existing = working_objects.get(object_record.id)
            if existing is not None and existing.object_type != object_record.object_type:
                raise OntologyInstanceValidationError(
                    f"ontology object {object_record.id!r} cannot change type "
                    f"from {existing.object_type} to {object_record.object_type}"
                )
            revision = existing.revision + 1 if existing is not None else 1
            working_objects[object_record.id] = replace(object_record, revision=revision)
        for link_record in normalized_links:
            validate_link_record(
                link_record,
                link_types=self._link_types,
                objects=working_objects,
                existing_links=tuple(working_links.values()),
            )
            working_links[(link_record.from_id, link_record.link_type, link_record.to_id)] = (
                link_record
            )
        self._objects = working_objects
        self._links = working_links

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
        return self._objects.get(object_id)

    async def delete_object(self, object_id: str) -> bool:
        existing = self._objects.pop(object_id, None)
        if existing is None:
            return False
        self._links = {
            key: link
            for key, link in self._links.items()
            if link.from_id != object_id and link.to_id != object_id
        }
        return True

    async def query_objects(
        self,
        *,
        object_types: Sequence[str] = (),
        property_equals: Mapping[str, Any] | None = None,
        limit: int = 100,
    ) -> OntologyGraphSnapshot:
        _validate_limit(limit)
        selected_types = set(object_types)
        filters = normalize_json_value(property_equals or {}, path="property_equals")
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
        queue: deque[tuple[str, int, str | None]] = deque(
            (root_id, 0, None) for root_id in root_ids if root_id in self._objects
        )
        visited: set[str] = set()
        expanded: set[tuple[str, str | None]] = set()
        included_links: dict[tuple[str, str, str], OntologyLinkRecord] = {}
        truncated = False
        while queue:
            object_id, depth, previous_link_type = queue.popleft()
            state = (object_id, previous_link_type)
            if state in expanded:
                continue
            expanded.add(state)
            if object_id not in visited and len(visited) >= limit:
                truncated = True
                break
            visited.add(object_id)
            if depth >= max_depth:
                continue
            for key, link in sorted(self._links.items()):
                if allowed_links and link.link_type not in allowed_links:
                    continue
                declaration = self._link_types[link.link_type]
                if not can_repeat_link(previous_link_type, declaration):
                    continue
                next_id: str | None = None
                if direction in {"outgoing", "both"} and link.from_id == object_id:
                    next_id = link.to_id
                elif direction in {"incoming", "both"} and link.to_id == object_id:
                    next_id = link.from_id
                if next_id is not None:
                    included_links[key] = link
                    queue.append((next_id, depth + 1, link.link_type))
        objects = tuple(self._objects[identifier] for identifier in sorted(visited))
        links = tuple(
            sorted(
                included_links.values(),
                key=lambda link: ontology_link_sort_key(
                    link,
                    link_types=self._link_types,
                    objects=self._objects,
                ),
            )
        )
        links = tuple(link for link in links if link.from_id in visited and link.to_id in visited)
        return OntologyGraphSnapshot(objects=objects, links=links, truncated=truncated)


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= 1000:
        raise ValueError("limit MUST be in [1, 1000]")


__all__ = ["InMemoryOntologyInstanceStore"]
