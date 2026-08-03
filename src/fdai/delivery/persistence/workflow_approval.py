"""Durable workflow approval requests projected into the existing HIL queue."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fdai.core.workflow.workflow_runtime import (
    WorkflowApprovalDecision,
    WorkflowApprovalSnapshot,
)
from fdai.delivery.persistence.state_store_hil_registry import add_pending_approval
from fdai.shared.providers.state_store import StateStore

_STATE_PREFIX = "workflow:approval:"
_PARK_PREFIX = "hil_park:"
_DECISION_PREFIX = "hil_decision:"


@dataclass(frozen=True, slots=True)
class StateStoreWorkflowApprovalProvider:
    """Persist exact workflow approval requests and resolve Var receipts."""

    store: StateStore

    async def ensure_requested(
        self,
        *,
        process_id: str,
        step_id: str,
        correlation_id: str,
        target_resource_id: str,
        requester_principal: str,
        required_role: str,
        quorum: int,
        no_self_approval: bool,
        timeout_seconds: int | None,
        requested_at: Any,
    ) -> WorkflowApprovalSnapshot:
        if not process_id or not step_id or not requester_principal:
            raise ValueError("workflow approval identity fields MUST be non-empty")
        if quorum < 1 or timeout_seconds is not None and timeout_seconds < 1:
            raise ValueError("workflow approval bounds MUST be positive")
        key = _state_key(process_id, step_id)
        expires_at = (
            requested_at + timedelta(seconds=timeout_seconds)
            if timeout_seconds is not None
            else None
        )
        slots = tuple(_slot(process_id, step_id, index) for index in range(quorum))
        record: dict[str, object] = {
            "process_id": process_id,
            "step_id": step_id,
            "correlation_id": correlation_id,
            "target_resource_id": target_resource_id,
            "requester_principal": requester_principal,
            "required_role": required_role,
            "quorum": quorum,
            "no_self_approval": no_self_approval,
            "timeout_seconds": timeout_seconds,
            "requested_at": requested_at.isoformat(),
            "expires_at": expires_at.isoformat() if expires_at is not None else None,
            "slots": list(slots),
            "state": "pending",
            "revision": 1,
        }
        created = await self.store.write_state_with_audit_if_absent(
            key,
            record,
            {
                "actor": "Var",
                "action_kind": "workflow.approval.requested",
                "process_id": process_id,
                "step_id": step_id,
                "required_role": required_role,
                "quorum": quorum,
                "requested_at": requested_at.isoformat(),
                "expires_at": expires_at.isoformat() if expires_at is not None else None,
            },
        )
        stored = record if created else await self.store.read_state(key)
        if stored is None or not _request_matches(stored, record):
            raise RuntimeError("workflow approval request conflicts with durable state")
        await self._ensure_parks(stored)
        return await self._snapshot(stored)

    async def mark_timed_out(
        self,
        *,
        process_id: str,
        step_id: str,
        expected_revision: int,
        timed_out_at: Any,
    ) -> bool:
        key = _state_key(process_id, step_id)
        record = await self.store.read_state(key)
        if record is None or not _lineage_matches(record, process_id, step_id):
            return False
        if record.get("state") == "timed_out":
            await self._close_parks(record, timed_out_at=timed_out_at)
            return True
        updated = {
            **dict(record),
            "state": "timed_out",
            "timed_out_at": timed_out_at.isoformat(),
            "revision": expected_revision + 1,
        }
        changed = await self.store.compare_and_set_state_with_audit(
            key,
            updated,
            expected_revision=expected_revision,
            audit_entry={
                "actor": "Var",
                "action_kind": "workflow.approval.timed_out",
                "process_id": process_id,
                "step_id": step_id,
                "timed_out_at": timed_out_at.isoformat(),
            },
        )
        if changed:
            await self._close_parks(updated, timed_out_at=timed_out_at)
        return changed

    async def _ensure_parks(self, record: Any) -> None:
        slots = _slots(record)
        for slot in slots:
            approval_id = str(slot["approval_id"])
            idempotency_key = str(slot["idempotency_key"])
            parked = _park_record(
                record,
                approval_id=approval_id,
                idempotency_key=idempotency_key,
            )
            created = await self.store.write_state_if_absent(
                f"{_PARK_PREFIX}{approval_id}",
                parked,
            )
            if not created:
                existing = await self.store.read_state(f"{_PARK_PREFIX}{approval_id}")
                if existing is None or existing.get("request_fingerprint") != parked.get(
                    "request_fingerprint"
                ):
                    raise RuntimeError("workflow approval slot conflicts with durable HIL state")
            await add_pending_approval(self.store, approval_id)

    async def _snapshot(self, record: Any) -> WorkflowApprovalSnapshot:
        decisions: list[WorkflowApprovalDecision] = []
        for slot in _slots(record):
            stored = await self.store.read_state(f"{_DECISION_PREFIX}{slot['idempotency_key']}")
            if stored is None:
                continue
            if (
                stored.get("approval_id") != slot["approval_id"]
                or stored.get("idempotency_key") != slot["idempotency_key"]
            ):
                raise RuntimeError("workflow approval receipt conflicts with its slot")
            decision = str(stored.get("decision") or "")
            decisions.append(
                WorkflowApprovalDecision(
                    principal=str(stored.get("approver_oid") or "").strip().casefold(),
                    decision=(
                        "approved"
                        if decision == "approve"
                        else "rejected"
                        if decision == "reject"
                        else decision
                    ),
                    receipt_ref=str(stored.get("receipt_ref") or ""),
                )
            )
        return WorkflowApprovalSnapshot(
            process_id=str(record["process_id"]),
            step_id=str(record["step_id"]),
            requester_principal=str(record["requester_principal"]),
            revision=int(record["revision"]),
            requested_at=_datetime(record["requested_at"]),
            expires_at=(
                _datetime(record["expires_at"]) if record.get("expires_at") is not None else None
            ),
            decisions=tuple(decisions),
            timed_out=record.get("state") == "timed_out",
        )

    async def _close_parks(self, record: Any, *, timed_out_at: Any) -> None:
        for slot in _slots(record):
            key = f"{_PARK_PREFIX}{slot['approval_id']}"
            parked = await self.store.read_state(key)
            if parked is None or parked.get("status") != "pending":
                continue
            revision = int(parked.get("revision", 0))
            await self.store.compare_and_set_state_with_audit(
                key,
                {
                    **dict(parked),
                    "status": "resolved",
                    "decision": "timeout",
                    "resolved_at": timed_out_at.isoformat(),
                    "revision": revision + 1,
                },
                expected_revision=revision,
                audit_entry={
                    "actor": "Var",
                    "action_kind": "workflow.approval.slot_timed_out",
                    "approval_id": slot["approval_id"],
                    "process_id": record["process_id"],
                    "step_id": record["step_id"],
                    "timed_out_at": timed_out_at.isoformat(),
                },
            )


def _state_key(process_id: str, step_id: str) -> str:
    digest = hashlib.sha256(f"{process_id}\0{step_id}".encode()).hexdigest()
    return f"{_STATE_PREFIX}{digest}"


def _slot(process_id: str, step_id: str, index: int) -> dict[str, object]:
    digest = hashlib.sha256(f"{process_id}\0{step_id}\0{index}".encode()).hexdigest()
    return {
        "index": index,
        "approval_id": f"workflow-approval:{digest}",
        "idempotency_key": f"workflow-approval:{digest}:decision",
    }


def _slots(record: Any) -> tuple[dict[str, object], ...]:
    raw = record.get("slots")
    if not isinstance(raw, list):
        raise RuntimeError("workflow approval slots are malformed")
    slots = tuple(dict(item) for item in raw if isinstance(item, dict))
    if len(slots) != len(raw):
        raise RuntimeError("workflow approval slots are malformed")
    return slots


def _request_matches(stored: Any, expected: dict[str, object]) -> bool:
    fields = (
        "process_id",
        "step_id",
        "correlation_id",
        "target_resource_id",
        "requester_principal",
        "required_role",
        "quorum",
        "no_self_approval",
        "timeout_seconds",
        "slots",
    )
    return all(stored.get(field) == expected[field] for field in fields)


def _lineage_matches(record: Any, process_id: str, step_id: str) -> bool:
    return bool(record.get("process_id") == process_id and record.get("step_id") == step_id)


def _park_record(
    record: Any,
    *,
    approval_id: str,
    idempotency_key: str,
) -> dict[str, object]:
    fingerprint = hashlib.sha256(
        f"{record['process_id']}\0{record['step_id']}\0{approval_id}".encode()
    ).hexdigest()
    return {
        "status": "pending",
        "revision": 0,
        "approval_id": approval_id,
        "idempotency_key": idempotency_key,
        "action_type": "workflow.approval",
        "action": {
            "event_id": str(uuid5(NAMESPACE_URL, f"{approval_id}:event")),
            "action_id": str(uuid5(NAMESPACE_URL, f"{approval_id}:action")),
            "action_type": "workflow.approval",
            "target_resource_ref": record["target_resource_id"],
            "citing_rules": [],
        },
        "submitter_oid": record["requester_principal"],
        "correlation_id": record["correlation_id"],
        "parked_at": record["requested_at"],
        "request_fingerprint": fingerprint,
        "reason": (
            f"Workflow step {record['step_id']} requires "
            f"{record['quorum']} {record['required_role']} approval(s)."
        ),
        "metadata": {
            "decision_route": "workflow",
            "process_id": str(record["process_id"]),
            "step_id": str(record["step_id"]),
        },
    }


def _datetime(value: object) -> Any:
    from datetime import datetime

    if not isinstance(value, str):
        raise RuntimeError("workflow approval timestamp is malformed")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


__all__ = ["StateStoreWorkflowApprovalProvider"]
