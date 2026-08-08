"""Read-only operator-memory console tool."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.conversation.session import Principal, Role
from fdai.core.conversation.tools import SideEffectClass, ToolResult, _optional_int, _require_str
from fdai.core.operator_memory.store import OperatorMemoryStore
from fdai.core.operator_memory.types import ScopeKind


class QueryOperatorMemoryTool:
    """Return active operator-memory entries for a bounded scope."""

    name = "query_operator_memory"
    description = (
        "Return active operator-memory entries for a (scope_kind, scope_ref). "
        "Read-only; superseded / expired rows are filtered."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, store: OperatorMemoryStore) -> None:
        self._store = store

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        import asyncio

        raw_scope_kind = _require_str(arguments, "scope_kind").strip()
        raw_scope_ref = _require_str(arguments, "scope_ref").strip()
        if not raw_scope_kind:
            return ToolResult(
                status="error",
                preview="query_operator_memory requires a non-empty 'scope_kind'",
            )
        if not raw_scope_ref:
            return ToolResult(
                status="error",
                preview="query_operator_memory requires a non-empty 'scope_ref'",
            )
        try:
            scope_kind = ScopeKind(raw_scope_kind)
        except ValueError:
            allowed = ", ".join(sorted(kind.value for kind in ScopeKind))
            return ToolResult(
                status="error",
                preview=f"query_operator_memory 'scope_kind' MUST be one of: {allowed}",
            )
        limit = _optional_int(arguments, "limit", default=20, minimum=1, maximum=100)
        try:
            entries = asyncio.run(
                self._store.list_active_for_scope(
                    scope_kind=scope_kind,
                    scope_ref=raw_scope_ref,
                )
            )
        except RuntimeError as exc:
            return ToolResult(
                status="error",
                preview=f"query_operator_memory event-loop reuse: {exc}",
            )
        projected = [_project_memory_entry(entry) for entry in entries[:limit]]
        return ToolResult(
            status="ok" if projected else "abstain",
            data={
                "scope_kind": scope_kind.value,
                "scope_ref": raw_scope_ref,
                "limit": limit,
                "total_active": len(entries),
                "entries": projected,
            },
            preview=(
                f"query_operator_memory[{scope_kind.value}={raw_scope_ref}]: "
                f"{len(projected)} active entry(ies)"
            ),
            evidence_refs=tuple(f"operator-memory:{entry['id']}" for entry in projected),
        )


def _project_memory_entry(entry: Any) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "scope_kind": _enum_value(entry.scope_kind),
        "scope_ref": entry.scope_ref,
        "category": _enum_value(entry.category),
        "body": entry.body,
        "source_event": _enum_value(entry.source_event),
        "source_ref": entry.source_ref,
        "author": entry.author,
        "approved_by": entry.approved_by,
        "created_at": entry.created_at.isoformat(),
        "ttl_seconds": getattr(entry, "ttl_seconds", None),
    }


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)
