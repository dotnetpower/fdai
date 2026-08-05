"""Bounded, identity-safe Kubernetes custom owner evidence semantics."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final, NamedTuple

_DNS_SUBDOMAIN: Final = re.compile(
    r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*$"
)
_KIND: Final = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,127}$")
_UID: Final = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_BUILTIN_API_GROUPS: Final = frozenset(
    {
        "admissionregistration.k8s.io",
        "apiextensions.k8s.io",
        "apps",
        "autoscaling",
        "batch",
        "coordination.k8s.io",
        "discovery.k8s.io",
        "events.k8s.io",
        "extensions",
        "networking.k8s.io",
        "policy",
        "rbac.authorization.k8s.io",
        "scheduling.k8s.io",
        "storage.k8s.io",
    }
)


class CustomOwnerQuery(NamedTuple):
    resource: str
    expected_uid: str


def custom_owner_queries(
    resources: Sequence[Mapping[str, Any]],
    *,
    max_owners: int,
) -> tuple[tuple[CustomOwnerQuery, ...], int]:
    """Return bounded, deduplicated custom owner queries with immutable identity."""

    candidates: set[CustomOwnerQuery] = set()
    omitted = 0
    for resource in resources:
        if "owner_references" not in resource:
            continue
        if resource.get("owner_reference_projection_complete") is not True:
            omitted += 1
            continue
        for reference in _owner_references(resource):
            query = _custom_owner_query(reference)
            if query is None:
                omitted += 1
            else:
                candidates.add(query)
    ordered = tuple(sorted(candidates))
    return ordered[:max_owners], omitted + max(0, len(ordered) - max_owners)


def project_custom_owner(
    payload: Mapping[str, Any],
    *,
    namespace: str,
    query: CustomOwnerQuery,
) -> dict[str, Any] | None:
    """Project one exact custom owner only when its immutable UID still matches."""

    api_version = payload.get("apiVersion")
    kind = payload.get("kind")
    metadata = payload.get("metadata")
    if (
        not isinstance(api_version, str)
        or not _is_custom_api_version(api_version)
        or not isinstance(kind, str)
        or _KIND.fullmatch(kind) is None
        or not isinstance(metadata, Mapping)
    ):
        return None
    name = metadata.get("name")
    resource_namespace = metadata.get("namespace")
    uid = metadata.get("uid")
    expected_resource = _resource_query(api_version=api_version, kind=kind, name=name)
    if (
        resource_namespace != namespace
        or uid != query.expected_uid
        or expected_resource != query.resource
    ):
        return None
    status = payload.get("status")
    conditions = status.get("conditions") if isinstance(status, Mapping) else None
    return {
        "api_version": api_version[:128],
        "kind": kind[:128],
        "name": str(name)[:253],
        "namespace": namespace,
        "uid": query.expected_uid,
        "custom_resource": True,
        "resource_version": _text(metadata.get("resourceVersion"), 64),
        "generation": _nonnegative_int(metadata.get("generation")),
        "deleting": metadata.get("deletionTimestamp") is not None,
        "conditions": _project_conditions(conditions),
    }


def _owner_references(resource: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    references = resource.get("owner_references")
    return (
        [item for item in references if isinstance(item, Mapping)]
        if isinstance(references, list)
        else []
    )


def _custom_owner_query(value: Mapping[str, Any]) -> CustomOwnerQuery | None:
    api_version = value.get("api_version")
    kind = value.get("kind")
    name = value.get("name")
    uid = value.get("uid")
    resource = _resource_query(api_version=api_version, kind=kind, name=name)
    if resource is None or not isinstance(uid, str) or _UID.fullmatch(uid) is None:
        return None
    return CustomOwnerQuery(resource, uid)


def _resource_query(*, api_version: object, kind: object, name: object) -> str | None:
    if (
        not isinstance(api_version, str)
        or not _is_custom_api_version(api_version)
        or not isinstance(kind, str)
        or _KIND.fullmatch(kind) is None
        or not isinstance(name, str)
        or _DNS_SUBDOMAIN.fullmatch(name) is None
    ):
        return None
    group = api_version.split("/", maxsplit=1)[0]
    return f"{kind.casefold()}.{group}/{name}"


def _is_custom_api_version(value: str) -> bool:
    group, separator, version = value.partition("/")
    return (
        separator == "/"
        and bool(version)
        and len(value) <= 128
        and "." in group
        and group not in _BUILTIN_API_GROUPS
        and _DNS_SUBDOMAIN.fullmatch(group) is not None
    )


def _project_conditions(value: object) -> list[dict[str, str]]:
    conditions = value if isinstance(value, list) else []
    return [
        {
            "type": _text(condition.get("type"), 128),
            "status": _text(condition.get("status"), 32),
            "reason": _text(condition.get("reason"), 256),
        }
        for condition in conditions[-32:]
        if isinstance(condition, Mapping)
    ]


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _text(value: object, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


__all__ = ["CustomOwnerQuery", "custom_owner_queries", "project_custom_owner"]
