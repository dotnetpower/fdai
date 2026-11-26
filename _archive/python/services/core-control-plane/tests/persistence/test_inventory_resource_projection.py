"""Focused inventory resource display projection tests."""

from fdai.delivery.inventory_schedule import VM_SHUTDOWN_SCHEDULE_TYPE
from fdai.delivery.persistence.postgres_inventory_snapshot import _resource_payload


def test_invalid_optional_shutdown_schedule_does_not_hide_inventory() -> None:
    payload = _resource_payload(
        {
            "resource_id": "schedule-invalid",
            "resource_type": VM_SHUTDOWN_SCHEDULE_TYPE,
            "props": {
                "name": "invalid schedule",
                "providerType": "Microsoft.DevTestLab/schedules",
                "subscriptionId": "invalid",
                "properties": {
                    "taskType": "ComputeVmShutdownTask",
                    "status": "Enabled",
                },
            },
        },
        include_props=True,
    )

    assert payload["id"] == "schedule-invalid"
    assert payload["projection_warnings"] == ["invalid_shutdown_schedule"]
    assert "scheduled_shutdown_time" not in payload
