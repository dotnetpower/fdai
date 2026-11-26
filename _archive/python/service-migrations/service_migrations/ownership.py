"""Validate exclusive service ownership for legacy tables and write scopes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from service_migrations.inventory import LegacyInventory

SERVICE_IDS = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)


@dataclass(frozen=True)
class WriteTransition:
    """One non-overlapping write scope on a transition-controlled table."""

    transition_id: str
    table: str
    scope: str
    writer: str


@dataclass(frozen=True)
class MigrationDependency:
    """One cross-service schema dependency between exact branch revisions."""

    consumer_service: str
    consumer_revision: str
    provider_service: str
    provider_revision: str
    schema_prerequisites: tuple[str, ...]
    provider_rollback: str

    @property
    def provider(self) -> tuple[str, str]:
        """Return the provider service and minimum required revision."""
        return self.provider_service, self.provider_revision


@dataclass(frozen=True)
class OwnershipManifest:
    """Validated table migration and write ownership for the five services."""

    table_migrators: dict[str, str]
    table_writers: dict[str, str]
    transitions: tuple[WriteTransition, ...]
    migration_dependencies: tuple[MigrationDependency, ...]


def _owned_tables(raw: object, field: str) -> dict[str, str]:
    if not isinstance(raw, dict) or set(raw) != set(SERVICE_IDS):
        raise ValueError(f"{field} must define exactly the five service ids")
    owners: dict[str, str] = {}
    for service_id in SERVICE_IDS:
        tables = raw[service_id]
        if not isinstance(tables, list) or not all(isinstance(item, str) for item in tables):
            raise ValueError(f"{field}.{service_id} must be a string list")
        for table in cast(list[str], tables):
            if table in owners:
                raise ValueError(
                    f"overlapping {field} ownership for {table}: {owners[table]} and {service_id}"
                )
            owners[table] = service_id
    return owners


def _transitions(raw: object) -> tuple[WriteTransition, ...]:
    if not isinstance(raw, list):
        raise ValueError("transition_ownership must be a list")
    transitions: list[WriteTransition] = []
    ids: set[str] = set()
    scopes: set[tuple[str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("transition ownership entries must be objects")
        required = {"id", "table", "scope", "writer"}
        if set(item) != required or not all(isinstance(item[key], str) for key in required):
            raise ValueError(f"transition ownership entry must contain {sorted(required)}")
        transition = WriteTransition(
            transition_id=cast(str, item["id"]),
            table=cast(str, item["table"]),
            scope=cast(str, item["scope"]),
            writer=cast(str, item["writer"]),
        )
        if transition.writer not in SERVICE_IDS:
            raise ValueError(f"unknown transition writer: {transition.writer}")
        if transition.transition_id in ids:
            raise ValueError(f"duplicate transition id: {transition.transition_id}")
        scope_key = (transition.table, transition.scope)
        if scope_key in scopes:
            raise ValueError(
                f"overlapping transition ownership for {transition.table}:{transition.scope}"
            )
        ids.add(transition.transition_id)
        scopes.add(scope_key)
        transitions.append(transition)
    return tuple(transitions)


def _migration_dependencies(raw: object) -> tuple[MigrationDependency, ...]:
    if not isinstance(raw, list):
        raise ValueError("migration_dependencies must be a list")
    required = {
        "consumer_service",
        "consumer_revision",
        "provider_service",
        "provider_revision",
        "schema_prerequisites",
        "provider_rollback",
    }
    dependencies: list[MigrationDependency] = []
    edges: set[tuple[str, str, str, str]] = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError(f"migration dependency must contain {sorted(required)}")
        scalar_fields = required - {"schema_prerequisites"}
        if not all(isinstance(item[field], str) and item[field] for field in scalar_fields):
            raise ValueError("migration dependency scalar fields must be non-empty strings")
        prerequisites = item["schema_prerequisites"]
        if (
            not isinstance(prerequisites, list)
            or not prerequisites
            or not all(isinstance(value, str) and value for value in prerequisites)
            or len(set(prerequisites)) != len(prerequisites)
        ):
            raise ValueError("migration dependency schema_prerequisites must be unique strings")
        dependency = MigrationDependency(
            consumer_service=cast(str, item["consumer_service"]),
            consumer_revision=cast(str, item["consumer_revision"]),
            provider_service=cast(str, item["provider_service"]),
            provider_revision=cast(str, item["provider_revision"]),
            schema_prerequisites=tuple(cast(list[str], prerequisites)),
            provider_rollback=cast(str, item["provider_rollback"]),
        )
        if dependency.consumer_service not in SERVICE_IDS:
            raise ValueError(
                f"unknown migration dependency consumer: {dependency.consumer_service}"
            )
        if dependency.provider_service not in SERVICE_IDS:
            raise ValueError(
                f"unknown migration dependency provider: {dependency.provider_service}"
            )
        if dependency.consumer_service == dependency.provider_service:
            raise ValueError("cross-service migration dependency cannot reference one service")
        edge = (
            dependency.consumer_service,
            dependency.consumer_revision,
            dependency.provider_service,
            dependency.provider_revision,
        )
        if edge in edges:
            raise ValueError(f"duplicate migration dependency: {edge}")
        edges.add(edge)
        dependencies.append(dependency)
    return tuple(dependencies)


def migration_order(
    manifest: OwnershipManifest,
    service_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Topologically order selected services while preserving stable input order."""
    if len(set(service_ids)) != len(service_ids) or not set(service_ids) <= set(SERVICE_IDS):
        raise ValueError("migration order requires unique known service ids")
    selected = set(service_ids)
    providers = {
        service_id: {
            dependency.provider_service
            for dependency in manifest.migration_dependencies
            if dependency.consumer_service == service_id and dependency.provider_service in selected
        }
        for service_id in service_ids
    }
    ordered: list[str] = []
    while len(ordered) < len(service_ids):
        ready = next(
            (
                service_id
                for service_id in service_ids
                if service_id not in ordered and providers[service_id] <= set(ordered)
            ),
            None,
        )
        if ready is None:
            blocked = tuple(service_id for service_id in service_ids if service_id not in ordered)
            raise ValueError(f"migration dependency cycle detected: {blocked}")
        ordered.append(ready)
    return tuple(ordered)


