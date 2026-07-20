"""Five-round dynamic Azure read-command capability matrix."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import pytest

from fdai.core.tools.default_commands import default_command_catalog
from fdai.delivery.azure.command_runner import (
    AzureCliCommandRunner,
    AzureCliCommandRunnerConfig,
    AzureCliProcessResult,
)
from fdai.shared.providers.command_runner import CommandPlan, CommandStatus

_SUBSCRIPTION = "subscription-example"


def _resolve(
    command_id: str,
    arguments: Mapping[str, object],
    *,
    round_number: int,
    dry_run: bool = True,
) -> CommandPlan:
    return default_command_catalog().resolve(
        command_id=command_id,
        arguments=arguments,
        trusted_values={"subscription": _SUBSCRIPTION},
        idempotency_key=f"round-{round_number}:{command_id}:{sorted(arguments.items())}",
        dry_run=dry_run,
    )


def _config() -> AzureCliCommandRunnerConfig:
    return AzureCliCommandRunnerConfig(
        subscription_id=_SUBSCRIPTION,
        managed_identity_client_id="identity-example",
    )


@pytest.mark.parametrize("round_number", range(1, 6))
async def test_twenty_four_dynamic_read_scenarios_per_round(round_number: int) -> None:
    group = f"rg-round-{round_number}"
    vm = f"vm-round-{round_number}"
    resource_type = "Microsoft.Compute/virtualMachines"

    plans = (
        _resolve("azure.resource.list", {}, round_number=round_number),
        _resolve("azure.resource.list", {"resource_group": group}, round_number=round_number),
        _resolve(
            "azure.resource.list", {"resource_type": resource_type}, round_number=round_number
        ),
        _resolve(
            "azure.resource.list",
            {"resource_group": group, "resource_type": resource_type},
            round_number=round_number,
        ),
        _resolve("azure.group.list", {}, round_number=round_number),
        _resolve("azure.vm.list", {}, round_number=round_number),
        _resolve("azure.vm.list", {"resource_group": group}, round_number=round_number),
        _resolve(
            "azure.vm.status",
            {"resource_group": group, "name": vm},
            round_number=round_number,
        ),
    )
    assert all(plan.dry_run for plan in plans)
    assert all(plan.credential_profile == "azure.reader" for plan in plans)
    assert all(plan.argv[-2:] == ("--subscription", _SUBSCRIPTION) for plan in plans)

    invalid_cases = (
        ("azure.resource.delete", {}, {}, LookupError),
        ("azure.resource.list", {"subscription": "attacker"}, {}, ValueError),
        ("azure.resource.list", {"unknown": "value"}, {}, ValueError),
        ("azure.resource.list", {"resource_group": "bad;group"}, {}, ValueError),
        ("azure.resource.list", {"resource_type": "bad type"}, {}, ValueError),
        ("azure.vm.status", {"resource_group": group}, {}, ValueError),
        ("azure.vm.status", {"name": vm}, {}, ValueError),
        ("azure.vm.status", {"resource_group": group, "name": "bad;vm"}, {}, ValueError),
    )
    catalog = default_command_catalog()
    for command_id, arguments, trusted, error in invalid_cases:
        with pytest.raises(error):
            catalog.resolve(
                command_id=command_id,
                arguments=arguments,
                trusted_values={"subscription": _SUBSCRIPTION, **trusted},
                idempotency_key=f"invalid-{round_number}",
            )

    calls: list[tuple[str, ...]] = []

    async def invoke(
        argv: tuple[str, ...],
        env: Mapping[str, str],  # noqa: ARG001
        timeout: float,  # noqa: ARG001
        cap: int,  # noqa: ARG001
    ) -> AzureCliProcessResult:
        calls.append(argv)
        if argv[1:3] == ("account", "show"):
            return AzureCliProcessResult(0, f"{_SUBSCRIPTION}\n".encode(), b"")
        if argv[1:3] == ("login", "--identity"):
            return AzureCliProcessResult(0, b"", b"")
        if argv[1:3] == ("vm", "get-instance-view"):
            return AzureCliProcessResult(0, b'{"powerState":"VM running"}', b"")
        return AzureCliProcessResult(0, b"[]", b"")

    runner = AzureCliCommandRunner(_config(), invoker=invoke)
    dry_receipt = await runner.execute(plans[0])
    assert dry_receipt.status is CommandStatus.PLANNED
    assert calls == []

    live_plans = tuple(replace(plan, dry_run=False) for plan in plans[4:])
    receipts = [await runner.execute(plan) for plan in live_plans]
    assert all(receipt.status is CommandStatus.SUCCEEDED for receipt in receipts)
    assert receipts[-1].stdout_tail == '{"powerState":"VM running"}'
    assert any(argv[1:3] == ("group", "list") for argv in calls)
    assert any(argv[1:3] == ("vm", "list") for argv in calls)
    assert any(argv[1:3] == ("vm", "get-instance-view") for argv in calls)

    prior_call_count = len(calls)
    replay = await runner.execute(live_plans[-1])
    assert replay.status is CommandStatus.ALREADY_APPLIED
    assert len(calls) == prior_call_count

    wrong_subscription = replace(
        live_plans[0],
        argv=(*live_plans[0].argv[:-1], "other-subscription"),
        idempotency_key=f"wrong-subscription-{round_number}",
    )
    with pytest.raises(ValueError, match="trusted binding"):
        await runner.execute(wrong_subscription)

    unsupported_option = replace(
        live_plans[1],
        argv=(*live_plans[1].argv[:-2], "--query", "name", *live_plans[1].argv[-2:]),
        idempotency_key=f"unsupported-option-{round_number}",
    )
    with pytest.raises(ValueError, match="unsupported option"):
        await runner.execute(unsupported_option)

    missing_required = replace(
        live_plans[-1],
        argv=tuple(value for index, value in enumerate(live_plans[-1].argv) if index not in {5, 6}),
        idempotency_key=f"missing-name-{round_number}",
    )
    with pytest.raises(ValueError, match="requires --resource-group|requires --name"):
        await runner.execute(missing_required)

    assert len(plans) + len(invalid_cases) + 8 == 24
