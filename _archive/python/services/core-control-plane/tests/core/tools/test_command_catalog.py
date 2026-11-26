"""Typed command plans never accept raw executable, env, or scope overrides."""

import pytest
from fdai.core.tools.command_catalog import (
    CommandArgumentKind,
    CommandArgumentSource,
    CommandArgumentSpec,
    CommandCatalog,
    CommandSpec,
)
from fdai.shared.providers.command_runner import (
    CommandExecutionClass,
    CommandNetworkProfile,
    CommandOutputFormat,
)


def _catalog() -> CommandCatalog:
    return CommandCatalog(
        (
            CommandSpec(
                command_id="azure.resource.list",
                version=1,
                executable_ref="azure.cli",
                fixed_argv=("resource", "list", "--only-show-errors", "--output", "json"),
                arguments=(
                    CommandArgumentSpec(
                        name="resource_group",
                        kind=CommandArgumentKind.STRING,
                        flag="--resource-group",
                        pattern=r"[A-Za-z0-9_.()-]{1,90}",
                    ),
                    CommandArgumentSpec(
                        name="subscription",
                        kind=CommandArgumentKind.STRING,
                        source=CommandArgumentSource.TRUSTED,
                        flag="--subscription",
                        pattern=r"[A-Za-z0-9-]{1,64}",
                    ),
                ),
                execution_class=CommandExecutionClass.CLOUD_READ,
                network_profile=CommandNetworkProfile.AZURE_CONTROL_PLANE,
                output_format=CommandOutputFormat.JSON,
                credential_profile="azure.reader",
            ),
        )
    )


def test_resolves_request_and_trusted_scope_in_catalog_order() -> None:
    plan = _catalog().resolve(
        command_id="azure.resource.list",
        arguments={"resource_group": "rg-example"},
        trusted_values={"subscription": "subscription-example"},
        idempotency_key="event-1",
    )

    assert plan.executable_ref == "azure.cli"
    assert plan.argv == (
        "resource",
        "list",
        "--only-show-errors",
        "--output",
        "json",
        "--resource-group",
        "rg-example",
        "--subscription",
        "subscription-example",
    )
    assert plan.credential_profile == "azure.reader"
    assert plan.dry_run is True


def test_request_cannot_override_trusted_subscription() -> None:
    with pytest.raises(ValueError, match="MUST NOT come from the request"):
        _catalog().resolve(
            command_id="azure.resource.list",
            arguments={
                "resource_group": "rg-example",
                "subscription": "attacker-selected",
            },
            trusted_values={"subscription": "subscription-example"},
            idempotency_key="event-1",
        )


def test_unknown_argument_is_rejected_before_rendering() -> None:
    with pytest.raises(ValueError, match="unknown command arguments"):
        _catalog().resolve(
            command_id="azure.resource.list",
            arguments={"resource_group": "rg-example", "raw_argv": "--help"},
            trusted_values={"subscription": "subscription-example"},
            idempotency_key="event-1",
        )


def test_shell_text_is_rejected_by_argument_pattern() -> None:
    with pytest.raises(ValueError, match="does not match its pattern"):
        _catalog().resolve(
            command_id="azure.resource.list",
            arguments={"resource_group": "rg-example; az account show"},
            trusted_values={"subscription": "subscription-example"},
            idempotency_key="event-1",
        )
