"""Deterministic architecture views over a promoted inventory graph."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from fdai.shared.providers.inventory import InventoryGraphViewNotFoundError

DEFAULT_ARCHITECTURE_VIEW_ID = "fdai-control-plane"
SERVICE_TAG_KEYS = (
    "fdai:service",
    "service",
    "application",
    "app",
    "workload",
    "azd-service-name",
)
_SCOPE_TYPES = frozenset({"subscription", "resource-group"})
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class _View:
    id: str
    label: str
    kind: Literal["fdai", "service", "resource_group"]
    classification: Literal["ownership_tag", "service_tag", "resource_group_fallback"]
    resource_ids: frozenset[str]
    root_resource_id: str

    def manifest(self) -> dict[str, str]:
        descriptions = {
            "fdai": (
                "FDAI control-plane resources identified by ownership or reserved service tags"
            ),
            "service": "Resources grouped by an explicit service tag",
            "resource_group": (
                "Resources grouped by resource group because service identity is unavailable"
            ),
        }
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "classification": self.classification,
            "description": descriptions[self.kind],
            "root_resource_id": self.root_resource_id,
        }


@dataclass(frozen=True, slots=True)
class _ServiceTagResult:
    identity: tuple[str, str] | None
    ambiguous: bool = False


def project_architecture_graph(
    *,
    resources: Sequence[Mapping[str, Any]],
    links: Sequence[Mapping[str, Any]],
    requested_view: str | None,
) -> dict[str, Any]:
    """Partition inventory into the FDAI default, service, and RG fallback views."""

    by_id = {str(resource["id"]): resource for resource in resources}
    parent_by_id = _parent_index(resources, links)
    children_by_id: dict[str, set[str]] = defaultdict(set)
    for child_id, parent_id in parent_by_id.items():
        children_by_id[parent_id].add(child_id)

    directly_owned = {
        resource_id for resource_id, resource in by_id.items() if _is_fdai_owned(_tags(resource))
    }
    owned_ids = _descendants(directly_owned, children_by_id)
    fdai_ids = _with_ancestors(owned_ids, parent_by_id)

    service_members: dict[str, set[str]] = defaultdict(set)
    service_labels: dict[str, str] = {}
    fallback_members: dict[str, set[str]] = defaultdict(set)
    for resource_id, resource in by_id.items():
        if resource_id in owned_ids or str(resource.get("type")) in _SCOPE_TYPES:
            continue
        service = _inherited_service_identity(resource_id, by_id, parent_by_id)
        if service is not None:
            service_id, label = service
            service_members[service_id].add(resource_id)
            service_labels.setdefault(service_id, label)
            continue
        resource_group_id = _resource_group_ancestor(resource_id, by_id, parent_by_id)
        if resource_group_id is not None:
            fallback_members[resource_group_id].add(resource_id)

    views = [_fdai_view(fdai_ids, parent_by_id)]
    for service_id in sorted(service_members, key=lambda item: service_labels[item].casefold()):
        member_ids = _with_ancestors(service_members[service_id], parent_by_id)
        views.append(
            _View(
                id=service_id,
                label=service_labels[service_id],
                kind="service",
                classification="service_tag",
                resource_ids=frozenset(member_ids),
                root_resource_id=_root_id(member_ids, parent_by_id),
            )
        )
    for resource_group_id in sorted(
        fallback_members,
        key=lambda item: str(by_id[item].get("name") or item).casefold(),
    ):
        member_ids = _with_ancestors(fallback_members[resource_group_id], parent_by_id)
        views.append(
            _View(
                id=resource_group_id,
                label=str(by_id[resource_group_id].get("name") or resource_group_id),
                kind="resource_group",
                classification="resource_group_fallback",
                resource_ids=frozenset(member_ids),
                root_resource_id=resource_group_id,
            )
        )

    active_id = requested_view or DEFAULT_ARCHITECTURE_VIEW_ID
    active = next((view for view in views if view.id == active_id), None)
    if active is None:
        raise InventoryGraphViewNotFoundError(f"architecture view not found: {active_id}")
    selected_ids = active.resource_ids
    return {
        "active_view": active.id,
        "views": [view.manifest() for view in views],
        "resources": [
            {key: value for key, value in resource.items() if key != "props"}
            for resource in resources
            if str(resource["id"]) in selected_ids
        ],
        "links": [
            dict(link)
            for link in links
            if str(link["source"]) in selected_ids and str(link["target"]) in selected_ids
        ],
    }


def _fdai_view(resource_ids: set[str], parent_by_id: Mapping[str, str]) -> _View:
    return _View(
        id=DEFAULT_ARCHITECTURE_VIEW_ID,
        label="FDAI control plane",
        kind="fdai",
        classification="ownership_tag",
        resource_ids=frozenset(resource_ids),
        root_resource_id=_root_id(resource_ids, parent_by_id, default=DEFAULT_ARCHITECTURE_VIEW_ID),
    )


def _parent_index(
    resources: Sequence[Mapping[str, Any]], links: Sequence[Mapping[str, Any]]
) -> dict[str, str]:
    parents = {
        str(resource["id"]): str(resource["parent_id"])
        for resource in resources
        if resource.get("parent_id")
    }
    for link in links:
        if link.get("type") == "contains":
            parents.setdefault(str(link["target"]), str(link["source"]))
    return parents


def _tags(resource: Mapping[str, Any]) -> Mapping[str, Any]:
    props = resource.get("props")
    if not isinstance(props, Mapping):
        return {}
    tags = props.get("tags")
    return tags if isinstance(tags, Mapping) else {}


def _normalized_tags(tags: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(key).strip().casefold(): str(value).strip()
        for key, value in tags.items()
        if isinstance(value, (str, int, float, bool)) and str(value).strip()
    }


def _is_fdai_owned(tags: Mapping[str, Any]) -> bool:
    normalized = _normalized_tags(tags)
    ownership_pair = (
        normalized.get("fdai:managed", "").casefold() == "true"
        and normalized.get("fdai:workload", "").casefold() == "fdai"
    )
    service_result = _service_identity(tags)
    explicit_fdai_service = (
        not service_result.ambiguous
        and service_result.identity is not None
        and service_result.identity[1].casefold() == "fdai"
    )
    return ownership_pair or explicit_fdai_service


def _service_identity(tags: Mapping[str, Any]) -> _ServiceTagResult:
    normalized = _normalized_tags(tags)
    values = {
        normalized[key].strip().casefold(): normalized[key].strip()
        for key in SERVICE_TAG_KEYS
        if normalized.get(key, "").strip()
    }
    if not values:
        return _ServiceTagResult(identity=None)
    if len(values) != 1:
        return _ServiceTagResult(identity=None, ambiguous=True)
    label = next(iter(values.values()))
    slug = _SLUG_PATTERN.sub("-", label.casefold()).strip("-") or "service"
    digest = hashlib.sha256(label.casefold().encode("utf-8")).hexdigest()[:8]
    return _ServiceTagResult(identity=(f"service:{slug[:48]}-{digest}", label))


def _inherited_service_identity(
    resource_id: str,
    by_id: Mapping[str, Mapping[str, Any]],
    parent_by_id: Mapping[str, str],
) -> tuple[str, str] | None:
    current_id: str | None = resource_id
    visited: set[str] = set()
    while current_id is not None and current_id not in visited:
        visited.add(current_id)
        resource = by_id.get(current_id)
        if resource is None:
            return None
        result = _service_identity(_tags(resource))
        if result.ambiguous:
            return None
        if result.identity is not None:
            return result.identity
        current_id = parent_by_id.get(current_id)
    return None


def _resource_group_ancestor(
    resource_id: str,
    by_id: Mapping[str, Mapping[str, Any]],
    parent_by_id: Mapping[str, str],
) -> str | None:
    current_id: str | None = resource_id
    visited: set[str] = set()
    while current_id is not None and current_id not in visited:
        visited.add(current_id)
        resource = by_id.get(current_id)
        if resource is None:
            return None
        if resource.get("type") == "resource-group":
            return current_id
        current_id = parent_by_id.get(current_id)
    return None


def _descendants(root_ids: set[str], children_by_id: Mapping[str, set[str]]) -> set[str]:
    selected = set(root_ids)
    queue = deque(root_ids)
    while queue:
        parent_id = queue.popleft()
        for child_id in children_by_id.get(parent_id, set()):
            if child_id not in selected:
                selected.add(child_id)
                queue.append(child_id)
    return selected


def _with_ancestors(resource_ids: set[str], parent_by_id: Mapping[str, str]) -> set[str]:
    selected = set(resource_ids)
    for resource_id in tuple(resource_ids):
        current_id = resource_id
        visited: set[str] = set()
        while current_id in parent_by_id and current_id not in visited:
            visited.add(current_id)
            current_id = parent_by_id[current_id]
            selected.add(current_id)
    return selected


def _root_id(
    resource_ids: set[str],
    parent_by_id: Mapping[str, str],
    *,
    default: str = "",
) -> str:
    roots = sorted(
        resource_id
        for resource_id in resource_ids
        if parent_by_id.get(resource_id) not in resource_ids
    )
    return roots[0] if roots else default


__all__ = [
    "DEFAULT_ARCHITECTURE_VIEW_ID",
    "SERVICE_TAG_KEYS",
    "project_architecture_graph",
]
