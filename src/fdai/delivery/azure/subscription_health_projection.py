"""Pure normalization helpers for Azure subscription health evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def service_health_events(
    events: Sequence[Mapping[str, Any]],
    impacts: Sequence[Mapping[str, Any]],
    *,
    subscription_scope: bool,
    max_impacts: int,
) -> tuple[list[dict[str, Any]], bool]:
    impacts_by_event: dict[str, list[Mapping[str, Any]]] = {}
    for impact in impacts[: max_impacts + 1]:
        tracking_id = str(impact.get("eventTrackingId") or "").strip().casefold()
        if tracking_id:
            impacts_by_event.setdefault(tracking_id, []).append(impact)
    normalized: list[dict[str, Any]] = []
    for event in events[:65]:
        tracking_id = str(event.get("trackingId") or "").strip()
        event_name = str(event.get("eventName") or "").strip()
        aliases = {value.casefold() for value in (tracking_id, event_name) if value}
        matched_impacts = [
            impact for alias in aliases for impact in impacts_by_event.get(alias, ())
        ]
        if not subscription_scope and not matched_impacts:
            continue
        impacted_resources: list[dict[str, str]] = []
        seen_resources: set[tuple[str, str, str]] = set()
        for impact in matched_impacts:
            name = bounded_text(impact.get("resourceName"))
            resource_group = bounded_text(impact.get("resourceGroup"))
            resource_type = bounded_text(impact.get("targetResourceType"))
            resource_key = (name.casefold(), resource_group.casefold(), resource_type.casefold())
            if resource_key in seen_resources:
                continue
            seen_resources.add(resource_key)
            impacted_resources.append(
                {
                    "name": name,
                    "resource_group": resource_group,
                    "resource_type": resource_type,
                    "region": bounded_text(impact.get("targetRegion")),
                    "status": bounded_text(impact.get("status")),
                }
            )
        normalized.append(
            {
                "event_type": bounded_text(event.get("eventType")),
                "status": bounded_text(event.get("status")),
                "level": bounded_text(event.get("level")),
                "title": bounded_text(event.get("title")),
                "impact_start_time": bounded_text(event.get("impactStartTime")),
                "impacted_resource_count": len(impacted_resources),
                "impacted_resources": impacted_resources[:64],
            }
        )
    return normalized[:64], len(events) > 64 or len(impacts) > max_impacts


def impacted_resource_count(events: Sequence[Mapping[str, Any]]) -> int:
    resources: set[tuple[str, str, str]] = set()
    for event in events:
        impacted = event.get("impacted_resources")
        if not isinstance(impacted, list):
            continue
        for resource in impacted:
            if not isinstance(resource, Mapping):
                continue
            resources.add(
                (
                    str(resource.get("name") or "").casefold(),
                    str(resource.get("resource_group") or "").casefold(),
                    str(resource.get("resource_type") or "").casefold(),
                )
            )
    return len(resources)


def valid_resource(value: Mapping[str, Any]) -> bool:
    return all(
        isinstance(value.get(key), str) and value.get(key)
        for key in ("id", "name", "type", "resourceGroup")
    )


def health_findings(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for row in rows:
        state = str(row.get("availabilityState") or "Unknown")
        if state.casefold() == "available":
            continue
        resource_id = row.get("targetResourceId")
        identity = resource_identity(resource_id if isinstance(resource_id, str) else "")
        resource_name = row.get("resourceName")
        findings.append(
            {
                "kind": "resource_health",
                "resource_name": str(resource_name or identity["name"] or "unknown"),
                "resource_type": identity["type"],
                "resource_group": identity["resource_group"],
                "status": state,
                "reason": str(row.get("reasonType") or "unknown"),
                "title": bounded_text(row.get("title")),
                "observed_at": str(row.get("occurredTime") or "unknown"),
            }
        )
    return findings


def health_history_events(
    health: Sequence[Mapping[str, Any]],
    annotations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in health:
        resource_id = row.get("targetResourceId")
        identity = resource_identity(resource_id if isinstance(resource_id, str) else "")
        events.append(
            {
                "kind": "availability_status",
                "resource_name": str(row.get("resourceName") or identity["name"] or "unknown"),
                "resource_type": identity["type"],
                "resource_group": identity["resource_group"],
                "status": str(row.get("availabilityState") or "Unknown"),
                "reason": str(row.get("reasonType") or "unknown"),
                "classification": health_event_classification(row.get("reasonType")),
                "title": bounded_text(row.get("title")),
                "observed_at": str(row.get("occurredTime") or "unknown"),
            }
        )
    for row in annotations:
        resource_id = row.get("targetResourceId")
        identity = resource_identity(resource_id if isinstance(resource_id, str) else "")
        events.append(
            {
                "kind": "resource_annotation",
                "resource_name": identity["name"] or "unknown",
                "resource_type": identity["type"],
                "resource_group": identity["resource_group"],
                "status": bounded_text(row.get("annotationName")),
                "reason": bounded_text(row.get("context") or row.get("reason")),
                "classification": health_event_classification(row.get("context")),
                "title": bounded_text(row.get("reason")),
                "observed_at": str(row.get("occurredTime") or "unknown"),
            }
        )
    return sorted(events, key=lambda event: event["observed_at"])[:64]


def health_event_classification(value: object) -> str:
    normalized = str(value or "").casefold()
    if "customer" in normalized:
        return "customer-initiated"
    if "platform" in normalized:
        return "platform-initiated"
    return "status-only"


def merge_health_annotations(
    health: Sequence[Mapping[str, Any]],
    annotations: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    reason_by_target: dict[str, str] = {}
    for annotation in annotations:
        target = annotation.get("targetResourceId")
        if not isinstance(target, str) or target.casefold() in reason_by_target:
            continue
        candidates = tuple(
            str(annotation.get(field) or "").strip()
            for field in ("context", "reason", "annotationName")
        )
        recognized = next(
            (
                "Customer Initiated" if "customer" in candidate.casefold() else "Platform Initiated"
                for candidate in candidates
                if "customer" in candidate.casefold() or "platform" in candidate.casefold()
            ),
            None,
        )
        fallback = next((candidate for candidate in candidates if candidate), None)
        if recognized or fallback:
            reason_by_target[target.casefold()] = recognized or fallback or "unknown"
    merged: list[Mapping[str, Any]] = []
    for row in health:
        reason = str(row.get("reasonType") or "").strip()
        target = str(row.get("targetResourceId") or "").casefold()
        if not reason or reason.casefold() == "unknown":
            reason = reason_by_target.get(target, reason or "unknown")
        merged.append({**row, "reasonType": reason})
    return merged


def resource_identity(resource_id: str) -> dict[str, str]:
    parts = [part for part in resource_id.strip("/").split("/") if part]
    folded = [part.casefold() for part in parts]
    group = ""
    if "resourcegroups" in folded:
        group_at = folded.index("resourcegroups")
        if group_at + 1 < len(parts):
            group = parts[group_at + 1]
    if "providers" not in folded:
        return {"name": "", "type": "", "resource_group": group}
    provider_at = folded.index("providers")
    provider_parts = parts[provider_at + 1 :]
    if len(provider_parts) < 3:
        return {"name": "", "type": "", "resource_group": group}
    namespace = provider_parts[0]
    type_parts = provider_parts[1::2]
    name_parts = provider_parts[2::2]
    return {
        "name": name_parts[-1] if name_parts else "",
        "type": "/".join((namespace, *type_parts)),
        "resource_group": group,
    }


def provisioning_findings(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    bad = {"failed", "canceled", "deleting"}
    return [
        {
            "kind": "provisioning",
            "resource_name": str(row["name"]),
            "resource_type": str(row["type"]),
            "resource_group": str(row["resourceGroup"]),
            "status": str(row.get("provisioningState") or "unknown"),
        }
        for row in rows
        if str(row.get("provisioningState") or "").casefold() in bad
    ]


def resource_state_findings(
    rows: Sequence[Mapping[str, Any]],
    requested_states: Sequence[str],
) -> list[dict[str, Any]]:
    requested = {state.casefold() for state in requested_states}
    findings: list[dict[str, Any]] = []
    for row in rows:
        observed = next(
            (
                str(row[field])
                for field in ("state", "status", "resourceState")
                if isinstance(row.get(field), str) and str(row[field]).strip()
            ),
            "",
        )
        if observed.casefold() not in requested:
            continue
        findings.append(
            {
                "kind": "resource_state",
                "resource_name": str(row["name"]),
                "resource_type": str(row["type"]),
                "resource_group": str(row["resourceGroup"]),
                "status": observed,
            }
        )
    return findings


def bounded_text(value: object) -> str:
    if not isinstance(value, str):
        return "unknown"
    return " ".join(value.split())[:128] or "unknown"


__all__ = [
    "bounded_text",
    "health_event_classification",
    "health_findings",
    "health_history_events",
    "impacted_resource_count",
    "merge_health_annotations",
    "provisioning_findings",
    "resource_identity",
    "resource_state_findings",
    "service_health_events",
    "valid_resource",
]
