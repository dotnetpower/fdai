"""Tests for deterministic VM shutdown schedule projection."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.delivery.operator_api.application.conversation.capabilities.inventory.query import (
    InventoryField,
    InventoryOperator,
    InventoryPredicate,
    InventoryQuery,
    InventoryQueryKind,
    InventoryQuerySource,
    InventoryScheduleWindow,
)
from fdai.delivery.operator_api.projections.conversation.inventory.schedule import (
    project_scheduled_shutdown_result,
    render_scheduled_shutdown_answer,
)


def test_schedule_projection_discloses_bounded_preview() -> None:
    query = InventoryQuery(
        source=InventoryQuerySource.CURRENT,
        kind=InventoryQueryKind.SCHEDULED_SHUTDOWN,
        predicates=(
            InventoryPredicate(
                InventoryField.RESOURCE_TYPE,
                InventoryOperator.EQ,
                "compute.vm-shutdown-schedule",
            ),
        ),
        require_fresh=True,
        schedule_window=InventoryScheduleWindow.TODAY_EVENING,
        reference_time=datetime(2026, 8, 5, 3, 0, tzinfo=UTC),
    )
    resources = [
        {
            "type": "compute.vm-shutdown-schedule",
            "scheduled_shutdown_status": "Enabled",
            "scheduled_shutdown_time": "1900",
            "scheduled_shutdown_time_zone": "Korea Standard Time",
            "scheduled_shutdown_time_zone_iana": "Asia/Seoul",
            "scheduled_shutdown_target_name": f"vm-{index:02d}",
            "scheduled_shutdown_target_resource_group": "rg-example",
            "scheduled_shutdown_target_subscription_digest": "sha256:" + "a" * 64,
        }
        for index in range(41)
    ]
    graph = {
        "snapshot_at": "2026-08-05T03:00:00+00:00",
        "freshness": "fresh",
        "source": "azure-resource-graph",
        "active_view": "all-resources",
        "truncated": False,
        "coverage": {"resource_types": ["compute.vm-shutdown-schedule"]},
    }

    result = project_scheduled_shutdown_result(query, graph, resources)

    assert result["matched_count"] == 41
    assert len(result["resources"]) == 40
    assert result["resource_preview_truncated"] is True
    assert "처음 40개" in render_scheduled_shutdown_answer(result, korean=True)


def test_schedule_projection_deduplicates_target_vm_and_keeps_earliest() -> None:
    query = InventoryQuery(
        source=InventoryQuerySource.CURRENT,
        kind=InventoryQueryKind.SCHEDULED_SHUTDOWN,
        predicates=(),
        require_fresh=True,
        schedule_window=InventoryScheduleWindow.TODAY_EVENING,
        reference_time=datetime(2026, 8, 5, 3, 0, tzinfo=UTC),
    )
    resources = [
        {
            "type": "compute.vm-shutdown-schedule",
            "scheduled_shutdown_status": "Enabled",
            "scheduled_shutdown_time": shutdown_time,
            "scheduled_shutdown_time_zone": "Korea Standard Time",
            "scheduled_shutdown_time_zone_iana": "Asia/Seoul",
            "scheduled_shutdown_target_name": "vm-example",
            "scheduled_shutdown_target_resource_group": "rg-example",
            "scheduled_shutdown_target_subscription_digest": "sha256:" + "a" * 64,
        }
        for shutdown_time in ("2300", "1900", "1900")
    ]
    graph = {
        "snapshot_at": "2026-08-05T03:00:00+00:00",
        "freshness": "fresh",
        "source": "azure-resource-graph",
        "active_view": "all-resources",
        "truncated": False,
        "coverage": {"resource_types": ["compute.vm-shutdown-schedule"]},
    }

    result = project_scheduled_shutdown_result(query, graph, resources)

    assert result["matched_count"] == 1
    assert result["resources"][0]["scheduled_shutdown_at"] == "2026-08-05T19:00:00+09:00"


def test_schedule_projection_keeps_same_vm_name_in_distinct_subscriptions() -> None:
    query = InventoryQuery(
        source=InventoryQuerySource.CURRENT,
        kind=InventoryQueryKind.SCHEDULED_SHUTDOWN,
        predicates=(),
        require_fresh=True,
        schedule_window=InventoryScheduleWindow.TODAY_EVENING,
        reference_time=datetime(2026, 8, 5, 3, 0, tzinfo=UTC),
    )
    resources = [
        {
            "type": "compute.vm-shutdown-schedule",
            "scheduled_shutdown_status": "Enabled",
            "scheduled_shutdown_time": "1900",
            "scheduled_shutdown_time_zone": "Korea Standard Time",
            "scheduled_shutdown_time_zone_iana": "Asia/Seoul",
            "scheduled_shutdown_target_name": "vm-example",
            "scheduled_shutdown_target_resource_group": "rg-example",
            "scheduled_shutdown_target_subscription_digest": "sha256:" + digest * 64,
        }
        for digest in ("a", "b")
    ]
    graph = {
        "snapshot_at": "2026-08-05T03:00:00+00:00",
        "freshness": "fresh",
        "source": "azure-resource-graph",
        "active_view": "all-resources",
        "truncated": False,
        "coverage": {"resource_types": ["compute.vm-shutdown-schedule"]},
    }

    result = project_scheduled_shutdown_result(query, graph, resources)

    assert result["matched_count"] == 2
    assert all("subscription" not in resource for resource in result["resources"])
