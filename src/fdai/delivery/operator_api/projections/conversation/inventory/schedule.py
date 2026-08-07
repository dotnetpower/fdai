"""Deterministic projection and rendering for recurring VM shutdown schedules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fdai.delivery.inventory_schedule import VM_SHUTDOWN_SCHEDULE_TYPE
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.query import (
    InventoryQuery,
    InventoryScheduleWindow,
)


class ScheduledShutdownEvidenceError(ValueError):
    """Raised when schedule evidence cannot support a complete answer."""


def schedule_reference_is_current(
    query: InventoryQuery,
    now: datetime,
    *,
    maximum_skew_seconds: int = 300,
) -> bool:
    """Return whether a schedule query carries a current server-owned time anchor."""

    if query.reference_time is None or now.tzinfo is None:
        return False
    return abs((now.astimezone(UTC) - query.reference_time).total_seconds()) <= maximum_skew_seconds


def project_scheduled_shutdown_result(
    query: InventoryQuery,
    graph: Mapping[str, Any],
    resources: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Project enabled VM shutdown schedules inside the pinned local-time window."""

    if query.schedule_window is not InventoryScheduleWindow.TODAY_EVENING:
        raise ScheduledShutdownEvidenceError("scheduled shutdown window is unsupported")
    if query.reference_time is None:  # pragma: no cover - query contract enforces this
        raise ScheduledShutdownEvidenceError("scheduled shutdown reference time is unavailable")
    unavailable_reason = graph.get("unavailable_reason")
    if isinstance(unavailable_reason, str) and unavailable_reason:
        return {
            "status": "unavailable",
            "reason": unavailable_reason,
            "query": query.to_dict(),
        }
    if graph.get("freshness") != "fresh":
        return {
            "status": "unavailable",
            "reason": "fresh_inventory_required",
            "query": query.to_dict(),
        }
    if graph.get("truncated") is True:
        return {
            "status": "unavailable",
            "reason": "scheduled_shutdown_coverage_incomplete",
            "query": query.to_dict(),
        }
    coverage_value = graph.get("coverage")
    coverage = coverage_value if isinstance(coverage_value, Mapping) else None
    covered_types = coverage.get("resource_types") if coverage is not None else None
    if coverage is None:
        return {
            "status": "unavailable",
            "reason": "scheduled_shutdown_coverage_unavailable",
            "query": query.to_dict(),
        }
    if not isinstance(covered_types, (list, tuple)) and coverage is not None:
        return {
            "status": "unavailable",
            "reason": "scheduled_shutdown_coverage_unavailable",
            "query": query.to_dict(),
        }
    if isinstance(covered_types, (list, tuple)) and VM_SHUTDOWN_SCHEDULE_TYPE not in covered_types:
        return {
            "status": "unavailable",
            "reason": "scheduled_shutdown_coverage_unavailable",
            "query": query.to_dict(),
        }

    schedules = [item for item in resources if item.get("type") == VM_SHUTDOWN_SCHEDULE_TYPE]
    matched_targets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for schedule in schedules:
        status = schedule.get("scheduled_shutdown_status")
        if status == "Disabled":
            continue
        if status != "Enabled":
            raise ScheduledShutdownEvidenceError("scheduled shutdown status is invalid")
        shutdown_at = _scheduled_occurrence(query.reference_time, schedule)
        if shutdown_at is None:
            continue
        target_name = schedule.get("scheduled_shutdown_target_name")
        resource_group = schedule.get("scheduled_shutdown_target_resource_group")
        subscription_digest = schedule.get("scheduled_shutdown_target_subscription_digest")
        time_zone = schedule.get("scheduled_shutdown_time_zone")
        if (
            not isinstance(target_name, str)
            or not target_name
            or not isinstance(resource_group, str)
            or not resource_group
            or not isinstance(subscription_digest, str)
            or not subscription_digest
            or not isinstance(time_zone, str)
            or not time_zone
        ):
            raise ScheduledShutdownEvidenceError("scheduled shutdown target is invalid")
        if not subscription_digest.startswith("sha256:") or len(subscription_digest) != 71:
            raise ScheduledShutdownEvidenceError("scheduled shutdown target scope is invalid")
        projected = {
            "name": target_name,
            "type": "compute.vm",
            "provider_type": "Microsoft.Compute/virtualMachines",
            "status": "scheduled_shutdown",
            "resource_group": resource_group,
            "scheduled_shutdown_at": shutdown_at.isoformat(),
            "scheduled_shutdown_time_zone": time_zone,
        }
        identity = (subscription_digest, resource_group.casefold(), target_name.casefold())
        current = matched_targets.get(identity)
        if current is None or projected["scheduled_shutdown_at"] < current["scheduled_shutdown_at"]:
            matched_targets[identity] = projected
    matches = list(matched_targets.values())
    matches.sort(key=lambda item: (item["scheduled_shutdown_at"], item["name"].casefold()))
    preview_truncated = len(matches) > 40
    return {
        "status": "matched",
        "query_source": query.source.value,
        "query_kind": query.kind.value,
        "query_scope": query.scope.value,
        "query": query.to_dict(),
        "snapshot_at": graph.get("snapshot_at"),
        "freshness": graph.get("freshness"),
        "source": graph.get("source"),
        "active_view": graph.get("active_view") or "provider-default",
        "truncated": False,
        "total_resources": len(resources),
        "matched_count": len(matches),
        "resources": matches[:40],
        "resource_preview_truncated": preview_truncated,
        "scheduled_window": query.schedule_window.value,
    }