def load_ownership_manifest(path: Path, inventory: LegacyInventory) -> OwnershipManifest:
    """Load ownership and reject unknown tables, services, gaps, or overlaps."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("ownership manifest must be an object")
    expected = raw.get("legacy_inventory")
    if not isinstance(expected, dict):
        raise ValueError("legacy_inventory metadata is required")
    actual_metadata = {
        "head": inventory.heads[0],
        "revision_count": len(inventory.down_revisions),
        "table_count": len(inventory.table_sources),
    }
    if expected != actual_metadata:
        raise ValueError(
            f"legacy inventory changed; expected {expected}, observed {actual_metadata}"
        )

    migrators = _owned_tables(raw.get("table_migrations"), "table_migrations")
    legacy_tables = set(inventory.table_sources)
    if not legacy_tables <= set(migrators):
        missing = sorted(legacy_tables - set(migrators))
        raise ValueError(f"legacy table migration ownership is missing: {missing}")

    writers = _owned_tables(raw.get("whole_table_writers"), "whole_table_writers")
    transitions = _transitions(raw.get("transition_ownership"))
    transition_tables = {transition.table for transition in transitions}
    owned_tables = set(migrators)
    if transition_tables - owned_tables:
        unknown_transition_tables = sorted(transition_tables - owned_tables)
        raise ValueError(f"transitions reference unknown tables: {unknown_transition_tables}")
    if set(writers) & transition_tables:
        raise ValueError(
            "whole-table and transition-scoped writers overlap: "
            f"{sorted(set(writers) & transition_tables)}"
        )
    covered_writes = set(writers) | transition_tables
    if covered_writes != owned_tables:
        missing = sorted(owned_tables - covered_writes)
        unknown = sorted(covered_writes - owned_tables)
        raise ValueError(f"table write ownership mismatch; missing={missing}, unknown={unknown}")
    manifest = OwnershipManifest(
        table_migrators=migrators,
        table_writers=writers,
        transitions=transitions,
        migration_dependencies=_migration_dependencies(raw.get("migration_dependencies")),
    )
    migration_order(manifest, SERVICE_IDS)
    return manifest
