"""Bounded server-owned inventory result context for durable follow-ups."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Final

_SCHEMA_VERSION: Final = 1
_MAX_RESOURCES: Final = 40
_MAX_TEXT: Final = 1_024
_RESOURCE_FIELDS: Final = frozenset(
    {"name", "resource_type", "resource_group", "location", "status"}
)


def response_resource_result_context(
    view_context: Mapping[str, Any], *, verification_status: str
) -> dict[str, Any] | None:
    """Project one verified inventory result set into durable replay metadata."""

    if verification_status not in {"verified", "corrected"}:
        return None
    tool = view_context.get("_tool_evidence")
    if not isinstance(tool, Mapping) or tool.get("tool") != "query_inventory":
        return None
    result = tool.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "matched":
        return None
    if result.get("freshness") != "fresh":
        return None
    source = _bounded_text(result.get("source"))
    snapshot_at = _bounded_text(result.get("snapshot_at"))
    query = result.get("query")
    resources = result.get("resources")
    if (
        source is None
        or snapshot_at is None
        or not isinstance(query, Mapping)
        or not isinstance(resources, list)
        or not resources
    ):
        return None
    projected = tuple(
        resource
        for raw in resources[:_MAX_RESOURCES]
        if (resource := _project_resource(raw)) is not None
    )
    if not projected:
        return None
    canonical_query = json.dumps(
        dict(query),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    matched_count = result.get("matched_count")
    truncated = result.get("truncated") is True or (
        isinstance(matched_count, int) and matched_count > len(projected)
    )
    return {
        "schema_version": _SCHEMA_VERSION,
        "authority": str(tool.get("authority") or "server_inventory_graph"),
        "source": source,
        "snapshot_at": snapshot_at,
        "freshness": "fresh",
        "scope": str(query.get("scope") or "subscription"),
        "query_digest": hashlib.sha256(canonical_query.encode("utf-8")).hexdigest(),
        "evidence_ref": f"inventory:{source}@{snapshot_at}"[:_MAX_TEXT],
        "truncated": truncated,
        "resources": [dict(resource) for resource in projected],
    }


def parse_resource_result_context(raw: object) -> dict[str, Any] | None:
    """Parse replay-owned result context without accepting partial shapes."""

    if not isinstance(raw, Mapping) or raw.get("schema_version") != _SCHEMA_VERSION:
        return None
    required_text = (
        "authority",
        "source",
        "snapshot_at",
        "freshness",
        "scope",
        "query_digest",
        "evidence_ref",
    )
    text = {key: _bounded_text(raw.get(key)) for key in required_text}
    if any(value is None for value in text.values()):
        return None
    if text["freshness"] != "fresh" or text["scope"] not in {"active_view", "subscription"}:
        return None
    digest = text["query_digest"]
    if (
        digest is None
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        return None
    truncated = raw.get("truncated")
    resources = raw.get("resources")
    if not isinstance(truncated, bool) or not isinstance(resources, list):
        return None
    projected = tuple(
        resource
        for item in resources[:_MAX_RESOURCES]
        if (resource := _project_resource(item)) is not None
    )
    if not projected or len(projected) != len(resources):
        return None
    return {
        "schema_version": _SCHEMA_VERSION,
        **text,
        "truncated": truncated,
        "resources": [dict(resource) for resource in projected],
    }


def _project_resource(raw: object) -> dict[str, str] | None:
    if not isinstance(raw, Mapping):
        return None
    name = _bounded_text(raw.get("name"))
    resource_type = _bounded_text(raw.get("type") or raw.get("resource_type"))
    if name is None or resource_type is None:
        return None
    projected = {"name": name, "resource_type": resource_type}
    for key in _RESOURCE_FIELDS - {"name", "resource_type"}:
        value = _bounded_text(raw.get(key))
        if value is not None:
            projected[key] = value
    return projected


def _bounded_text(raw: object) -> str | None:
    return raw if isinstance(raw, str) and 0 < len(raw) <= _MAX_TEXT else None


__all__ = ["parse_resource_result_context", "response_resource_result_context"]