def render_scheduled_shutdown_answer(result: Mapping[str, Any], *, korean: bool) -> str:
    """Render a bounded schedule answer without model inference."""

    count = int(result.get("matched_count", 0))
    resources = [item for item in result.get("resources", ()) if isinstance(item, Mapping)]
    if korean:
        lines = [f"오늘 저녁에 자동 종료가 예정된 VM은 {count}개입니다."]
    else:
        lines = [f"{count} VMs are scheduled for automatic shutdown this evening."]
    for resource in resources:
        shutdown_at = datetime.fromisoformat(str(resource["scheduled_shutdown_at"]))
        lines.append(
            f"- {resource['name']}: {shutdown_at:%H:%M} "
            f"({resource['scheduled_shutdown_time_zone']}), "
            f"{'리소스 그룹' if korean else 'resource group'} {resource['resource_group']}"
        )
    if result.get("resource_preview_truncated"):
        lines.append(
            "처음 40개 VM만 표시했습니다. 전체 일치 수는 위 합계에 포함됩니다."
            if korean
            else "Only the first 40 VMs are shown; the total above includes every match."
        )
    lines.append(
        f"{'근거' if korean else 'Evidence'}: {result.get('source')}, "
        f"snapshot {result.get('snapshot_at')}, freshness {result.get('freshness')}."
    )
    return "\n".join(lines)


def _scheduled_occurrence(
    reference_time: datetime,
    schedule: Mapping[str, Any],
) -> datetime | None:
    time_zone = schedule.get("scheduled_shutdown_time_zone_iana")
    raw_time = schedule.get("scheduled_shutdown_time")
    if not isinstance(time_zone, str) or not isinstance(raw_time, str) or len(raw_time) != 4:
        raise ScheduledShutdownEvidenceError("scheduled shutdown time is invalid")
    zone = _schedule_zone(time_zone)
    local_now = reference_time.astimezone(zone)
    try:
        hour = int(raw_time[:2])
        minute = int(raw_time[2:])
        occurrence = datetime.combine(local_now.date(), time(hour, minute), tzinfo=zone)
    except ValueError as exc:
        raise ScheduledShutdownEvidenceError("scheduled shutdown time is invalid") from exc
    if not 18 <= occurrence.hour <= 23 or occurrence < local_now:
        return None
    return occurrence


def _schedule_zone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ScheduledShutdownEvidenceError("scheduled shutdown timezone is unsupported") from exc


__all__ = [
    "ScheduledShutdownEvidenceError",
    "project_scheduled_shutdown_result",
    "render_scheduled_shutdown_answer",
    "schedule_reference_is_current",
]
