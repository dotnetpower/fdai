"""Server-scoped task-worker tools backed only by the existing promoted inventory store.

This registry never constructs a cloud reader or interprets natural-language scope. Resource
references come from reviewed server configuration. Unsupported evidence stays unavailable; the
seven-tool capability profile is not a claim that every provider source is configured.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.core.read_investigation.catalog import read_tool_spec
from fdai.core.task_worker.models import TaskWorkerToolResult
from fdai.core.task_worker.tools import TaskWorkerToolDeniedError
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_task_worker_inventory import (
    PostgresTaskWorkerInventoryReader,
)
from fdai.shared.providers.read_investigation import ReadToolId, ResolvedResource


@dataclass(frozen=True, slots=True)
class TaskWorkerReadScope:
    """An explicit server-owned maximum read set, not authority supplied by a worker prompt."""

    scope_ref: str
    resource_refs: frozenset[str]

    def __post_init__(self) -> None:
        if not 1 <= len(self.resource_refs) <= 64:
            raise ValueError("worker read scope MUST contain 1-64 exact resources")
        for value in (self.scope_ref, *self.resource_refs):
            if not value.strip() or len(value) > 256 or any(ord(char) < 32 for char in value):
                raise ValueError("worker read scope requires bounded references")

    @classmethod
    def from_json(cls, value: str) -> TaskWorkerReadScope:
        """Parse private configuration without accepting wildcard or duplicate declarations."""
        if len(value.encode()) > 32_768:
            raise ValueError("worker read scope exceeds the byte limit")

        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for name, item in pairs:
                if name in result:
                    raise ValueError("worker read scope contains duplicate keys")
                result[name] = item
            return result

        raw = json.loads(value, object_pairs_hook=unique)
        if not isinstance(raw, dict) or set(raw) != {"scope_ref", "resource_refs"}:
            raise ValueError("worker read scope fields are invalid")
        refs = raw["resource_refs"]
        if (
            not isinstance(raw["scope_ref"], str)
            or not isinstance(refs, list)
            or not all(isinstance(ref, str) and "*" not in ref for ref in refs)
            or len(set(refs)) != len(refs)
        ):
            raise ValueError("worker read scope requires unique exact resource references")
        return cls(raw["scope_ref"], frozenset(refs))


class TaskWorkerInventoryTool:
    """Expose one fixed, non-billable inventory operation within an explicit maximum scope."""

    side_effect_class = "read"

    def __init__(
        self,
        *,
        tool_id: ReadToolId,
        scope: TaskWorkerReadScope,
        reader: Callable[[str], Awaitable[Mapping[str, Any] | None]],
    ) -> None:
        self.name = tool_id.value
        self._tool_id = tool_id
        self._scope = scope
        self._reader = reader

    async def call(self, arguments: Mapping[str, str]) -> TaskWorkerToolResult:
        """Reject unscoped/raw queries before SQL; return only bounded recorded evidence."""
        if (
            set(arguments) != {"resource_ref"}
            or arguments["resource_ref"] not in self._scope.resource_refs
        ):
            raise TaskWorkerToolDeniedError("worker resource is outside the server read scope")
        if self._tool_id not in {ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE}:
            return TaskWorkerToolResult(
                data=(("status", "unavailable"), ("reason", "source_unbound"))
            )
        reference = arguments["resource_ref"]
        spec = read_tool_spec(self._tool_id)
        async with asyncio.timeout(spec.timeout_seconds):
            raw = await self._reader(reference)
            if raw is None:
                return TaskWorkerToolResult(data=(("status", "unavailable"),))
            if raw.get("resource_id") != reference:
                raise TaskWorkerToolDeniedError("worker inventory target does not match")
            name, resource_type = raw.get("name"), raw.get("resource_type")
            if not isinstance(name, str) or not isinstance(resource_type, str):
                return TaskWorkerToolResult(data=(("status", "unavailable"),))
            resource = ResolvedResource(reference, self._scope.scope_ref, name, resource_type)
            snapshot, at = raw.get("snapshot_id"), raw.get("observed_at")
            if not isinstance(snapshot, str) or not snapshot.strip() or not isinstance(at, str):
                return TaskWorkerToolResult(data=(("status", "unavailable"),))
            observed = datetime.fromisoformat(at)
            if observed.utcoffset() is None:
                return TaskWorkerToolResult(data=(("status", "unavailable"),))
            if self._tool_id is ReadToolId.RESOLVE_RESOURCE:
                return TaskWorkerToolResult(
                    data=(
                        ("status", "matched"),
                        ("resource_ref", reference),
                        ("scope_ref", self._scope.scope_ref),
                        ("name", name),
                        ("resource_type", resource_type),
                    )
                )
            state = raw.get("state")
            if not isinstance(state, str) or not state.strip():
                return TaskWorkerToolResult(data=(("status", "unavailable"),))
            return TaskWorkerToolResult(
                data=(
                    ("status", "matched"),
                    ("authority", "inventory.resource_state"),
                    ("resource_ref", resource.resource_ref),
                    ("freshness", "recorded_fresh"),
                    ("observed_at", observed.isoformat()),
                    ("state_0", state),
                ),
                evidence_refs=(f"inventory-snapshot:{snapshot}",),
            )


def build_task_worker_inventory_tools(
    *, dsn: str, scope: TaskWorkerReadScope
) -> tuple[TaskWorkerInventoryTool, ...]:
    """Bind the seven fixed names to real PostgreSQL readers; no I/O or fake fallback here."""
    config = PostgresInventorySnapshotStoreConfig(dsn=dsn)
    reader = PostgresTaskWorkerInventoryReader(config=config)
    return tuple(
        TaskWorkerInventoryTool(tool_id=tool_id, scope=scope, reader=reader)
        for tool_id in ReadToolId
    )
