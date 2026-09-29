"""Durable Operator writes for principal-owned Workflow drafts and bindings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, cast

import psycopg
from fdai_service_contracts import JsonObject
from psycopg.rows import dict_row
from starlette.exceptions import HTTPException

from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
)

_AUTHORING_SOURCE: Final = "postgresql:workflow-authoring"
_DEFINITION_PREFIX: Final = "workflow-definition:user"
_BINDING_PREFIX: Final = "workflow-binding"
_VALID_TRIGGERS: Final = frozenset({"deck_open", "schedule", "signal"})


@dataclass(frozen=True, slots=True)
class WorkflowAuthoringResult:
    """Committed authoring response returned to the Console."""

    payload: JsonObject
    status_code: int
    revision: str


class PostgresWorkflowAuthoringStore:
    """Write only principal-owned private workflow drafts and bindings.

    The store is intentionally narrower than the proposal outbox: it commits the Console's
    reviewed private draft and automation binding records so subsequent reads show the durable
    result. It never writes built-ins, shared definitions, publication state, enablement, or any
    runtime Process authority.
    """

    def __init__(self, store: PostgresFamilyStore) -> None:
        self._store = store

    async def create_definition(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        expected_revision: str,
        payload: Mapping[str, object],
    ) -> WorkflowAuthoringResult:
        if expected_revision != "new":
            raise HTTPException(
                status_code=409, detail="workflow draft create expects If-Match: new"
            )
        if payload.get("confirmed") is not True:
            raise HTTPException(
                status_code=400, detail="workflow draft creation requires confirmation"
            )
        workflow = _mapping(payload.get("workflow"), "workflow")
        now = datetime.now(UTC)
        document = _workflow_document(workflow)
        definition_hash = _digest(document)
        action_versions = _resolved_action_versions(document)
        definition_id = _definition_id(principal_id, definition_hash)
        request_hash = _digest({"workflow": document, "confirmed": True})
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            replay = await self._audit_replay(
                connection,
                principal_id=principal_id,
                operation="workflow-definition.create",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if replay is not None:
                return WorkflowAuthoringResult(replay, 200, _json_revision(replay))
            await connection.execute(
                """
                INSERT INTO workflow_definition (
                    definition_id, workflow_name, workflow_version, schema_version,
                    definition_hash, action_catalog_digest, resolved_action_versions,
                    workflow_document, origin, visibility, lifecycle, owner_ref,
                    derived_from, source_ref, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, 'user',
                    'private', 'draft', %s, NULL, %s, %s)
                ON CONFLICT (definition_id) DO NOTHING
                """,
                (
                    definition_id,
                    _required_text(document, "name"),
                    _required_text(document, "version"),
                    _required_text(document, "schema_version"),
                    definition_hash,
                    _action_catalog_digest(action_versions),
                    json.dumps(action_versions, sort_keys=True, separators=(",", ":")),
                    json.dumps(document, sort_keys=True, separators=(",", ":")),
                    principal_id,
                    f"operator-console:{idempotency_key}",
                    now,
                ),
            )
            row = await self._owned_definition(connection, principal_id, definition_id)
            if row is None:
                raise HTTPException(status_code=409, detail="workflow draft was not committed")
            response: JsonObject = {
                "valid": True,
                "definition": _definition_response(row),
                "duplicate": False,
            }
            await self._write_audit(
                connection,
                principal_id=principal_id,
                operation="workflow-definition.create",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                result=response,
            )
        return WorkflowAuthoringResult(response, 201, _json_revision(response))

    async def create_binding(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        expected_revision: str,
        payload: Mapping[str, object],
    ) -> WorkflowAuthoringResult:
        if expected_revision != "new":
            raise HTTPException(
                status_code=409, detail="workflow binding create expects If-Match: new"
            )
        if payload.get("confirmed") is not True:
            raise HTTPException(
                status_code=400, detail="workflow binding creation requires confirmation"
            )
        body = _binding_input(payload)
        request_hash = _digest(body)
        binding_id = _binding_id(principal_id, body)
        now = datetime.now(UTC)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            replay = await self._audit_replay(
                connection,
                principal_id=principal_id,
                operation="workflow-binding.create",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if replay is not None:
                return WorkflowAuthoringResult(replay, 200, _json_revision(replay))
            await self._require_visible_definition(
                connection, principal_id, str(body["definition_id"])
            )
            await connection.execute(
                """
                INSERT INTO workflow_binding (
                    principal_id, binding_id, definition_id, trigger, enabled, scope_ref,
                    cron_expression, timezone, signal_type, parameters, revision,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, FALSE, %s, %s, %s, %s, %s::jsonb, 1, %s, %s)
                ON CONFLICT (principal_id, binding_id) DO NOTHING
                """,
                (
                    principal_id,
                    binding_id,
                    str(body["definition_id"]),
                    body["trigger"],
                    body.get("scope_ref"),
                    body.get("cron_expression"),
                    body.get("timezone"),
                    body.get("signal_type"),
                    json.dumps(body["parameters"], sort_keys=True, separators=(",", ":")),
                    now,
                    now,
                ),
            )
            row = await self._owned_binding(connection, principal_id, binding_id)
            if row is None:
                raise HTTPException(status_code=409, detail="workflow binding was not committed")
            response = _binding_response(row)
            await self._write_audit(
                connection,
                principal_id=principal_id,
                operation="workflow-binding.create",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                result=response,
            )
        return WorkflowAuthoringResult(response, 201, str(response["revision"]))

    async def update_binding(
        self,
        *,
        principal_id: str,
        binding_id: str,
        idempotency_key: str,
        expected_revision: str,
        payload: Mapping[str, object],
    ) -> WorkflowAuthoringResult:
        revision = _revision(expected_revision)
        body = _binding_input(payload)
        request_hash = _digest({"binding_id": binding_id, **body, "revision": revision})
        now = datetime.now(UTC)
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            replay = await self._audit_replay(
                connection,
                principal_id=principal_id,
                operation="workflow-binding.update",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if replay is not None:
                return WorkflowAuthoringResult(replay, 200, _json_revision(replay))
            await self._require_visible_definition(
                connection, principal_id, str(body["definition_id"])
            )
            cursor = await connection.execute(
                """
                UPDATE workflow_binding
                SET definition_id=%s, trigger=%s, enabled=FALSE, scope_ref=%s,
                    cron_expression=%s, timezone=%s, signal_type=%s, parameters=%s::jsonb,
                    revision=revision + 1, updated_at=%s
                WHERE principal_id=%s AND binding_id=%s AND revision=%s
                RETURNING principal_id, binding_id, definition_id, trigger, enabled, scope_ref,
                    cron_expression, timezone, signal_type, parameters, revision
                """,
                (
                    str(body["definition_id"]),
                    body["trigger"],
                    body.get("scope_ref"),
                    body.get("cron_expression"),
                    body.get("timezone"),
                    body.get("signal_type"),
                    json.dumps(body["parameters"], sort_keys=True, separators=(",", ":")),
                    now,
                    principal_id,
                    binding_id,
                    revision,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=409, detail="workflow binding revision mismatch")
            response = _binding_response(row)
            await self._write_audit(
                connection,
                principal_id=principal_id,
                operation="workflow-binding.update",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                result=response,
            )
        return WorkflowAuthoringResult(response, 200, str(response["revision"]))

    async def delete_binding(
        self,
        *,
        principal_id: str,
        binding_id: str,
        idempotency_key: str,
        expected_revision: str,
    ) -> WorkflowAuthoringResult:
        revision = _revision(expected_revision)
        request_hash = _digest({"binding_id": binding_id, "revision": revision})
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            replay = await self._audit_replay(
                connection,
                principal_id=principal_id,
                operation="workflow-binding.delete",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if replay is not None:
                return WorkflowAuthoringResult(replay, 200, _json_revision(replay))
            cursor = await connection.execute(
                """
                DELETE FROM workflow_binding
                WHERE principal_id=%s AND binding_id=%s AND revision=%s
                RETURNING binding_id, revision
                """,
                (principal_id, binding_id, revision),
            )
            row = await cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=409, detail="workflow binding revision mismatch")
            response: JsonObject = {
                "deleted": True,
                "binding_id": str(row["binding_id"]),
                "revision": int(row["revision"]),
            }
            await self._write_audit(
                connection,
                principal_id=principal_id,
                operation="workflow-binding.delete",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                result=response,
            )
        return WorkflowAuthoringResult(response, 200, str(response["revision"]))

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        try:
            return await psycopg.AsyncConnection.connect(
                self._store._config.dsn,
                row_factory=dict_row,
                connect_timeout=self._store._config.connect_timeout_s,
            )
        except psycopg.Error as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative workflow authoring store is unavailable"
            ) from exc

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._store._config.statement_timeout_ms),),
        )

    async def _audit_replay(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        *,
        principal_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> JsonObject | None:
        cursor = await connection.execute(
            """
            SELECT request_hash, result
            FROM operator_workflow_authoring_audit
            WHERE principal_id=%s AND operation=%s AND idempotency_key=%s
            """,
            (principal_id, operation, idempotency_key),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise HTTPException(
                status_code=409, detail="workflow authoring idempotency key conflict"
            )
        result = dict(row["result"])
        result["duplicate"] = True
        return cast(JsonObject, result)

    async def _write_audit(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        *,
        principal_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        result: Mapping[str, object],
    ) -> None:
        await connection.execute(
            """
            INSERT INTO operator_workflow_authoring_audit (
                principal_id, operation, idempotency_key, request_hash, result, recorded_at
            ) VALUES (%s, %s, %s, %s, %s::jsonb, NOW())
            """,
            (
                principal_id,
                operation,
                idempotency_key,
                request_hash,
                json.dumps(dict(result), sort_keys=True, separators=(",", ":")),
            ),
        )

    async def _require_visible_definition(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        principal_id: str,
        definition_id: str,
    ) -> None:
        cursor = await connection.execute(
            """
            SELECT origin, visibility, owner_ref
            FROM workflow_definition
            WHERE definition_id=%s
              AND (visibility='global' OR (visibility='private' AND owner_ref=%s))
            """,
            (definition_id, principal_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="workflow definition is not visible")
        if row["origin"] == "upstream" and row["visibility"] != "global":
            raise HTTPException(status_code=409, detail="built-in workflow definition is read-only")

    async def _owned_definition(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        principal_id: str,
        definition_id: str,
    ) -> Mapping[str, object] | None:
        cursor = await connection.execute(
            """
            SELECT definition_id, workflow_name, lifecycle, owner_ref
            FROM workflow_definition
            WHERE definition_id=%s AND origin='user' AND visibility='private' AND owner_ref=%s
            """,
            (definition_id, principal_id),
        )
        return await cursor.fetchone()

    async def _owned_binding(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        principal_id: str,
        binding_id: str,
    ) -> Mapping[str, object] | None:
        cursor = await connection.execute(
            """
            SELECT principal_id, binding_id, definition_id, trigger, enabled, scope_ref,
                cron_expression, timezone, signal_type, parameters, revision
            FROM workflow_binding
            WHERE principal_id=%s AND binding_id=%s
            """,
            (principal_id, binding_id),
        )
        return await cursor.fetchone()


def _workflow_document(value: Mapping[str, object]) -> JsonObject:
    document = dict(value)
    for field in ("schema_version", "name", "version"):
        _required_text(document, field)
    steps = document.get("steps")
    if not isinstance(steps, list) or not steps:
        raise HTTPException(status_code=422, detail="workflow draft requires at least one step")
    if _required_text(document, "default_mode") != "shadow":
        raise HTTPException(status_code=409, detail="private workflow drafts must remain shadow")
    return cast(JsonObject, document)


def _binding_input(payload: Mapping[str, object]) -> JsonObject:
    if payload.get("confirmed") not in {None, True}:
        raise HTTPException(
            status_code=400, detail="workflow binding request has invalid confirmation"
        )
    definition_id = _required_text(payload, "definition_id")
    trigger = _required_text(payload, "trigger")
    if trigger not in _VALID_TRIGGERS:
        raise HTTPException(status_code=400, detail="workflow binding trigger is invalid")
    body: dict[str, object] = {
        "definition_id": definition_id,
        "trigger": trigger,
        "scope_ref": _optional_text(payload, "scope_ref"),
        "parameters": _scalar_mapping(payload.get("parameters", {})),
    }
    if trigger == "schedule":
        body["cron_expression"] = _required_text(payload, "cron_expression")
        body["timezone"] = _required_text(payload, "timezone")
        body["signal_type"] = None
    elif trigger == "signal":
        body["cron_expression"] = None
        body["timezone"] = None
        body["signal_type"] = _required_text(payload, "signal_type")
    else:
        body["cron_expression"] = None
        body["timezone"] = None
        body["signal_type"] = None
    return cast(JsonObject, body)


def _resolved_action_versions(document: Mapping[str, object]) -> dict[str, str]:
    refs: set[str] = set()
    for raw in cast(list[object], document["steps"]):
        if isinstance(raw, Mapping):
            ref = raw.get("action_type_ref")
            if isinstance(ref, str) and ref:
                refs.add(ref)
    return {ref: "unresolved" for ref in sorted(refs)}


def _definition_response(row: Mapping[str, object]) -> JsonObject:
    return {
        "definition_id": str(row["definition_id"]),
        "workflow_name": str(row["workflow_name"]),
        "lifecycle": str(row["lifecycle"]),
        "owner_ref": str(row["owner_ref"]),
    }


def _binding_response(row: Mapping[str, object]) -> JsonObject:
    raw_parameters = row["parameters"]
    if not isinstance(raw_parameters, Mapping):
        raise HTTPException(status_code=503, detail="workflow binding parameters are malformed")
    revision = row["revision"]
    if not isinstance(revision, int):
        raise HTTPException(status_code=503, detail="workflow binding revision is malformed")
    return {
        "binding_id": str(row["binding_id"]),
        "definition_id": str(row["definition_id"]),
        "trigger": str(row["trigger"]),
        "enabled": bool(row["enabled"]),
        "cron_expression": _row_optional_text(row, "cron_expression"),
        "timezone": _row_optional_text(row, "timezone"),
        "signal_type": _row_optional_text(row, "signal_type"),
        "scope_ref": _row_optional_text(row, "scope_ref"),
        "parameters": cast(JsonObject, _scalar_mapping(raw_parameters)),
        "revision": revision,
    }


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise HTTPException(status_code=400, detail=f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _required_text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise HTTPException(status_code=400, detail=f"{key} must be a bounded non-empty string")
    return value.strip()


def _optional_text(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise HTTPException(status_code=400, detail=f"{key} must be a bounded string")
    return value.strip()


def _row_optional_text(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    return None if value is None else str(value)


def _scalar_mapping(value: object) -> dict[str, str | int | float | bool]:
    if not isinstance(value, Mapping):
        raise HTTPException(status_code=400, detail="workflow binding parameters must be an object")
    out: dict[str, str | int | float | bool] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or not isinstance(raw_value, str | int | float | bool):
            raise HTTPException(
                status_code=400, detail="workflow binding parameters must be scalar"
            )
        out[raw_key] = raw_value
    return out


def _revision(value: str) -> int:
    try:
        revision = int(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="If-Match must be a numeric binding revision"
        ) from exc
    if revision < 1:
        raise HTTPException(status_code=400, detail="If-Match must be a positive binding revision")
    return revision


def _digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _action_catalog_digest(action_versions: Mapping[str, str]) -> str:
    return _digest({"resolved_action_versions": dict(action_versions)})


def _json_revision(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _definition_id(principal_id: str, definition_hash: str) -> str:
    owner = hashlib.sha256(principal_id.encode()).hexdigest()[:16]
    document = definition_hash.removeprefix("sha256:")[:16]
    return f"{_DEFINITION_PREFIX}:{owner}:{document}"


def _binding_id(principal_id: str, body: Mapping[str, object]) -> str:
    fingerprint = _digest({"principal_id": principal_id, **dict(body)}).removeprefix("sha256:")[:24]
    return f"{_BINDING_PREFIX}:{fingerprint}"


__all__ = [
    "PostgresWorkflowAuthoringStore",
    "WorkflowAuthoringResult",
]
