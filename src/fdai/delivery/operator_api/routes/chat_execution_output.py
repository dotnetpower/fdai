"""Bounded JSON presentation for redacted conversational execution evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

MAX_EXECUTION_OUTPUT_CHARS: Final = 64 * 1024
_INVENTORY_RESULT_FIELDS: Final = (
    "status",
    "query",
    "requested_types",
    "status_groups",
    "resource_group",
    "name_filter",
    "provider_type_summary",
    "scope_counts",
    "state_coverage",
    "inventory_coverage",
    "inventory_coverage_complete",
    "inventory_checked_type_counts",
    "inventory_failed_type_count",
    "state_unavailable_resource_count",
    "state_unavailable_type_counts",
    "state_available_type_counts",
    "resource_group_count",
    "derived_resource_count",
    "snapshot_at",
    "freshness",
    "source",
    "active_view",
    "truncated",
    "total_resources",
    "matched_count",
    "type_counts",
    "matched_type_counts",
    "matched_location_counts",
    "matched_status_counts",
    "resources",
    "links",
    "coverage_gap",
    "state_history_requested",
)


def inventory_execution_output(result: Mapping[str, Any]) -> tuple[str, bool]:
    """Render a safe inventory projection without breaking JSON when bounded."""

    projection = {key: result[key] for key in _INVENTORY_RESULT_FIELDS if key in result}
    collections: dict[str, list[Any]] = {}
    for key in ("resources", "links"):
        value = projection.get(key)
        if isinstance(value, (list, tuple)):
            collections[key] = list(value)
            projection[key] = collections[key]
    original_counts = {key: len(value) for key, value in collections.items()}
    truncated = False
    while True:
        if truncated:
            projection["omitted"] = {
                key: original_counts[key] - len(value)
                for key, value in collections.items()
                if original_counts[key] > len(value)
            }
        try:
            output = json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True)
        except (TypeError, ValueError):
            break
        if len(output) <= MAX_EXECUTION_OUTPUT_CHARS:
            return output, truncated
        populated = [value for value in collections.values() if value]
        if not populated:
            break
        max(populated, key=len).pop()
        truncated = True
    fallback = {
        key: result[key]
        for key in ("status", "matched_count", "total_resources", "truncated")
        if key in result
    }
    fallback["detail_omitted"] = True
    return json.dumps(fallback, ensure_ascii=False, indent=2, sort_keys=True), True
