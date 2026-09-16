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
    "remediate.tag-add": "azure.resource.tags.merge",
}
_TARGET_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}$")
_TAG_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_TAG_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@ -]{0,255}$")
_LOGICAL_RESOURCE_REF = re.compile(
    r"^scope-[a-f0-9]{16,64}/resource-group/"
    r"[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}"
    r"(?:/providers(?:/[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}){3,15})?$",
    re.IGNORECASE,
)


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
    if operation_id == "azure.resource.tags.merge":
        target_resource_ref = _tag_resource_ref(raw)
        tag_name = _tag_text(raw, "tag_name", _TAG_NAME)
        tag_value = _tag_text(raw, "tag_value", _TAG_VALUE)
        return {
            "target_resource_ref": target_resource_ref,
            "tag_name": tag_name,
            "tag_value": tag_value,
        }
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
    if operation_id == "azure.resource.tags.merge":
        return _tag_resource_ref(arguments)
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


def _tag_resource_ref(arguments: Mapping[str, object]) -> str:
    value = arguments.get("target_resource_ref")
    if not isinstance(value, str) or _LOGICAL_RESOURCE_REF.fullmatch(value) is None:
        raise ValueError(
            "gateway target_resource_ref MUST identify one bounded logical Azure resource"
        )
    parts = value.split("/")
    if "providers" in (part.casefold() for part in parts):
        provider_index = next(
            index for index, part in enumerate(parts) if part.casefold() == "providers"
        )
        if (len(parts) - provider_index - 1) % 2 == 0:
            raise ValueError("gateway target_resource_ref provider path is incomplete")
    return value.casefold()


def _tag_text(
    arguments: Mapping[str, object],
    name: str,
    pattern: re.Pattern[str],
) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"gateway tag argument {name} is invalid")
    return value


__all__ = ["AzureOperationTarget", "resolve_azure_operation_target"]
