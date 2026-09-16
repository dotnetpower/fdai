"""Sanitize and validate direct ARM virtual-machine child state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from fdai.shared.providers.inventory import ResourceRecord


class ArmInventoryError(RuntimeError):
    """A direct ARM inventory shard could not complete safely."""


def project_vmss_instance_state(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """Keep one power-state code and discard unreviewed VMSS instance-view fields."""

    properties = row.get("properties")
    if not isinstance(properties, Mapping):
        return row
    instance_view = properties.get("instanceView")
    if not isinstance(instance_view, Mapping):
        return {**row, "properties": {**properties, "instanceView": {}}}
    statuses = instance_view.get("statuses")
    if not isinstance(statuses, list):
        return {**row, "properties": {**properties, "instanceView": {}}}
    power_states = {
        code.strip().casefold()
        for item in statuses
        if isinstance(item, Mapping)
        and isinstance((code := item.get("code")), str)
        and code.strip().casefold().startswith("powerstate/")
    }
    if len(power_states) > 1:
        raise ArmInventoryError("ARM VM scale-set instance view has conflicting power states")
    sanitized_view = (
        {"powerState": {"code": f"PowerState/{next(iter(power_states)).split('/', 1)[1]}"}}
        if power_states
        else {}
    )
    return {**row, "properties": {**properties, "instanceView": sanitized_view}}


def with_vm_run_command_state(
    resource: ResourceRecord,
    row: Mapping[str, Any],
) -> ResourceRecord:
    """Merge only executionState; command output and error text never persist."""

    properties = row.get("properties")
    instance_view = properties.get("instanceView") if isinstance(properties, Mapping) else None
    execution_state = (
        instance_view.get("executionState") if isinstance(instance_view, Mapping) else None
    )
    props = dict(resource.props)
    existing = props.get("properties")
    nested = dict(existing) if isinstance(existing, Mapping) else {}
    nested["instanceView"] = (
        {"executionState": execution_state.strip()}
        if isinstance(execution_state, str) and execution_state.strip()
        else {}
    )
    props["properties"] = nested
    return replace(
        resource,
        props=props,
        last_seen=(
            datetime.now(tz=UTC).isoformat()
            if isinstance(execution_state, str) and execution_state.strip()
            else resource.last_seen
        ),
    )


def validate_child_identity(
    resource_id: str,
    *,
    parent_id: str,
    collection: str,
) -> None:
    """Require one exact direct child below the requested ARM collection."""

    expected = f"{parent_id.rstrip('/')}/{collection}/".casefold()
    normalized = resource_id.casefold()
    remainder = normalized.removeprefix(expected)
    if normalized == remainder or not remainder or "/" in remainder:
        raise ArmInventoryError("ARM child response changed parent identity")
