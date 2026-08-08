"""Recording command runner preserves shadow and idempotency semantics."""

from fdai.shared.providers.command_runner import (
    CommandExecutionClass,
    CommandNetworkProfile,
    CommandOutputFormat,
    CommandPlan,
    CommandStatus,
)
from fdai.shared.providers.testing.command_runner import RecordingCommandRunner


def _plan(*, dry_run: bool) -> CommandPlan:
    return CommandPlan(
        command_id="local.pytest",
        command_version=1,
        idempotency_key="event-1",
        executable_ref="python.runtime",
        argv=("-m", "pytest", "services/core-control-plane/tests/unit"),
        execution_class=CommandExecutionClass.LOCAL_READ,
        network_profile=CommandNetworkProfile.NONE,
        output_format=CommandOutputFormat.TEXT,
        timeout_seconds=120,
        max_output_bytes=64 * 1024,
        dry_run=dry_run,
        workspace_ref="workspace:sha256:example",
    )


async def test_dry_run_records_no_execution() -> None:
    runner = RecordingCommandRunner()

    receipt = await runner.execute(_plan(dry_run=True))

    assert receipt.status is CommandStatus.PLANNED
    assert runner.calls == []


async def test_live_retry_is_idempotent() -> None:
    runner = RecordingCommandRunner()

    first = await runner.execute(_plan(dry_run=False))
    second = await runner.execute(_plan(dry_run=False))

    assert first.status is CommandStatus.SUCCEEDED
    assert second.status is CommandStatus.ALREADY_APPLIED
    assert second.receipt_ref == first.receipt_ref
    assert len(runner.calls) == 1
