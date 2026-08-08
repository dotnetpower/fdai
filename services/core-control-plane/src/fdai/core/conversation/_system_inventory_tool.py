"""Read-only inventory console tool."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol, runtime_checkable

from fdai.core.conversation.session import Principal, Role
from fdai.core.conversation.tools import (
    SideEffectClass,
    ToolResult,
    _optional_int,
    _optional_str,
    _require_str,
)


@runtime_checkable
class InventoryProvider(Protocol):
    """A read-only inventory that iterates inventory batches."""

    def full_snapshot(self, since: str | None = None) -> AsyncIterator[Any]: ...


class QueryInventoryTool:
    """Read inventory records by resource type and optional filters."""

    name = "query_inventory"
    description = (
        "Return the inventory records for a given resource_type, optionally "
        "filtered by id substring and/or resource_group (e.g. list the "
        "sql-database resources in one resource group). Read-only; each record "
        "carries its property bag (name, location, tags)."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, inventory: InventoryProvider) -> None:
        self._inventory = inventory

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        import asyncio

        resource_type = _require_str(arguments, "resource_type").strip()
        if not resource_type:
            return ToolResult(
                status="error",
                preview="query_inventory requires a non-empty 'resource_type'",
            )
        id_substring = _optional_str(arguments, "id_substring", default="").lower()
        resource_group = _optional_str(arguments, "resource_group", default="").strip()
        limit = _optional_int(arguments, "limit", default=20, minimum=1, maximum=200)
        try:
            projections = asyncio.run(
                _drain_inventory(
                    self._inventory,
                    resource_type=resource_type,
                    id_substring=id_substring,
                    resource_group=resource_group,
                    limit=limit,
                )
            )
        except RuntimeError as exc:
            return ToolResult(
                status="error",
                preview=f"query_inventory event-loop reuse: {exc}",
            )
        preview = f"query_inventory[{resource_type}]: {len(projections)} record(s)"
        if resource_group:
            preview += f" in resource-group {resource_group}"
        return ToolResult(
            status="ok" if projections else "abstain",
            data={
                "resource_type": resource_type,
                "id_substring": id_substring,
                "resource_group": resource_group,
                "records": projections,
            },
            preview=preview,
            evidence_refs=tuple(f"inventory:{projection['id']}" for projection in projections),
        )


async def _drain_inventory(
    inventory: InventoryProvider,
    *,
    resource_type: str,
    id_substring: str,
    resource_group: str,
    limit: int,
) -> list[dict[str, Any]]:
    projections: list[dict[str, Any]] = []
    async for batch in inventory.full_snapshot():
        for record in getattr(batch, "resources", ()) or ():
            record_type = getattr(record, "type", None) or getattr(record, "resource_type", None)
            if record_type != resource_type:
                continue
            record_id = str(getattr(record, "id", "") or getattr(record, "resource_id", ""))
            if id_substring and id_substring not in record_id.lower():
                continue
            raw_props = getattr(record, "props", None)
            if raw_props is None:
                raw_props = getattr(record, "properties", {})
            properties = dict(raw_props or {})
            if resource_group and not _record_in_resource_group(
                record_id, properties, resource_group
            ):
                continue
            projections.append(
                {"id": record_id, "resource_type": record_type, "properties": properties}
            )
            if len(projections) >= limit:
                return projections
    return projections


def _record_in_resource_group(
    record_id: str,
    properties: Mapping[str, Any],
    resource_group: str,
) -> bool:
    target = resource_group.strip().lower()
    if not target:
        return True
    for key in ("resourceGroup", "resource_group", "resourcegroup"):
        value = properties.get(key)
        if isinstance(value, str) and value.strip().lower() == target:
            return True
    lowered = record_id.lower()
    for marker in ("resource-group/", "resourcegroups/"):
        index = lowered.find(marker)
        if index < 0:
            continue
        segment = lowered[index + len(marker) :].split("/", 1)[0]
        if segment == target:
            return True
    return False
