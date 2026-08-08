"""Pure inventory mapping for PostgreSQL VM task targets."""

import pytest
from fdai.delivery.persistence.postgres_vm_task import vm_task_target_from_inventory_row
from fdai.shared.providers.vm_task import PythonTaskCapability


def _row(*, ready: str = "true", vm_size: str = "Standard_NC24ads_A100_v4") -> dict:
    return {
        "resource_id": "resource:compute/vm/gpu-worker",
        "resource_type": "compute.vm",
        "provider_ref": (
            "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/"
            "rg-example/providers/Microsoft.Compute/virtualMachines/gpu-worker"
        ),
        "props": {
            "location": "example-region",
            "tags": {
                "fdai:vm-task-ready": ready,
                "fdai:capabilities": "network,filesystem_write,process",
            },
            "properties": {
                "hardwareProfile": {"vmSize": vm_size},
                "storageProfile": {"osDisk": {"osType": "Linux"}},
            },
        },
    }


def test_opted_in_gpu_vm_maps_inventory_and_tags() -> None:
    target = vm_task_target_from_inventory_row(_row())

    assert target.provider_ref is not None
    assert target.location == "example-region"
    assert target.capabilities == frozenset(
        {
            PythonTaskCapability.GPU,
            PythonTaskCapability.NETWORK,
            PythonTaskCapability.FILESYSTEM_WRITE,
            PythonTaskCapability.PROCESS,
        }
    )


def test_vm_without_explicit_ready_tag_is_rejected() -> None:
    with pytest.raises(LookupError, match="not opted"):
        vm_task_target_from_inventory_row(_row(ready="false"))


def test_non_gpu_sku_does_not_gain_gpu_capability() -> None:
    target = vm_task_target_from_inventory_row(_row(vm_size="Standard_D4s_v5"))
    assert PythonTaskCapability.GPU not in target.capabilities
