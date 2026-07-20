"""The upstream catalog stays narrow, typed, and non-mutating."""

import pytest

from fdai.core.tools.default_commands import default_command_catalog
from fdai.shared.providers.command_runner import CommandExecutionClass


def test_targeted_pytest_plan_uses_trusted_executable_and_workspace() -> None:
    plan = default_command_catalog().resolve(
        command_id="local.python.pytest",
        arguments={"target": "tests/core/tools"},
        trusted_values={},
        idempotency_key="event-1",
        workspace_ref="workspace:sha256:example",
    )

    assert plan.executable_ref == "python.runtime"
    assert plan.argv == ("-m", "pytest", "-q", "--no-cov", "tests/core/tools")
    assert plan.execution_class is CommandExecutionClass.LOCAL_READ
    assert plan.dry_run is True


def test_targeted_pytest_rejects_out_of_scope_path() -> None:
    with pytest.raises(ValueError, match="does not match its pattern"):
        default_command_catalog().resolve(
            command_id="local.python.pytest",
            arguments={"target": "/etc"},
            trusted_values={},
            idempotency_key="event-1",
            workspace_ref="workspace:sha256:example",
        )


def test_local_command_requires_workspace() -> None:
    with pytest.raises(ValueError, match="requires a workspace_ref"):
        default_command_catalog().resolve(
            command_id="local.git.status",
            arguments={},
            trusted_values={},
            idempotency_key="event-1",
        )


def test_cloud_catalog_contains_only_read_class() -> None:
    catalog = default_command_catalog()
    plan = catalog.resolve(
        command_id="azure.resource.list",
        arguments={"resource_group": "rg-example"},
        trusted_values={"subscription": "subscription-example"},
        idempotency_key="event-1",
    )

    assert plan.execution_class is CommandExecutionClass.CLOUD_READ
    with pytest.raises(LookupError, match="unknown command id"):
        catalog.resolve(
            command_id="azure.resource.delete",
            arguments={},
            trusted_values={},
            idempotency_key="event-2",
        )


@pytest.mark.parametrize(
    "command_id,arguments,prefix",
    [
        ("azure.resource.list", {}, ("resource", "list")),
        ("azure.group.list", {}, ("group", "list")),
        ("azure.vm.list", {}, ("vm", "list")),
        (
            "azure.vm.status",
            {"resource_group": "rg-example", "name": "vm-example"},
            ("vm", "get-instance-view"),
        ),
    ],
)
def test_azure_read_commands_render_typed_argv(
    command_id: str,
    arguments: dict[str, object],
    prefix: tuple[str, str],
) -> None:
    plan = default_command_catalog().resolve(
        command_id=command_id,
        arguments=arguments,
        trusted_values={"subscription": "subscription-example"},
        idempotency_key=f"event:{command_id}",
    )

    assert plan.argv[:2] == prefix
    assert plan.argv[-2:] == ("--subscription", "subscription-example")
    assert plan.execution_class is CommandExecutionClass.CLOUD_READ
