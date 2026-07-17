"""Approver-scoped HIL console tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from fdai.core.conversation._write_audit import AuditWriter
from fdai.core.conversation.session import Principal, Role
from fdai.core.conversation.tools import SideEffectClass, ToolResult, _optional_str
from fdai.shared.providers.hil_registry import (
    HilApprovalDecision,
    HilApprovalRegistry,
    HilItemAlreadyResolvedError,
    HilItemNotFoundError,
    HilPendingItem,
    HilRegistryError,
)


class ListHilTool:
    """Return pending HIL items visible to Approvers."""

    name = "list_hil"
    description = (
        "Return the pending HIL items with full Approver-visible detail "
        "(idempotency_key, submitter, action, resource). Read-only."
    )
    rbac_floor: Role = Role.APPROVER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, registry: HilApprovalRegistry) -> None:
        self._registry = registry

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        import asyncio

        raw_limit = arguments.get("limit", 20)
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            return ToolResult(status="error", preview="list_hil 'limit' MUST be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
        items = asyncio.run(self._registry.list_pending(limit=limit))
        payload = [_project_pending_item(item) for item in items]
        return ToolResult(
            status="ok" if payload else "abstain",
            data={"items": payload, "limit": limit},
            preview=f"list_hil: {len(payload)} pending item(s)",
            evidence_refs=tuple(f"hil:{item.idempotency_key}" for item in items),
        )


class ApproveHilTool:
    """Resolve one queued HIL item with fail-closed invariant checks."""

    name = "approve_hil"
    description = (
        "Resolve one queued HIL item. Requires idempotency_key + "
        "decision ('approve' or 'reject'). Verifier re-check + "
        "no_self_approval invariant applied."
    )
    rbac_floor: Role = Role.APPROVER
    side_effect_class: SideEffectClass = "approve"

    def __init__(
        self,
        *,
        registry: HilApprovalRegistry,
        audit_writer: AuditWriter,
        known_action_kinds: frozenset[str] | None = None,
    ) -> None:
        self._registry = registry
        self._audit_writer = audit_writer
        self.known_action_kinds = (
            known_action_kinds if known_action_kinds is not None else frozenset()
        )

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        import asyncio

        idempotency_key = str(arguments.get("idempotency_key", "")).strip()
        raw_decision = str(arguments.get("decision", "")).strip().lower()
        justification = _optional_str(arguments, "justification", default="").strip()
        if not idempotency_key:
            return ToolResult(
                status="error",
                preview="approve_hil requires a non-empty 'idempotency_key'",
            )
        try:
            decision = HilApprovalDecision(raw_decision)
        except ValueError:
            return ToolResult(
                status="error",
                preview=(
                    f"approve_hil 'decision' MUST be 'approve' or 'reject'; got {raw_decision!r}"
                ),
            )
        item = asyncio.run(self._registry.get_pending(idempotency_key))
        if item is None:
            return ToolResult(
                status="error",
                preview=f"approve_hil: no pending item for idempotency_key={idempotency_key!r}",
            )
        if self.known_action_kinds and item.action_kind not in self.known_action_kinds:
            return ToolResult(
                status="error",
                preview=(
                    f"approve_hil: action_kind {item.action_kind!r} is no longer "
                    "in the shipped catalog; verifier re-check failed"
                ),
            )
        if not item.submitter_oid:
            return ToolResult(
                status="error",
                preview=(
                    "approve_hil: pending item is missing submitter_oid; the "
                    "no_self_approval invariant cannot be verified (fail-closed)"
                ),
            )
        if principal.id == item.submitter_oid:
            return ToolResult(
                status="error",
                preview=(
                    "approve_hil: no_self_approval invariant would be "
                    "violated (approver.oid == submitter_oid)"
                ),
            )
        try:
            receipt = asyncio.run(
                self._registry.record_decision(
                    idempotency_key=idempotency_key,
                    decision=decision,
                    approver_oid=principal.id,
                    justification=justification,
                )
            )
        except HilItemAlreadyResolvedError as exc:
            audit_id = self._audit_writer.write_approval_entry(
                item=item,
                principal=principal,
                decision=decision,
                outcome="error",
                justification=justification,
                receipt_ref="",
                already_recorded=False,
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id, "reason": str(exc)},
                preview=f"approve_hil: {exc}",
                evidence_refs=(f"audit:{audit_id}",),
            )
        except HilItemNotFoundError:
            return ToolResult(
                status="error",
                preview=(
                    f"approve_hil: item {idempotency_key!r} disappeared "
                    "between existence check and decision write"
                ),
            )
        except HilRegistryError as exc:
            return ToolResult(
                status="error",
                preview=f"approve_hil: registry error [{exc.kind}] {exc}",
            )
        outcome_status: Literal["ok", "error", "abstain"] = "ok"
        audit_id = self._audit_writer.write_approval_entry(
            item=item,
            principal=principal,
            decision=decision,
            outcome=outcome_status,
            justification=justification,
            receipt_ref=receipt.receipt_ref,
            already_recorded=receipt.already_recorded,
        )
        preview = (
            f"approve_hil[{item.action_kind}]: decision={decision.value} "
            f"receipt={receipt.receipt_ref}" + (" (replay)" if receipt.already_recorded else "")
        )
        return ToolResult(
            status=outcome_status,
            data={
                "audit_id": audit_id,
                "receipt_ref": receipt.receipt_ref,
                "already_recorded": receipt.already_recorded,
                "decision": decision.value,
                "idempotency_key": item.idempotency_key,
            },
            preview=preview,
            evidence_refs=(f"audit:{audit_id}", f"hil:{item.idempotency_key}"),
        )


def _project_pending_item(item: HilPendingItem) -> dict[str, Any]:
    return {
        "idempotency_key": item.idempotency_key,
        "approval_id": item.approval_id,
        "event_id": item.event_id,
        "action_id": item.action_id,
        "action_kind": item.action_kind,
        "target_resource_ref": item.target_resource_ref,
        "reason": item.reason,
        "submitter_oid": item.submitter_oid,
        "citing_rule_ids": list(item.citing_rule_ids),
        "requested_at": item.requested_at.isoformat() if item.requested_at else None,
        "correlation_id": item.correlation_id,
        "mutation_target": item.mutation_target.value if item.mutation_target else None,
    }
