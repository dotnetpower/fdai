"""PostgreSQL adapters for immutable workflow definitions and user bindings."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres_user_context_projection_queue import (
    enqueue_projection_upsert,
)
from fdai.shared.providers.workflow_definition import (
    WorkflowBindingRecord,
    WorkflowBindingTrigger,
    WorkflowDefinitionConflictError,
    WorkflowDefinitionRecord,
    WorkflowLifecycle,
    WorkflowOrigin,
    WorkflowVisibility,
)


@dataclass(frozen=True, slots=True)
class PostgresWorkflowDefinitionStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresWorkflowDefinitionStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresWorkflowDefinitionStoreConfig timeouts MUST be positive")


class _PostgresBase:
    def __init__(self, *, config: PostgresWorkflowDefinitionStoreConfig) -> None:
        self._config: Final = config

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        timeout = int(self._config.statement_timeout_ms)
        await connection.execute(f"SET LOCAL statement_timeout = {timeout}")


class PostgresWorkflowDefinitionStore(_PostgresBase):
    async def put(self, record: WorkflowDefinitionRecord) -> WorkflowDefinitionRecord:
        stored = record
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "INSERT INTO workflow_definition "
                "(definition_id, workflow_name, workflow_version, schema_version, "
                "definition_hash, action_catalog_digest, resolved_action_versions, origin, "
                "workflow_document, visibility, lifecycle, owner_ref, derived_from, source_ref, "
                "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, "
                "%s, %s, %s, %s, %s) "
                "ON CONFLICT (definition_id) DO NOTHING RETURNING definition_id",
                (
                    record.definition_id,
                    record.workflow_name,
                    record.workflow_version,
                    record.schema_version,
                    record.definition_hash,
                    record.action_catalog_digest,
                    json.dumps(dict(record.resolved_action_versions)),
                    record.origin.value,
                    json.dumps(dict(record.workflow_document)),
                    record.visibility.value,
                    record.lifecycle.value,
                    record.owner_ref,
                    record.derived_from,
                    record.source_ref,
                    record.created_at,
                ),
            )
            if await cursor.fetchone() is None:
                existing = await self._get(connection, record.definition_id)
                if existing is None or not _same_definition_except_created_at(existing, record):
                    raise WorkflowDefinitionConflictError(
                        f"definition {record.definition_id!r} is immutable"
                    )
                stored = existing
            await enqueue_projection_upsert(
                connection,
                projection_kind="workflow_definition",
                principal_id=stored.owner_ref or "system",
                record_id=stored.definition_id,
            )
        return stored

    async def get(self, *, definition_id: str) -> WorkflowDefinitionRecord | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            return await self._get(connection, definition_id)

    async def _get(
        self, connection: psycopg.AsyncConnection[Any], definition_id: str
    ) -> WorkflowDefinitionRecord | None:
        cursor = await connection.execute(
            _DEFINITION_SELECT + " WHERE definition_id = %s",
            (definition_id,),
        )
        row = await cursor.fetchone()
        return _definition(row) if row is not None else None

    async def list_visible(
        self, *, principal_id: str, team_refs: Sequence[str] = ()
    ) -> tuple[WorkflowDefinitionRecord, ...]:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                _DEFINITION_SELECT + " WHERE visibility = 'global' "
                "OR (visibility = 'private' AND owner_ref = %s) "
                "OR (visibility = 'team' AND owner_ref = ANY(%s::text[])) "
                "ORDER BY workflow_name, workflow_version",
                (principal_id, list(team_refs)),
            )
            return tuple(_definition(row) for row in await cursor.fetchall())


class PostgresWorkflowBindingStore(_PostgresBase):
    async def create(self, record: WorkflowBindingRecord) -> WorkflowBindingRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            try:
                await connection.execute(
                    "INSERT INTO workflow_binding "
                    "(principal_id, binding_id, definition_id, trigger, enabled, scope_ref, "
                    "cron_expression, timezone, signal_type, parameters, revision, created_at, "
                    "updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, "
                    "1, %s, %s)",
                    (
                        record.principal_id,
                        record.binding_id,
                        record.definition_id,
                        record.trigger.value,
                        record.enabled,
                        record.scope_ref,
                        record.cron_expression,
                        record.timezone,
                        record.signal_type,
                        json.dumps(dict(record.parameters)),
                        record.created_at,
                        record.updated_at,
                    ),
                )
            except (psycopg.errors.UniqueViolation, psycopg.errors.ForeignKeyViolation) as exc:
                raise WorkflowDefinitionConflictError(
                    f"binding {record.binding_id!r} conflicts"
                ) from exc
            await enqueue_projection_upsert(
                connection,
                projection_kind="workflow_binding",
                principal_id=record.principal_id,
                record_id=record.binding_id,
            )
        return _with_binding_revision(record, 1)

    async def list_for_principal(self, *, principal_id: str) -> tuple[WorkflowBindingRecord, ...]:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                _BINDING_SELECT + " WHERE principal_id = %s ORDER BY binding_id",
                (principal_id,),
            )
            return tuple(_binding(row) for row in await cursor.fetchall())

    async def put(
        self, record: WorkflowBindingRecord, *, expected_revision: int
    ) -> WorkflowBindingRecord:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE workflow_binding SET definition_id = %s, trigger = %s, enabled = %s, "
                "scope_ref = %s, cron_expression = %s, timezone = %s, signal_type = %s, "
                "parameters = %s::jsonb, revision = revision + 1, updated_at = %s "
                "WHERE principal_id = %s AND binding_id = %s AND revision = %s "
                "RETURNING revision",
                (
                    record.definition_id,
                    record.trigger.value,
                    record.enabled,
                    record.scope_ref,
                    record.cron_expression,
                    record.timezone,
                    record.signal_type,
                    json.dumps(dict(record.parameters)),
                    record.updated_at,
                    record.principal_id,
                    record.binding_id,
                    expected_revision,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                raise WorkflowDefinitionConflictError(
                    "binding revision mismatch or record not found"
                )
            revision = int(row["revision"])
            await enqueue_projection_upsert(
                connection,
                projection_kind="workflow_binding",
                principal_id=record.principal_id,
                record_id=record.binding_id,
            )
        return _with_binding_revision(record, revision)

    async def delete(self, *, principal_id: str, binding_id: str) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await connection.execute(
                "INSERT INTO user_context_projection_delete_queue (object_id) "
                "SELECT 'workflow-binding:' || principal_id || ':' || binding_id "
                "FROM workflow_binding WHERE principal_id = %s AND binding_id = %s "
                "ON CONFLICT (object_id) DO NOTHING",
                (principal_id, binding_id),
            )
            cursor = await connection.execute(
                "DELETE FROM workflow_binding WHERE principal_id = %s AND binding_id = %s "
                "RETURNING binding_id",
                (principal_id, binding_id),
            )
            return await cursor.fetchone() is not None


_DEFINITION_SELECT = (
    "SELECT definition_id, workflow_name, workflow_version, schema_version, "
    "definition_hash, action_catalog_digest, resolved_action_versions, origin, "
    "workflow_document, visibility, lifecycle, owner_ref, derived_from, source_ref, "
    "created_at FROM workflow_definition"
)
_BINDING_SELECT = (
    "SELECT principal_id, binding_id, definition_id, trigger, enabled, scope_ref, "
    "cron_expression, timezone, signal_type, parameters, revision, created_at, updated_at "
    "FROM workflow_binding"
)


def _same_definition_except_created_at(
    existing: WorkflowDefinitionRecord,
    candidate: WorkflowDefinitionRecord,
) -> bool:
    return existing == replace(candidate, created_at=existing.created_at)


def _definition(row: dict[str, Any]) -> WorkflowDefinitionRecord:
    return WorkflowDefinitionRecord(
        definition_id=str(row["definition_id"]),
        workflow_name=str(row["workflow_name"]),
        workflow_version=str(row["workflow_version"]),
        schema_version=str(row["schema_version"]),
        definition_hash=str(row["definition_hash"]),
        action_catalog_digest=str(row["action_catalog_digest"]),
        resolved_action_versions=dict(row["resolved_action_versions"]),
        workflow_document=dict(row["workflow_document"]),
        origin=WorkflowOrigin(str(row["origin"])),
        visibility=WorkflowVisibility(str(row["visibility"])),
        lifecycle=WorkflowLifecycle(str(row["lifecycle"])),
        owner_ref=(str(row["owner_ref"]) if row["owner_ref"] else None),
        derived_from=(str(row["derived_from"]) if row["derived_from"] else None),
        source_ref=(str(row["source_ref"]) if row["source_ref"] else None),
        created_at=row["created_at"],
    )


def _with_binding_revision(record: WorkflowBindingRecord, revision: int) -> WorkflowBindingRecord:
    return WorkflowBindingRecord(
        binding_id=record.binding_id,
        principal_id=record.principal_id,
        definition_id=record.definition_id,
        trigger=record.trigger,
        enabled=record.enabled,
        created_at=record.created_at,
        updated_at=record.updated_at,
        revision=revision,
        scope_ref=record.scope_ref,
        cron_expression=record.cron_expression,
        timezone=record.timezone,
        signal_type=record.signal_type,
        parameters=dict(record.parameters),
    )


def _binding(row: dict[str, Any]) -> WorkflowBindingRecord:
    return WorkflowBindingRecord(
        binding_id=str(row["binding_id"]),
        principal_id=str(row["principal_id"]),
        definition_id=str(row["definition_id"]),
        trigger=WorkflowBindingTrigger(str(row["trigger"])),
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        revision=int(row["revision"]),
        scope_ref=(str(row["scope_ref"]) if row["scope_ref"] else None),
        cron_expression=(str(row["cron_expression"]) if row["cron_expression"] else None),
        timezone=(str(row["timezone"]) if row["timezone"] else None),
        signal_type=(str(row["signal_type"]) if row["signal_type"] else None),
        parameters=dict(row["parameters"]),
    )


__all__ = [
    "PostgresWorkflowBindingStore",
    "PostgresWorkflowDefinitionStore",
    "PostgresWorkflowDefinitionStoreConfig",
]
