"""Principal-scoped Workflow definition catalog read from the Operator-owned PostgreSQL store.

Responsibility:
Serve ``workflow-definition.list``: the Built-in, Shared, and Mine definition groups plus the
authenticated principal's own automation bindings.

Boundary:
Module-owned SQL runs through the family store's bounded transport. HTTP parsing, RBAC, and
proposal writes stay in the workflow route family and its proposal outbox.

Authority and state:
SELECT-only reads of ``workflow_definition`` and ``workflow_binding`` under the ``fdai_operator``
grant. The reader never creates, publishes, binds, enables, promotes, or executes a definition. A
record outside the principal scope, a malformed record, or a store failure fails the whole read
closed instead of returning a partial catalog.

Dependencies:
Workflow-family read contracts and an injected bounded row fetcher.

Deployment:
Runs inside the independently deployed Operator Service; local and deployed composition use the
same reader and the same service migration grant.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

from fdai_service_contracts import JsonObject, JsonValue

from fdai_operator_service.families.workflow.contracts import (
    ProjectionProvenance,
    WorkflowReadResult,
)
from fdai_operator_service.postgres_family_models import PostgresFamilyStoreUnavailableError

RowFetcher = Callable[[str, Mapping[str, object]], Awaitable[list[dict[str, Any]]]]

MAX_VISIBLE_DEFINITIONS: Final = 200
MAX_PRINCIPAL_BINDINGS: Final = 200
WORKFLOW_DEFINITION_CATALOG_SOURCE: Final = "postgresql:workflow_definition+workflow_binding"

# Global definitions are visible to every authenticated principal; a private definition only to
# its owner. Team visibility stays excluded until a team-membership source is bound.
VISIBLE_DEFINITIONS_SQL: Final = (
    "SELECT definition_id, workflow_name, workflow_version, schema_version, definition_hash,"
    " action_catalog_digest, resolved_action_versions, workflow_document, origin, visibility,"
    " lifecycle, owner_ref, derived_from"
    " FROM workflow_definition"
    " WHERE visibility = 'global'"
    " OR (visibility = 'private' AND owner_ref = %(principal_id)s)"
    " ORDER BY workflow_name, workflow_version, definition_id"
    " LIMIT %(limit)s"
)
PRINCIPAL_BINDINGS_SQL: Final = (
    "SELECT principal_id, binding_id, definition_id, trigger, enabled, scope_ref,"
    " cron_expression, timezone, signal_type, parameters, revision"
    " FROM workflow_binding"
    " WHERE principal_id = %(principal_id)s"
    " ORDER BY binding_id"
    " LIMIT %(limit)s"
)

_ORIGINS: Final = frozenset({"upstream", "tenant", "user"})
_VISIBILITIES: Final = frozenset({"global", "team", "private"})
_LIFECYCLES: Final = frozenset(
    {"draft", "validated", "shadow", "published", "suspended", "retired"}
)
_TRIGGERS: Final = frozenset({"deck_open", "schedule", "signal"})
_GROUPS: Final = ("built_in", "shared", "mine")


@dataclass(frozen=True, slots=True)
class PostgresWorkflowDefinitionCatalog:
    """Read one authenticated principal's workflow definition catalog."""

    fetch_all: RowFetcher

    async def read(self, principal_id: str) -> WorkflowReadResult:
        """Return the grouped catalog bound to ``principal_id``.

        Raises ``PostgresFamilyStoreUnavailableError`` when the store is unreachable or its role
        lacks the read grant, when a bound is exceeded, or when any record is malformed or lies
        outside the principal scope.
        """
        definition_rows = await self.fetch_all(
            VISIBLE_DEFINITIONS_SQL,
            {"principal_id": principal_id, "limit": MAX_VISIBLE_DEFINITIONS + 1},
        )
        binding_rows = await self.fetch_all(
            PRINCIPAL_BINDINGS_SQL,
            {"principal_id": principal_id, "limit": MAX_PRINCIPAL_BINDINGS + 1},
        )
        payload = project_workflow_definition_catalog(
            definition_rows,
            binding_rows,
            principal_id=principal_id,
        )
        return WorkflowReadResult(
            payload=payload,
            provenance=ProjectionProvenance(
                source_ref=WORKFLOW_DEFINITION_CATALOG_SOURCE,
                revision=canonical_digest(payload),
            ),
        )


def project_workflow_definition_catalog(
    definition_rows: Sequence[Mapping[str, object]],
    binding_rows: Sequence[Mapping[str, object]],
    *,
    principal_id: str,
) -> JsonObject:
    """Group visible definitions and project the principal's bindings, failing closed.

    The SQL predicates are the primary principal-scope boundary. This projection repeats the
    same visibility and ownership rules so a predicate regression cannot disclose another
    principal's private definition or binding.
    """
    if len(definition_rows) > MAX_VISIBLE_DEFINITIONS:
        raise _unavailable(
            f"visible workflow definitions exceed the {MAX_VISIBLE_DEFINITIONS}-record read bound"
        )
    if len(binding_rows) > MAX_PRINCIPAL_BINDINGS:
        raise _unavailable(
            f"principal workflow bindings exceed the {MAX_PRINCIPAL_BINDINGS}-record read bound"
        )
    groups: dict[str, list[JsonValue]] = {group: [] for group in _GROUPS}
    for row in definition_rows:
        group, entry = _definition_entry(row, principal_id=principal_id)
        groups[group].append(entry)
    bindings: list[JsonValue] = [
        _binding_entry(row, principal_id=principal_id) for row in binding_rows
    ]
    counts: dict[str, JsonValue] = {group: len(groups[group]) for group in _GROUPS}
    return {
        "groups": cast(dict[str, JsonValue], groups),
        "bindings": bindings,
        "counts": counts,
    }


