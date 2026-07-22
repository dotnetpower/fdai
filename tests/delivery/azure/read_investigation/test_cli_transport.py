from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from fdai.core.tools.default_commands import default_command_catalog
from fdai.delivery.azure.read_investigation import (
    AzureCliReadTransport,
    AzureReadCliConfig,
    AzureReadCliError,
)
from fdai.shared.providers.command_runner import (
    CommandPlan,
    CommandReceipt,
    CommandStatus,
)
from fdai.shared.providers.read_investigation import ReadToolLimits, ResourceSelector

RESOURCE_ID = (
    "/subscriptions/sub-example/resourceGroups/rg-example/"
    "providers/Microsoft.Compute/virtualMachines/vm-01"
)
LIMITS = ReadToolLimits(timeout_seconds=120, max_results=8, max_output_bytes=64_000)


class _Runner:
    def __init__(self) -> None:
        self.plans: list[CommandPlan] = []

    async def execute(self, plan: CommandPlan) -> CommandReceipt:
        self.plans.append(plan)
        if plan.command_id == "azure.read.resource.resolve":
            payload: object = [
                {
                    "id": RESOURCE_ID,
                    "name": "vm-01",
                    "type": "Microsoft.Compute/virtualMachines",
                    "resourceGroup": "rg-example",
                }
            ]
        elif plan.command_id == "azure.vm.status":
            payload = {"statuses": [{"code": "PowerState/deallocated"}]}
        else:
            payload = [
                {
                    "eventTimestamp": datetime(2026, 7, 22, tzinfo=UTC).isoformat(),
                    "status": {"value": "Succeeded"},
                    "operationName": {"value": "deallocate"},
                    "caller": "caller@example.com",
                    "correlationId": "provider-correlation",
                }
            ]
        return CommandReceipt(
            status=CommandStatus.SUCCEEDED,
            receipt_ref=f"receipt:{plan.command_id}",
            exit_code=0,
            stdout_tail=json.dumps(payload),
        )


def _transport(runner: _Runner) -> AzureCliReadTransport:
    return AzureCliReadTransport(
        config=AzureReadCliConfig(
            scope_ref="scope:allowed",
            subscription_id="sub-example",
            resource_groups=("rg-example",),
            resource_type_map=(("Microsoft.Compute/virtualMachines", "compute.vm"),),
        ),
        catalog=default_command_catalog(),
        runner=runner,
    )


async def test_cli_transport_uses_registered_resource_state_and_activity_plans() -> None:
    runner = _Runner()
    transport = _transport(runner)
    resources = await transport.resolve_resources(
        ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
        limits=LIMITS,
    )
    state = await transport.get_resource_state(RESOURCE_ID, limits=LIMITS)
    activity = await transport.query_resource_activity(
        RESOURCE_ID,
        lookback_seconds=3_600,
        limits=LIMITS,
    )

    assert resources[0]["type"] == "compute.vm"
    assert state[0]["state"] == "deallocated"
    assert activity[0]["operation"] == "deallocate"
    assert [plan.command_id for plan in runner.plans] == [
        "azure.read.resource.resolve",
        "azure.vm.status",
        "azure.activity-log.list",
    ]
    assert runner.plans[0].argv == (
        "resource",
        "list",
        "--only-show-errors",
        "--query",
        "[:9].{id:id,name:name,type:type,resourceGroup:resourceGroup}",
        "--output",
        "json",
        "--name",
        "vm-01",
        "--resource-group",
        "rg-example",
        "--subscription",
        "sub-example",
    )
    assert "--resource-id" in runner.plans[2].argv
    assert "--start-time" in runner.plans[2].argv
    assert "--max-events" in runner.plans[2].argv


async def test_cli_transport_rejects_scope_widening_and_unsupported_sources() -> None:
    runner = _Runner()
    transport = _transport(runner)
    with pytest.raises(PermissionError, match="scope"):
        await transport.resolve_resources(
            ResourceSelector(name="vm-01", scope_ref="scope:other"),
            limits=LIMITS,
        )
    with pytest.raises(AzureReadCliError, match="Resource Health"):
        await transport.query_resource_health(
            RESOURCE_ID,
            lookback_seconds=3_600,
            limits=LIMITS,
        )
    with pytest.raises(AzureReadCliError, match="guest logs"):
        await transport.query_guest_shutdown_events(
            RESOURCE_ID,
            lookback_seconds=3_600,
            limits=LIMITS,
        )
    assert runner.plans == []
