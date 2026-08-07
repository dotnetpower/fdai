"""Safe projection and deterministic rendering for inventory activity queries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from fdai.delivery.operator_api.application.conversation.capabilities.inventory.query import (
    InventoryQuery,
    InventoryQueryKind,
    inventory_query_matches,
)

MAX_ACTIVITY_EVENTS: Final = 200
_MAX_RENDERED_EVENTS: Final = 40


def project_inventory_activity(
    query: InventoryQuery,
    activity: Mapping[str, Any] | None,
    current_resources: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Project one bounded identity-free Activity Log collection."""

    base = {
        "query_source": query.source.value,
        "query_kind": query.kind.value,
        "query": query.to_dict(),
        "lookback_seconds": query.lookback_seconds,
    }
    if activity is None or activity.get("status") != "matched":
        return {
            **base,
            "status": "unavailable",
            "reason": (
                activity.get("reason")
                if isinstance(activity, Mapping)
                else "activity_provider_unavailable"
            ),
            "events": [],
        }
    raw_events = activity.get("events")
    if not isinstance(raw_events, (list, tuple)):
        return {
            **base,
            "status": "unavailable",
            "reason": "invalid_activity_payload",
            "events": [],
        }
    type_by_resource = {
        (
            str(item.get("name", "")).casefold(),
            str(item.get("resource_group", "")).casefold(),
        ): str(item.get("type"))
        for item in current_resources
        if item.get("name") and item.get("type")
    }
    events = [
        safe
        for item in raw_events[:MAX_ACTIVITY_EVENTS]
        if isinstance(item, Mapping)
        and (safe := _safe_activity_event(item, type_by_resource)) is not None
    ]
    matched = [item for item in events if inventory_query_matches(query, item)]
    matched.sort(key=lambda item: str(item["occurred_at"]), reverse=True)
    return {
        **base,
        "status": "matched",
        "source": _optional_text(activity.get("source")) or "azure-activity-log",
        "snapshot_at": _optional_text(activity.get("observed_at")),
        "freshness": "live",
        "truncated": bool(activity.get("truncated")) or len(raw_events) > MAX_ACTIVITY_EVENTS,
        "total_events": len(events),
        "matched_count": len(matched),
        "events": matched[:_MAX_RENDERED_EVENTS],
    }


def render_inventory_activity(result: Mapping[str, Any], *, korean: bool) -> str:
    """Render one projected activity collection without model inference."""

    if result.get("status") != "matched":
        return (
            "Azure Activity Log 근거를 사용할 수 없어 변경된 리소스를 확정하지 않았습니다."
            if korean
            else (
                "Azure Activity Log evidence is unavailable, so changed resources were not "
                "confirmed."
            )
        )
    count = int(result.get("matched_count", 0))
    total = int(result.get("total_events", 0))
    lookback = int(result.get("lookback_seconds") or 0)
    events = [item for item in result.get("events", ()) if isinstance(item, Mapping)]
    if korean:
        lines = [
            f"최근 {lookback}초 Azure Activity Log {total}건 중 "
            f"조건과 일치하는 변경은 {count}건입니다."
        ]
    else:
        lines = [
            f"{count} of {total} Azure Activity Log events in the last {lookback} seconds "
            "match the question."
        ]
    if result.get("query_kind") != InventoryQueryKind.COUNT.value:
        lines.extend(_activity_line(item, korean=korean) for item in events)
    source = str(result.get("source") or "azure-activity-log")
    observed_at = str(result.get("snapshot_at") or "unknown time")
    lines.append(f"{'근거' if korean else 'Evidence'}: {source}, observed {observed_at}.")
    if result.get("truncated"):
        lines.append(
            "Activity Log 결과가 잘렸으므로 일치하는 변경이 더 있을 수 있습니다."
            if korean
            else "The Activity Log result is truncated, so additional matching changes may exist."
        )
    return "\n".join(lines)


def _safe_activity_event(
    raw: Mapping[str, Any],
    type_by_resource: Mapping[tuple[str, str], str],
) -> dict[str, str] | None:
    occurred_at = _bounded_text(raw.get("occurred_at"), 64)
    operation = _bounded_text(raw.get("operation"), 256)
    event_status = _bounded_text(raw.get("event_status") or raw.get("status"), 64)
    if occurred_at is None or operation is None or event_status is None:
        return None
    name = _bounded_text(raw.get("name") or raw.get("resource_name"), 128) or "unknown"
    resource_group = _bounded_text(raw.get("resource_group"), 128)
    resource_type = _bounded_text(raw.get("type") or raw.get("resource_type"), 128)
    if resource_type is None:
        resource_type = type_by_resource.get(
            (name.casefold(), (resource_group or "").casefold()),
            "arm-resource",
        )
    event = {
        "occurred_at": occurred_at,
        "operation": operation,
        "event_status": event_status,
        "name": name,
        "type": resource_type,
    }
    if resource_group is not None:
        event["resource_group"] = resource_group
    return event


def _activity_line(event: Mapping[str, Any], *, korean: bool) -> str:
    prefix = "변경" if korean else "Change"
    details = [
        str(event.get("type")),
        str(event.get("operation")),
        str(event.get("event_status")),
    ]
    if event.get("resource_group"):
        details.append(f"resource group {event['resource_group']}")
    return f"- {prefix} {event.get('occurred_at')} {event.get('name')}: " + ", ".join(details)


def _optional_text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _bounded_text(value: Any, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.strip().split())
    return text if text and len(text) <= maximum else None


__all__ = ["MAX_ACTIVITY_EVENTS", "project_inventory_activity", "render_inventory_activity"]
