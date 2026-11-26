"""PostgreSQL Python task artifacts and active-inventory VM target resolution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.shared.providers.vm_task import (
    PythonTaskArtifactStore,
    PythonTaskCapability,
    PythonTaskSpec,
    VmTaskTarget,
    VmTaskTargetResolver,
    python_task_from_mapping,
    python_task_to_mapping,
)


@dataclass(frozen=True, slots=True)
class PostgresVmTaskConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("dsn MUST be non-empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("database timeouts MUST be positive")


class PostgresPythonTaskArtifactStore(PythonTaskArtifactStore):
    """Immutable artifact registry keyed by task version and content hash."""

    def __init__(self, *, config: PostgresVmTaskConfig) -> None:
        self._config = config

    async def put(self, task: PythonTaskSpec, *, created_by: str = "system") -> str:
        if not created_by:
            raise ValueError("created_by MUST be non-empty")
        manifest = json.dumps(python_task_to_mapping(task), separators=(",", ":"))
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                cursor = await connection.execute(
                    "INSERT INTO python_task_artifact "
                    "(artifact_ref, task_id, version, artifact_hash, manifest, created_by) "
                    "VALUES (%s, %s, %s, %s, %s::jsonb, %s) "
                    "ON CONFLICT (task_id, version) DO NOTHING RETURNING artifact_ref",
                    (
                        task.artifact_ref,
                        task.task_id,
                        task.version,
                        task.artifact_hash,
                        manifest,
                        created_by,
                    ),
                )
                inserted = await cursor.fetchone()
                if inserted is not None:
                    return task.artifact_ref
                existing_cursor = await connection.execute(
                    "SELECT artifact_ref, artifact_hash FROM python_task_artifact "
                    "WHERE task_id=%s AND version=%s FOR UPDATE",
                    (task.task_id, task.version),
                )
                existing = await existing_cursor.fetchone()
                if existing is None:  # pragma: no cover - transaction invariant
                    raise RuntimeError("Python task artifact conflict row disappeared")
                if existing["artifact_hash"] != task.artifact_hash:
                    raise ValueError(
                        f"task version {task.task_id}@{task.version} is immutable "
                        "and already registered"
                    )
                return str(existing["artifact_ref"])

    async def get(self, artifact_ref: str) -> PythonTaskSpec:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT manifest, artifact_hash FROM python_task_artifact WHERE artifact_ref=%s",
                (artifact_ref,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise LookupError(f"unknown Python task artifact {artifact_ref!r}")
        manifest = row["manifest"]
        if isinstance(manifest, str):
            manifest = json.loads(manifest)
        if not isinstance(manifest, Mapping):
            raise RuntimeError("stored Python task manifest is not an object")
        task = python_task_from_mapping(manifest)
        if task.artifact_hash != row["artifact_hash"] or task.artifact_ref != artifact_ref:
            raise RuntimeError("stored Python task artifact hash mismatch")
        return task

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


class PostgresVmTaskTargetResolver(VmTaskTargetResolver):
    """Resolve one compute.vm from the active immutable inventory snapshot."""

    def __init__(self, *, config: PostgresVmTaskConfig) -> None:
        self._config = config

    async def resolve(self, resource_ref: str) -> VmTaskTarget:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            cursor = await connection.execute(
                "SELECT r.resource_id, r.resource_type, r.props, r.provider_ref "
                "FROM inventory_active a "
                "JOIN inventory_snapshot_resource r ON r.snapshot_id=a.snapshot_id "
                "WHERE a.singleton=TRUE AND r.resource_id=%s",
                (resource_ref,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise LookupError(f"resource {resource_ref!r} is not in the active inventory")
        return vm_task_target_from_inventory_row(row)


def vm_task_target_from_inventory_row(row: Mapping[str, object]) -> VmTaskTarget:
    """Map one active inventory row into an explicitly opted-in task target."""
    resource_ref = row.get("resource_id")
    if not isinstance(resource_ref, str) or not resource_ref:
        raise LookupError("inventory VM row has no resource_id")
    if row["resource_type"] != "compute.vm":
        raise LookupError(f"resource {resource_ref!r} is not a compute.vm")
    provider_ref = row["provider_ref"]
    if not isinstance(provider_ref, str) or not provider_ref:
        raise LookupError(f"resource {resource_ref!r} has no provider_ref")
    props = row["props"]
    if isinstance(props, str):
        props = json.loads(props)
    props = dict(props) if isinstance(props, Mapping) else {}
    location = props.get("location")
    os_type = _nested_string(props, "properties", "storageProfile", "osDisk", "osType")
    tags = props.get("tags")
    tags = dict(tags) if isinstance(tags, Mapping) else {}
    if str(tags.get("fdai:vm-task-ready", "")).lower() != "true":
        raise LookupError(f"resource {resource_ref!r} is not opted into VM task execution")
    return VmTaskTarget(
        resource_ref=resource_ref,
        provider_ref=provider_ref,
        capabilities=frozenset(_target_capabilities(props)),
        os_type="linux" if not os_type or os_type.lower() == "linux" else os_type.lower(),
        location=location if isinstance(location, str) else None,
    )


def _target_capabilities(props: Mapping[str, object]) -> set[PythonTaskCapability]:
    capabilities: set[PythonTaskCapability] = set()
    tags = props.get("tags")
    tags = dict(tags) if isinstance(tags, Mapping) else {}
    raw = tags.get("fdai:capabilities") or tags.get("fdai_capabilities") or ""
    values = raw.split(",") if isinstance(raw, str) else []
    for value in values:
        try:
            capabilities.add(PythonTaskCapability(value.strip()))
        except ValueError:
            continue
    vm_size = _nested_string(props, "properties", "hardwareProfile", "vmSize") or ""
    normalized = vm_size.upper().removeprefix("STANDARD_")
    if normalized.startswith(("NC", "ND", "NV")):
        capabilities.add(PythonTaskCapability.GPU)
    return capabilities


def _nested_string(value: Mapping[str, object], *path: str) -> str | None:
    current: object = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current if isinstance(current, str) else None


__all__ = [
    "PostgresPythonTaskArtifactStore",
    "PostgresVmTaskConfig",
    "PostgresVmTaskTargetResolver",
    "vm_task_target_from_inventory_row",
]
