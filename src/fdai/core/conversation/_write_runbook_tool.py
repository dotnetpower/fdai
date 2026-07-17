"""Governed runbook execution console tool."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from fdai.core.conversation._write_audit import AuditWriter
from fdai.core.conversation.session import Principal, Role
from fdai.core.conversation.tools import SideEffectClass, ToolResult
from fdai.shared.providers.runbook_registry import (
    RunbookError,
    RunbookNotFoundError,
    RunbookRegistry,
    RunbookResult,
)


class RunRunbookTool:
    """Execute one registered runbook in dry-run or live mode."""

    name = "run_runbook"
    description = (
        "Execute one runbook registered under docs/runbooks/. dry_run=True "
        "is a Contributor-floor plan; dry_run=False is a live invocation and "
        "requires Owner."
    )
    rbac_floor: Role = Role.CONTRIBUTOR
    side_effect_class: SideEffectClass = "execute"

    def __init__(self, *, registry: RunbookRegistry, audit_writer: AuditWriter) -> None:
        self._registry = registry
        self._audit_writer = audit_writer

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        import asyncio

        runbook_name = str(arguments.get("name", "")).strip()
        raw_params = arguments.get("params", {})
        dry_run_raw = arguments.get("dry_run", True)
        if not runbook_name:
            return ToolResult(status="error", preview="run_runbook requires a non-empty 'name'")
        if not isinstance(raw_params, Mapping):
            return ToolResult(status="error", preview="run_runbook 'params' MUST be a mapping")
        if not isinstance(dry_run_raw, bool):
            return ToolResult(status="error", preview="run_runbook 'dry_run' MUST be a boolean")
        dry_run: bool = dry_run_raw
        if not dry_run and principal.role is not Role.OWNER:
            audit_id = self._audit_writer.write_runbook_entry(
                name=runbook_name,
                params=raw_params,
                principal=principal,
                dry_run=dry_run,
                outcome="error",
                summary="live run refused; caller is not Owner",
                error_kind="rbac_below_owner_for_live",
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id},
                preview=(
                    "run_runbook: live invocation requires Owner "
                    f"(caller role={principal.role.value})"
                ),
                evidence_refs=(f"audit:{audit_id}",),
            )
        if runbook_name not in self._registry.names():
            available = ", ".join(self._registry.names()) or "(none registered)"
            audit_id = self._audit_writer.write_runbook_entry(
                name=runbook_name,
                params=raw_params,
                principal=principal,
                dry_run=dry_run,
                outcome="error",
                summary=f"unknown runbook; available: {available}",
                error_kind="not_found",
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id, "available": list(self._registry.names())},
                preview=f"run_runbook: unknown runbook {runbook_name!r}",
                evidence_refs=(f"audit:{audit_id}",),
            )
        try:
            result: RunbookResult = asyncio.run(
                self._registry.execute(
                    name=runbook_name,
                    params=dict(raw_params),
                    dry_run=dry_run,
                )
            )
        except RunbookNotFoundError:
            audit_id = self._audit_writer.write_runbook_entry(
                name=runbook_name,
                params=raw_params,
                principal=principal,
                dry_run=dry_run,
                outcome="error",
                summary="runbook disappeared between name check and execute",
                error_kind="not_found",
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id},
                preview=(
                    f"run_runbook: {runbook_name!r} disappeared between "
                    "existence check and dispatch"
                ),
                evidence_refs=(f"audit:{audit_id}",),
            )
        except RunbookError as exc:
            audit_id = self._audit_writer.write_runbook_entry(
                name=runbook_name,
                params=raw_params,
                principal=principal,
                dry_run=dry_run,
                outcome="error",
                summary=str(exc),
                error_kind=exc.kind,
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id, "error_kind": exc.kind},
                preview=f"run_runbook[{runbook_name}]: {exc}",
                evidence_refs=(f"audit:{audit_id}",),
            )
        outcome: Literal["ok", "error", "abstain"] = "ok" if result.ok else "error"
        audit_id = self._audit_writer.write_runbook_entry(
            name=runbook_name,
            params=raw_params,
            principal=principal,
            dry_run=dry_run,
            outcome=outcome,
            summary=result.summary,
            detail=dict(result.detail),
        )
        return ToolResult(
            status=outcome,
            data={
                "audit_id": audit_id,
                "runbook": runbook_name,
                "dry_run": dry_run,
                "summary": result.summary,
                "detail": dict(result.detail),
            },
            preview=(
                f"run_runbook[{runbook_name}]: {'dry-run ' if dry_run else ''}"
                f"{'ok' if result.ok else 'failed'} - {result.summary}"
            ),
            evidence_refs=(f"audit:{audit_id}",),
        )