def canonical_digest(payload: JsonObject) -> str:
    """Return the SHA-256 revision of one canonical JSON projection."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _definition_entry(
    row: Mapping[str, object],
    *,
    principal_id: str,
) -> tuple[str, JsonObject]:
    origin = _member(row, "origin", _ORIGINS)
    visibility = _member(row, "visibility", _VISIBILITIES)
    owner_ref = _optional_text(row, "owner_ref")
    if not (visibility == "global" or (visibility == "private" and owner_ref == principal_id)):
        raise _unavailable("workflow definition read returned a record outside the principal scope")
    if origin == "upstream":
        group = "built_in"
    elif owner_ref == principal_id:
        group = "mine"
    else:
        group = "shared"
    workflow_name = _text(row, "workflow_name")
    return group, {
        "definition_id": _text(row, "definition_id"),
        "workflow_name": workflow_name,
        "workflow_version": _text(row, "workflow_version"),
        "schema_version": _text(row, "schema_version"),
        "definition_hash": _text(row, "definition_hash"),
        "action_catalog_digest": _text(row, "action_catalog_digest"),
        "origin": origin,
        "visibility": visibility,
        "lifecycle": _member(row, "lifecycle", _LIFECYCLES),
        # Only the caller's own owner reference is disclosed; Shared entries withhold theirs.
        "owner_ref": owner_ref if owner_ref == principal_id else None,
        "derived_from": _optional_text(row, "derived_from"),
        "resolved_action_versions": _string_mapping(row, "resolved_action_versions"),
        "workflow_document": _workflow_document(row, workflow_name=workflow_name),
    }


def _binding_entry(row: Mapping[str, object], *, principal_id: str) -> JsonObject:
    if row.get("principal_id") != principal_id:
        raise _unavailable("workflow binding read returned a record outside the principal scope")
    enabled = row.get("enabled")
    revision = row.get("revision")
    if not isinstance(enabled, bool):
        raise _unavailable("workflow binding enabled flag is malformed")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise _unavailable("workflow binding revision is malformed")
    return {
        "binding_id": _text(row, "binding_id"),
        "definition_id": _text(row, "definition_id"),
        "trigger": _member(row, "trigger", _TRIGGERS),
        "enabled": enabled,
        "cron_expression": _optional_text(row, "cron_expression"),
        "timezone": _optional_text(row, "timezone"),
        "signal_type": _optional_text(row, "signal_type"),
        "scope_ref": _optional_text(row, "scope_ref"),
        "parameters": _scalar_mapping(row, "parameters"),
        "revision": revision,
    }


def _workflow_document(row: Mapping[str, object], *, workflow_name: str) -> JsonObject:
    document = row.get("workflow_document")
    if (
        not isinstance(document, dict)
        or not document
        or document.get("name") != workflow_name
        or not isinstance(document.get("steps"), list)
    ):
        raise _unavailable("workflow definition document is malformed")
    return cast(JsonObject, document)


def _string_mapping(row: Mapping[str, object], key: str) -> JsonObject:
    value = row.get(key)
    if not isinstance(value, dict) or not all(
        isinstance(name, str) and isinstance(item, str) for name, item in value.items()
    ):
        raise _unavailable(f"workflow definition {key} is malformed")
    return cast(JsonObject, dict(value))


def _scalar_mapping(row: Mapping[str, object], key: str) -> JsonObject:
    value = row.get(key)
    if not isinstance(value, dict) or not all(
        isinstance(name, str) and isinstance(item, str | int | float | bool)
        for name, item in value.items()
    ):
        raise _unavailable(f"workflow binding {key} is malformed")
    return cast(JsonObject, dict(value))


def _member(row: Mapping[str, object], key: str, allowed: frozenset[str]) -> str:
    value = row.get(key)
    if not isinstance(value, str) or value not in allowed:
        raise _unavailable(f"workflow record {key} is malformed")
    return value


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _unavailable(f"workflow record {key} is malformed")
    return value


def _optional_text(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _unavailable(f"workflow record {key} is malformed")
    return value


def _unavailable(message: str) -> PostgresFamilyStoreUnavailableError:
    return PostgresFamilyStoreUnavailableError(f"authoritative {message}")


__all__ = [
    "MAX_PRINCIPAL_BINDINGS",
    "MAX_VISIBLE_DEFINITIONS",
    "PRINCIPAL_BINDINGS_SQL",
    "VISIBLE_DEFINITIONS_SQL",
    "WORKFLOW_DEFINITION_CATALOG_SOURCE",
    "PostgresWorkflowDefinitionCatalog",
    "RowFetcher",
    "canonical_digest",
    "project_workflow_definition_catalog",
]
