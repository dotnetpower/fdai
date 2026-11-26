"""Append-only audit writer for conversation write tools."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fdai.core.conversation.session import Principal
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.hil_registry import HilApprovalDecision, HilPendingItem


class AuditWriter:
    """Sync facade over an async audit store for console tools."""

    def __init__(self, *, audit_store: Any) -> None:
        self._audit_store = audit_store

    def write_simulation_entry(
        self,
        *,
        event: Event,
        principal: Principal,
        outcome: str,
        reason: str | None,
        citing_rule_ids: tuple[str, ...],
        pr_intents: tuple[Mapping[str, Any], ...],
        findings_summary: tuple[Mapping[str, Any], ...],
    ) -> str:
        audit_id = str(uuid4())
        entry: dict[str, Any] = {
            "audit_id": audit_id,
            "event_id": str(event.event_id),
            "action_kind": "console.simulate_change",
            "actor": principal.id,
            "actor_role": principal.role.value,
            "decision": outcome,
            "mode": Mode.SHADOW.value,
            "stage": "simulate",
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            "resource_type": _extract_resource_type(event),
            "citing_rule_ids": list(citing_rule_ids),
            "reason": reason or "",
            "pr_intents": [dict(intent) for intent in pr_intents],
            "findings": [dict(finding) for finding in findings_summary],
        }
        asyncio.run(self._audit_store.append_audit_entry(entry))
        return audit_id

    def write_approval_entry(
        self,
        *,
        item: HilPendingItem,
        principal: Principal,
        decision: HilApprovalDecision,
        outcome: str,
        justification: str,
        receipt_ref: str,
        already_recorded: bool,
    ) -> str:
        audit_id = str(uuid4())
        entry: dict[str, Any] = {
            "audit_id": audit_id,
            "event_id": item.event_id,
            "action_id": item.action_id,
            "action_kind": "console.approve_hil",
            "actor": principal.id,
            "actor_role": principal.role.value,
            "decision": decision.value,
            "outcome": outcome,
            "mode": Mode.SHADOW.value,
            "stage": "approve",
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            "idempotency_key": item.idempotency_key,
            "approval_id": item.approval_id,
            "submitter_oid": item.submitter_oid,
            "target_resource_ref": item.target_resource_ref,
            "citing_rule_ids": list(item.citing_rule_ids),
            "action_kind_dispatched": item.action_kind,
            "receipt_ref": receipt_ref,
            "already_recorded": already_recorded,
            "justification": justification,
        }
        asyncio.run(self._audit_store.append_audit_entry(entry))
        return audit_id

    def write_runbook_entry(
        self,
        *,
        name: str,
        params: Mapping[str, Any],
        principal: Principal,
        dry_run: bool,
        outcome: str,
        summary: str,
        detail: Mapping[str, Any] | None = None,
        error_kind: str | None = None,
    ) -> str:
        audit_id = str(uuid4())
        entry: dict[str, Any] = {
            "audit_id": audit_id,
            "action_kind": "console.run_runbook",
            "runbook_name": name,
            "actor": principal.id,
            "actor_role": principal.role.value,
            "decision": outcome,
            "dry_run": dry_run,
            "mode": Mode.SHADOW.value if dry_run else Mode.ENFORCE.value,
            "stage": "runbook",
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            "params": dict(params),
            "summary": summary,
            "detail": dict(detail or {}),
            "error_kind": error_kind or "",
        }
        asyncio.run(self._audit_store.append_audit_entry(entry))
        return audit_id

    def write_break_glass_entry(
        self,
        *,
        principal: Principal,
        outcome: str,
        reason_redacted: str,
        activated_at: datetime | None,
        expires_at: datetime | None,
        pager_receipt: str,
        refusal_kind: str | None = None,
    ) -> str:
        audit_id = str(uuid4())
        entry: dict[str, Any] = {
            "audit_id": audit_id,
            "action_kind": "console.activate_break_glass",
            "actor": principal.id,
            "actor_role": principal.role.value,
            "decision": outcome,
            "mode": Mode.SHADOW.value,
            "stage": "break_glass",
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            "reason": reason_redacted,
            "activated_at": activated_at.isoformat() if activated_at else None,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "pager_receipt": pager_receipt,
            "refusal_kind": refusal_kind or "",
        }
        asyncio.run(self._audit_store.append_audit_entry(entry))
        return audit_id


def _extract_resource_type(event: Event) -> str:
    resource = event.payload.get("resource")
    if isinstance(resource, Mapping):
        resource_type = resource.get("type")
        if isinstance(resource_type, str):
            return resource_type
    return ""
