"""PostgreSQL persistence for IAM human-in-the-loop decisions and callbacks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import cast

from fdai_operator_service.families.iam.contracts import (
    HilApprovalDecision,
    HilDecisionCommand,
    HilDecisionOutboxRequest,
    HilDecisionReceipt,
    HilPendingItem,
)
from fdai_operator_service.families.iam.errors import (
    IamConflictError,
    IamExpiredError,
    IamNotFoundError,
    IamPermissionError,
    IamUnavailableError,
)
from fdai_operator_service.families.iam.hil_callback_audit import HilCallbackAuditRecord
from fdai_operator_service.families.iam.hil_callback_context import HilCallbackContext
from fdai_operator_service.families.iam.hil_decision_outbox import (
    hil_decision_delivery_key,
    outbox_payload,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
    StoredProposal,
)
from fdai_operator_service.postgres_hil_decision import (
    HilDecisionStore,
    PostgresHilDecisionExpiredError,
    PostgresHilDecisionNotFoundError,
    PostgresHilDecisionPermissionError,
)

_HIL_PARK_PREFIX = "hil_park:"
_HIL_DECISION_PREFIX = "operator-hil-decision:"
_HIL_CALLBACK_AUDIT_PREFIX = "operator-hil-callback-audit:"


class PostgresIamHilMixin:
    """Provide the focused HIL persistence port used by the IAM adapter bundle."""

    store: PostgresFamilyStore
    hil_decisions: HilDecisionStore | None

    async def _state(self, key: str) -> dict[str, object] | None:
        raise NotImplementedError

    async def _proposal(
        self,
        operation: str,
        command: object,
        idempotency_key: str,
    ) -> StoredProposal:
        raise NotImplementedError

    async def get_pending_by_approval_id(self, approval_id: str) -> HilPendingItem | None:
        """Read one existing risk-gate HIL park record."""
        state = await self._state(f"{_HIL_PARK_PREFIX}{approval_id}")
        if state is None or state.get("status") != "pending":
            return None
        idempotency_key = state.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise IamUnavailableError("pending HIL record has no idempotency key")
        if "metadata" not in state:
            metadata = {"decision_route": "action"}
        elif isinstance(raw_metadata := state["metadata"], Mapping):
            metadata = {str(key): str(value) for key, value in raw_metadata.items()}
        else:
            raise IamUnavailableError("pending HIL metadata is malformed")
        correlation_id = state.get("correlation_id")
        request_fingerprint = state.get("request_fingerprint")
        approval_context = state.get("approval_context")
        if isinstance(correlation_id, str) and correlation_id:
            metadata.setdefault("correlation_id", correlation_id)
        if isinstance(request_fingerprint, str) and request_fingerprint:
            metadata.setdefault("action_hash", request_fingerprint)
        if isinstance(approval_context, Mapping):
            expires_at = approval_context.get("expires_at")
            if isinstance(expires_at, str) and expires_at:
                metadata.setdefault("expires_at", expires_at)
        return HilPendingItem(
            approval_id=approval_id,
            idempotency_key=idempotency_key,
            submitter_oid=str(state.get("submitter_oid") or ""),
            metadata=metadata,
        )

    async def get_decision_by_approval_id(
        self,
        approval_id: str,
    ) -> HilDecisionReceipt | None:
        """Read a previously recorded idempotent HIL decision."""
        state = await self._state(f"{_HIL_DECISION_PREFIX}{approval_id}")
        return None if state is None else _hil_receipt(state)

    async def record_decision(self, command: HilDecisionCommand) -> HilDecisionReceipt:
        """Atomically record one human decision and its durable outbox."""
        if self.hil_decisions is None:
            raise IamUnavailableError("HIL decision store is unavailable")
        try:
            stored = await self.hil_decisions.append_hil_decision(
                approval_id=command.approval_id,
                idempotency_key=command.idempotency_key,
                action_hash=command.action_hash,
                decision=command.decision.value,
                approver_oid=command.approver_oid,
                approver_roles=command.approver_roles,
                justification=command.justification,
                decided_at=command.decided_at,
                expected_expires_at=command.expected_expires_at,
                expected_submitter_oid=command.expected_submitter_oid,
                expected_decision_route=command.expected_decision_route,
                expected_required_role=command.expected_required_role,
            )
        except PostgresHilDecisionExpiredError as exc:
            raise IamExpiredError(str(exc)) from exc
        except PostgresHilDecisionNotFoundError as exc:
            raise IamNotFoundError(str(exc)) from exc
        except PostgresHilDecisionPermissionError as exc:
            raise IamPermissionError(str(exc)) from exc
        except PostgresProposalConflict as exc:
            raise IamConflictError(str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("HIL decision store is unavailable") from exc
        existing = await self.get_decision_by_approval_id(command.approval_id)
        if existing is None:
            raise IamUnavailableError("recorded HIL decision disappeared")
        return replace(existing, already_recorded=stored.duplicate)

    async def enqueue(self, request: HilDecisionOutboxRequest) -> None:
        """Queue a recorded HIL decision for typed downstream transport."""
        await self._proposal(
            "hil.decision.enqueue",
            outbox_payload(request.receipt),
            hil_decision_delivery_key(request.receipt.idempotency_key),
        )

    async def mark_delivered(self, receipt: HilDecisionReceipt) -> HilDecisionReceipt:
        """Mark only the durable outbox handoff, never the managed-resource effect."""
        key = f"{_HIL_DECISION_PREFIX}{receipt.approval_id}"
        current = await self._state(key)
        stored = _hil_receipt(current) if current is not None else receipt
        if stored.delivered:
            return replace(stored, already_recorded=True, delivered=True)
        delivered = replace(stored, delivered=True)
        try:
            await self.store.write_state(key, _json_mapping(asdict(delivered)))
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("HIL delivery receipt store is unavailable") from exc
        return replace(delivered, already_recorded=receipt.already_recorded)

    async def mark_decision_published(self, idempotency_key: str) -> bool:
        """Close the durable outbox record once the broker accepted the decision."""
        try:
            return await self.store.mark_hil_decision_published(
                idempotency_key=hil_decision_delivery_key(idempotency_key),
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("HIL decision outbox store is unavailable") from exc

    async def append_callback_audit(self, record: HilCallbackAuditRecord) -> None:
        """Append one sanitized callback phase as an immutable Operator record."""
        key = f"{_HIL_CALLBACK_AUDIT_PREFIX}{record.callback_id}:{record.phase.value}"
        value = _json_mapping(asdict(record))
        try:
            created = await self.store.create_state(key, value)
            if created:
                return
            existing = await self.store.read_state(key)
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("HIL callback audit store is unavailable") from exc
        if existing is None:
            raise IamUnavailableError("HIL callback audit phase disappeared")
        immutable_fields = set(value) - {"recorded_at"}
        if any(existing.get(field) != value[field] for field in immutable_fields):
            raise IamConflictError("HIL callback audit phase conflicts with its durable record")

    async def get_callback_context(self, approval_id: str) -> HilCallbackContext | None:
        """Read immutable callback identity from a pending or terminal park."""
        state = await self._state(f"{_HIL_PARK_PREFIX}{approval_id}")
        if state is None:
            return None
        approval_context = state.get("approval_context")
        if not isinstance(approval_context, Mapping):
            raise IamUnavailableError("HIL callback context is malformed")
        correlation_id = state.get("correlation_id")
        idempotency_key = state.get("idempotency_key")
        action_hash = state.get("request_fingerprint")
        if not all(
            isinstance(value, str) and value
            for value in (correlation_id, idempotency_key, action_hash)
        ):
            raise IamUnavailableError("HIL callback identity is incomplete")
        expires_at = _datetime(approval_context.get("expires_at"), "expires_at")
        if "metadata" not in state:
            metadata = {"decision_route": "action"}
        elif isinstance(raw_metadata := state["metadata"], Mapping):
            metadata = {str(key): str(value) for key, value in raw_metadata.items()}
        else:
            raise IamUnavailableError("HIL callback metadata is malformed")
        return HilCallbackContext(
            approval_id=approval_id,
            correlation_id=cast(str, correlation_id),
            idempotency_key=cast(str, idempotency_key),
            action_hash=cast(str, action_hash),
            expires_at=expires_at,
            submitter_oid=str(state.get("submitter_oid") or ""),
            metadata=metadata,
        )


def _json_mapping(value: object) -> dict[str, object]:
    normalized = json.loads(json.dumps(value, default=_json_default))
    if not isinstance(normalized, dict):
        raise ValueError("IAM adapter payload MUST serialize to a JSON object")
    return cast(dict[str, object], normalized)


def _json_default(value: object) -> object:
    if isinstance(value, set | frozenset):
        return sorted(str(item) for item in value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def _datetime(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise IamUnavailableError(f"authoritative IAM projection {name} is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IamUnavailableError(f"authoritative IAM projection {name} is malformed") from exc
    if parsed.tzinfo is None:
        raise IamUnavailableError(f"authoritative IAM projection {name} has no timezone")
    return parsed.astimezone(UTC)


def _hil_receipt(value: Mapping[str, object]) -> HilDecisionReceipt:
    try:
        return HilDecisionReceipt(
            approval_id=str(value["approval_id"]),
            idempotency_key=str(value["idempotency_key"]),
            decision=HilApprovalDecision(str(value["decision"])),
            approver_oid=str(value["approver_oid"]),
            decided_at=_datetime(value.get("decided_at"), "decided_at"),
            receipt_ref=str(value["receipt_ref"]),
            justification=str(value.get("justification") or ""),
            already_recorded=value.get("already_recorded") is True,
            delivered=value.get("delivered") is True,
        )
    except KeyError as exc:
        raise IamUnavailableError("stored HIL decision receipt is malformed") from exc


__all__ = ["PostgresIamHilMixin"]
