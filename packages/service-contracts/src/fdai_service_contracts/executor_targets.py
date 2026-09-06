"""Canonical managed-resource targets for allowlisted Azure operations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

_ACTION_OPERATIONS = {
    "ops.start-vm": "azure.compute.vm.start",
    "ops.deallocate-vm": "azure.compute.vm.deallocate",
    "ops.upsert-network-rule": "azure.network.nsg.rule.upsert",
    "ops.delete-network-rule": "azure.network.nsg.rule.delete",
}
_TARGET_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}$")


@dataclass(frozen=True, slots=True)
class AzureOperationTarget:
    """Normalized gateway operation and its exact logical target identity."""

    operation_id: str
    arguments: dict[str, object]
    resource_ref: str


def resolve_azure_operation_target(
    action_type_name: str,
    raw_arguments: Mapping[str, object],
) -> AzureOperationTarget:
    """Resolve one allowlisted action to normalized arguments and an ARM-scope target."""

    operation_id = _ACTION_OPERATIONS.get(action_type_name)
    if operation_id is None:
        raise ValueError(f"gateway has no registered operation for {action_type_name}")
    arguments = _normalize_arguments(operation_id, raw_arguments)
    return AzureOperationTarget(
        operation_id=operation_id,
        arguments=arguments,
        resource_ref=_canonical_resource_ref(operation_id, arguments),
    )


def _normalize_arguments(
    operation_id: str,
    raw: Mapping[str, object],
) -> dict[str, object]:
    required: tuple[str, ...]
    if operation_id.startswith("azure.compute.vm."):
        required = ("resource_group", "vm_name")
    elif operation_id == "azure.network.nsg.rule.delete":
        required = ("resource_group", "nsg_name", "rule_name")
    else:
        required = ("resource_group", "nsg_name", "rule_name", "rule")
    arguments: dict[str, object] = {}
    for key in required:
        if key not in raw:
            raise ValueError(f"gateway argument {key} is required")
        arguments[key] = raw[key]
    return arguments


def _canonical_resource_ref(
    operation_id: str,
    arguments: Mapping[str, object],
) -> str:
    resource_group = _target_segment(arguments, "resource_group")
    if operation_id.startswith("azure.compute.vm."):
        vm_name = _target_segment(arguments, "vm_name")
        return (
            f"/resourcegroups/{resource_group}/providers/"
            f"microsoft.compute/virtualmachines/{vm_name}"
        )
    nsg_name = _target_segment(arguments, "nsg_name")
    rule_name = _target_segment(arguments, "rule_name")
    return (
        f"/resourcegroups/{resource_group}/providers/"
        f"microsoft.network/networksecuritygroups/{nsg_name}/securityrules/{rule_name}"
    )


def _target_segment(arguments: Mapping[str, object], name: str) -> str:
    value = arguments[name]
    if not isinstance(value, str) or _TARGET_SEGMENT.fullmatch(value) is None:
        raise ValueError(f"gateway target argument {name} MUST be a bounded non-empty string")
    return value.casefold()


__all__ = ["AzureOperationTarget", "resolve_azure_operation_target"]
