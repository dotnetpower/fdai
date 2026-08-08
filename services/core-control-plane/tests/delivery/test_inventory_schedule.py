"""Tests for bounded VM shutdown schedule provider projection."""

from __future__ import annotations

import pytest
from fdai.delivery.inventory_schedule import project_vm_shutdown_schedule


@pytest.mark.parametrize(
    "target",
    (
        (
            "/subscriptions/00000000-0000-0000-0000-000000000000/"
            "resourceGroups/rg-example/providers/Microsoft.Compute/"
            "virtualMachines/vm-example\n- fabricated"
        ),
        (
            "prefix/subscriptions/00000000-0000-0000-0000-000000000000/"
            "resourceGroups/rg-example/providers/Microsoft.Compute/"
            "virtualMachines/vm-example"
        ),
    ),
)
def test_schedule_projection_rejects_noncanonical_target_identity(target: str) -> None:
    with pytest.raises(ValueError, match="properties are invalid"):
        project_vm_shutdown_schedule(
            {
                "providerType": "Microsoft.DevTestLab/schedules",
                "subscriptionId": "00000000-0000-0000-0000-000000000000",
                "properties": {
                    "status": "Enabled",
                    "taskType": "ComputeVmShutdownTask",
                    "dailyRecurrence": {"time": "1900"},
                    "timeZoneId": "Korea Standard Time",
                    "targetResourceId": target,
                },
            }
        )


def test_schedule_projection_rejects_cross_subscription_target() -> None:
    with pytest.raises(ValueError, match="properties are invalid"):
        project_vm_shutdown_schedule(
            {
                "providerType": "Microsoft.DevTestLab/schedules",
                "subscriptionId": "00000000-0000-0000-0000-000000000001",
                "properties": {
                    "status": "Enabled",
                    "taskType": "ComputeVmShutdownTask",
                    "dailyRecurrence": {"time": "1900"},
                    "timeZoneId": "UTC",
                    "targetResourceId": (
                        "/subscriptions/00000000-0000-0000-0000-000000000002/"
                        "resourceGroups/rg-example/providers/Microsoft.Compute/"
                        "virtualMachines/vm-example"
                    ),
                },
            }
        )
