"""Validated taxonomy over exact cloud-provider-neutral ResourceType ids."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Annotated, Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from .resource_type import ResourceTypeRegistry

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "resource_classes.schema.json"
_MAX_MEMBERSHIPS = 256
_MAX_SPECIALIZATIONS = 256
_MAX_SPECIALIZATION_DEPTH = 8


class ResourceClassEntry(BaseModel):
    """One reviewed taxonomic class with explicit members and broader classes."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    id: Annotated[
        str,
        Field(pattern=r"^class\.[a-z][a-z0-9-]{0,57}$", max_length=64),
    ]
    description: Annotated[str, Field(min_length=1, max_length=512)]
    members: tuple[str, ...] = ()
    specializes: tuple[str, ...] = ()


class ResourceClassRegistry(BaseModel):
    """Immutable acyclic class graph resolved only from reviewed references."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    classes: tuple[ResourceClassEntry, ...]

    def __iter__(self) -> Iterator[ResourceClassEntry]:  # type: ignore[override]
        return iter(self.classes)

    def get(self, class_id: str) -> ResourceClassEntry:
        """Return one exact class or raise for an unknown id."""

        for entry in self.classes:
            if entry.id == class_id:
                return entry
        raise KeyError(class_id)

    @property
    def content_digest(self) -> str:
        """Return the canonical digest of this exact reviewed taxonomy."""

        canonical = json.dumps(
            self.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(canonical).hexdigest()

    def closure(self, class_id: str) -> tuple[str, ...]:
        """Return exact ResourceType members of one class and every specialization."""

        by_id = {entry.id: entry for entry in self.classes}
        included = self.class_closure(class_id)
        return tuple(
            sorted({member for candidate_id in included for member in by_id[candidate_id].members})
        )

    def class_closure(self, class_id: str) -> tuple[str, ...]:
        """Return the requested class and every explicit narrower class."""

        self.get(class_id)
        by_id = {entry.id: entry for entry in self.classes}
        return tuple(
            sorted(
                candidate.id
                for candidate in self.classes
                if _specializes(candidate.id, class_id, by_id, set())
            )
        )


@dataclass(frozen=True, slots=True)
class ResourceClassIssue:
    key: str
    message: str


class ResourceClassRegistryError(ValueError):
    """Aggregate every structural error in one catalog review."""

    def __init__(self, issues: list[ResourceClassIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{item.key}: {item.message}" for item in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"resource-class registry validation failed: {preview}{suffix}")


def load_resource_class_registry_from_mapping(
    raw: Mapping[str, Any],
    *,
    resource_types: ResourceTypeRegistry,
) -> ResourceClassRegistry:
    """Validate one taxonomy against its schema and exact ResourceType registry."""

    issues: list[ResourceClassIssue] = []
    schema = json.loads(
        resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    )
    schema_id = schema.get("$id")
    bundled_version = schema_id.rsplit("/", 1)[-1] if isinstance(schema_id, str) else ""
    if raw.get("schema_version") != bundled_version:
        issues.append(
            ResourceClassIssue(
                key="schema_version",
                message=f"must match bundled schema version {bundled_version!r}",
            )
        )
    for error in sorted(
        Draft202012Validator(schema).iter_errors(dict(raw)),
        key=lambda item: list(item.path),
    ):
        path = ".".join(str(part) for part in error.absolute_path) or "<root>"
        issues.append(ResourceClassIssue(key=path, message=error.message))

    raw_classes = raw.get("classes")
    if isinstance(raw_classes, list):
        class_rows = [item for item in raw_classes if isinstance(item, Mapping)]
        class_ids = [str(item["id"]) for item in class_rows if isinstance(item.get("id"), str)]
        known_classes = set(class_ids)
        known_types = resource_types.ids()
        for class_id in sorted({item for item in class_ids if class_ids.count(item) > 1}):
            issues.append(ResourceClassIssue(f"classes[id={class_id}]", "duplicate class id"))
        graph: dict[str, tuple[str, ...]] = {}
        direct_members: dict[str, tuple[str, ...]] = {}
        for item in class_rows:
            raw_class_id = item.get("id")
            if not isinstance(raw_class_id, str):
                continue
            class_id = raw_class_id
            parents = tuple(
                value for value in item.get("specializes", ()) if isinstance(value, str)
            )
            members = tuple(value for value in item.get("members", ()) if isinstance(value, str))
            graph[class_id] = parents
            direct_members[class_id] = members
            for member in sorted({value for value in members if members.count(value) > 1}):
                issues.append(
                    ResourceClassIssue(
                        f"classes[id={class_id}].members",
                        f"duplicate ResourceType member {member!r}",
                    )
                )
            for parent in parents:
                if parent == class_id:
                    issues.append(
                        ResourceClassIssue(
                            f"classes[id={class_id}].specializes",
                            "class cannot specialize itself",
                        )
                    )
                elif parent not in known_classes:
                    issues.append(
                        ResourceClassIssue(
                            f"classes[id={class_id}].specializes",
                            f"unknown ResourceClass {parent!r}",
                        )
                    )
            for member in members:
                if member not in known_types:
                    issues.append(
                        ResourceClassIssue(
                            f"classes[id={class_id}].members",
                            f"unknown ResourceType {member!r}",
                        )
                    )
        membership_count = sum(len(members) for members in direct_members.values())
        if membership_count > _MAX_MEMBERSHIPS:
            issues.append(
                ResourceClassIssue(
                    "classes.members",
                    f"total memberships exceed {_MAX_MEMBERSHIPS}",
                )
            )
        specialization_count = sum(len(parents) for parents in graph.values())
        if specialization_count > _MAX_SPECIALIZATIONS:
            issues.append(
                ResourceClassIssue(
                    "classes.specializes",
                    f"total specializations exceed {_MAX_SPECIALIZATIONS}",
                )
            )
        cycle = _find_cycle(graph)
        if cycle:
            issues.append(
                ResourceClassIssue(
                    "classes.specializes",
                    f"specialization cycle detected: {' -> '.join(cycle)}",
                )
            )
        elif _specialization_depth(graph) > _MAX_SPECIALIZATION_DEPTH:
            issues.append(
                ResourceClassIssue(
                    "classes.specializes",
                    f"specialization depth exceeds {_MAX_SPECIALIZATION_DEPTH}",
                )
            )
        children = {parent for parents in graph.values() for parent in parents}
        for class_id in sorted(known_classes):
            if not direct_members.get(class_id) and class_id not in children:
                issues.append(
                    ResourceClassIssue(
                        f"classes[id={class_id}]",
                        "class requires a direct member or specialization",
                    )
                )

    if issues:
        raise ResourceClassRegistryError(issues)
    try:
        return ResourceClassRegistry.model_validate(raw)
    except ValueError as exc:
        raise ResourceClassRegistryError([ResourceClassIssue("<root>", str(exc))]) from exc


def _find_cycle(graph: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    visited: set[str] = set()
    active: list[str] = []

    def visit(node: str) -> tuple[str, ...]:
        if node in active:
            start = active.index(node)
            return (*active[start:], node)
        if node in visited:
            return ()
        active.append(node)
        for parent in sorted(graph.get(node, ())):
            if cycle := visit(parent):
                return cycle
        active.pop()
        visited.add(node)
        return ()

    for node in sorted(graph):
        if cycle := visit(node):
            return cycle
    return ()


def _specialization_depth(graph: Mapping[str, tuple[str, ...]]) -> int:
    depths: dict[str, int] = {}

    def depth(node: str) -> int:
        if node not in depths:
            parents = graph.get(node, ())
            depths[node] = 0 if not parents else 1 + max(depth(parent) for parent in parents)
        return depths[node]

    return max((depth(node) for node in graph), default=0)


def _specializes(
    candidate_id: str,
    target_id: str,
    by_id: Mapping[str, ResourceClassEntry],
    visited: set[str],
) -> bool:
    if candidate_id == target_id:
        return True
    if candidate_id in visited:
        return False
    next_visited = {*visited, candidate_id}
    return any(
        _specializes(parent_id, target_id, by_id, next_visited)
        for parent_id in by_id[candidate_id].specializes
    )


__all__ = [
    "ResourceClassEntry",
    "ResourceClassRegistry",
    "ResourceClassRegistryError",
    "load_resource_class_registry_from_mapping",
]
