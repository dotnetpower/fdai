"""Azure CLI command broker keeps identity and subscription server-owned."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from fdai.core.tools.default_commands import default_command_catalog
from fdai.delivery.azure.command_runner import (
    AzureCliCommandRunner,
    AzureCliCommandRunnerConfig,
    AzureCliProcessResult,
)
from fdai.shared.providers.command_runner import CommandPlan, CommandStatus


def _config() -> AzureCliCommandRunnerConfig:
    return AzureCliCommandRunnerConfig(
        subscription_id="subscription-example",
        managed_identity_client_id="identity-example",
    )


def _plan(*, dry_run: bool) -> CommandPlan:
    return default_command_catalog().resolve(
        command_id="azure.resource.list",
        arguments={"resource_group": "rg-example"},
        trusted_values={"subscription": "subscription-example"},
        idempotency_key="event-1",
        dry_run=dry_run,
    )


async def test_dry_run_performs_no_login_or_command() -> None:
    calls: list[tuple[str, ...]] = []

    async def invoke(
        argv: tuple[str, ...],
        env: Mapping[str, str],  # noqa: ARG001
        timeout: float,  # noqa: ARG001
        cap: int,  # noqa: ARG001
    ) -> AzureCliProcessResult:
        calls.append(argv)
        raise AssertionError("dry-run must not invoke Azure CLI")

    receipt = await AzureCliCommandRunner(_config(), invoker=invoke).execute(_plan(dry_run=True))

    assert receipt.status is CommandStatus.PLANNED
    assert calls == []


async def test_live_read_logs_in_with_identity_and_checks_subscription() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    async def invoke(
        argv: tuple[str, ...],
        env: Mapping[str, str],
        timeout: float,  # noqa: ARG001
        cap: int,  # noqa: ARG001
    ) -> AzureCliProcessResult:
        calls.append((argv, dict(env)))
        if argv[1:3] == ("login", "--identity"):
            return AzureCliProcessResult(0, b"", b"")
        if argv[1:3] == ("account", "show"):
            return AzureCliProcessResult(0, b"subscription-example\n", b"")
        return AzureCliProcessResult(0, b'[{"type":"example"}]', b"")

    runner = AzureCliCommandRunner(_config(), invoker=invoke)
    receipt = await runner.execute(_plan(dry_run=False))

    assert receipt.status is CommandStatus.SUCCEEDED
    assert receipt.stdout_tail == '[{"type":"example"}]'
    assert calls[0][0][1:5] == ("login", "--identity", "--client-id", "identity-example")
    assert calls[2][0][1:3] == ("resource", "list")
    assert calls[0][1]["AZURE_EXTENSION_USE_DYNAMIC_INSTALL"] == "no"
    assert calls[0][1]["AZURE_CONFIG_DIR"] == calls[1][1]["AZURE_CONFIG_DIR"]
    assert "AZURE_CONFIG_DIR" in calls[2][1]
    assert not Path(calls[0][1]["AZURE_CONFIG_DIR"]).exists()


async def test_full_output_is_separate_from_bounded_receipt_tail() -> None:
    payload = b'[{"value":"' + (b"x" * 8_000) + b'"}]'

    async def invoke(
        argv: tuple[str, ...],
        env: Mapping[str, str],  # noqa: ARG001
        timeout: float,  # noqa: ARG001
        cap: int,
    ) -> AzureCliProcessResult:
        if argv[1:3] == ("account", "show"):
            return AzureCliProcessResult(0, b"subscription-example\n", b"")
        if argv[1:3] == ("resource", "list"):
            assert cap == _plan(dry_run=False).max_output_bytes
            return AzureCliProcessResult(0, payload, b"")
        return AzureCliProcessResult(0, b"", b"")

    output = await AzureCliCommandRunner(_config(), invoker=invoke).execute_with_output(
        _plan(dry_run=False)
    )

    assert output.stdout == payload.decode()
    assert len(output.receipt.stdout_tail.encode()) == 4_096
    assert "x" * 5_000 not in repr(output)


async def test_full_output_is_not_retained_by_runner() -> None:
    payload = b'[{"value":"' + (b"x" * 8_000) + b'"}]'

    async def invoke(
        argv: tuple[str, ...],
        env: Mapping[str, str],  # noqa: ARG001
        timeout: float,  # noqa: ARG001
        cap: int,  # noqa: ARG001
    ) -> AzureCliProcessResult:
        if argv[1:3] == ("account", "show"):
            return AzureCliProcessResult(0, b"subscription-example\n", b"")
        if argv[1:3] == ("resource", "list"):
            return AzureCliProcessResult(0, payload, b"")
        return AzureCliProcessResult(0, b"", b"")

    runner = AzureCliCommandRunner(_config(), invoker=invoke)
    output = await runner.execute_with_output(_plan(dry_run=False))

    assert len(output.stdout) > 4_096
    assert vars(runner).get("_outputs") is None
    assert all(payload.decode() not in repr(value) for value in vars(runner).values())


async def test_subscription_override_is_rejected_before_login() -> None:
    calls = 0

    async def invoke(
        argv: tuple[str, ...],  # noqa: ARG001
        env: Mapping[str, str],  # noqa: ARG001
        timeout: float,  # noqa: ARG001
        cap: int,  # noqa: ARG001
    ) -> AzureCliProcessResult:
        nonlocal calls
        calls += 1
        return AzureCliProcessResult(0, b"", b"")

    plan = _plan(dry_run=False)
    malicious = replace(
        plan,
        argv=(*plan.argv[:-1], "attacker-subscription"),
    )

    with pytest.raises(ValueError, match="trusted binding"):
        await AzureCliCommandRunner(_config(), invoker=invoke).execute(malicious)
    assert calls == 0


async def test_account_mismatch_stops_before_resource_command() -> None:
    calls: list[tuple[str, ...]] = []

    async def invoke(
        argv: tuple[str, ...],
        env: Mapping[str, str],  # noqa: ARG001
        timeout: float,  # noqa: ARG001
        cap: int,  # noqa: ARG001
    ) -> AzureCliProcessResult:
        calls.append(argv)
        if argv[1:3] == ("account", "show"):
            return AzureCliProcessResult(0, b"other-subscription\n", b"")
        return AzureCliProcessResult(0, b"", b"")

    receipt = await AzureCliCommandRunner(_config(), invoker=invoke).execute(_plan(dry_run=False))

    assert receipt.status is CommandStatus.STOPPED
    assert len(calls) == 2
    assert "does not match" in receipt.stderr_tail
