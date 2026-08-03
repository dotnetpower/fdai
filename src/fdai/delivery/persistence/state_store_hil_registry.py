"""StateStore-backed HIL registry projected from durable core park records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Final

import psycopg
from psycopg.rows import dict_row

from fdai.shared.providers.hil_registry import (
    HilApprovalDecision,
    HilApprovalRegistry,
    HilDecisionReceipt,
    HilDuplicateApproverError,
    HilItemAlreadyResolvedError,
    HilItemNotFoundError,
    HilPendingItem,
    MutationTarget,
)
from fdai.shared.providers.state_store import StateStore

_PARK_PREFIX: Final[str] = "hil_park:"
_DECISION_PREFIX: Final[str] = "hil_decision:"
_INDEX_KEY: Final[str] = "hil_pending:index"


class StateStoreHilApprovalRegistry(HilApprovalRegistry):
    """Read pending parks and persist idempotent approval decisions."""

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def list_pending(self, *, limit: int = 50) -> Sequence[HilPendingItem]:
        cap = max(1, limit)
        offset = 0
        items: list[HilPendingItem] = []
        while len(items) < cap:
            parks, total = await self._store.read_state_page(
                _PARK_PREFIX,
                limit=min(100, cap),
                offset=offset,
            )
            for park in parks:
                item = _pending_from_park(park)
                if item is None:
                    continue
                if not await self._item_is_decided(item):
                    items.append(item)
                    if len(items) == cap:
                        break
            offset += len(parks)
            if not parks or offset >= total:
                break
        items.sort(
            key=lambda item: (
                item.requested_at or datetime.min.replace(tzinfo=UTC),
                item.idempotency_key,
            ),
            reverse=True,
        )
        return tuple(items[:cap])

    async def get_pending(self, idempotency_key: str) -> HilPendingItem | None:
        park = await self._store.find_state(
            _PARK_PREFIX,
            field="idempotency_key",
            value=idempotency_key,
        )
        item = _pending_from_park(park)
        if item is None:
            return None
        return None if await self._item_is_decided(item) else item

    async def get_pending_by_approval_id(
        self,
        approval_id: str,
    ) -> HilPendingItem | None:
        park = await self._store.read_state(_park_key(approval_id))
        item = _pending_from_park(park)
        if item is None:
            return None
        return None if await self._item_is_decided(item) else item

    async def get_decision_by_approval_id(
        self,
        approval_id: str,
    ) -> HilDecisionReceipt | None:
        park = await self._store.read_state(_park_key(approval_id))
        if park is None:
            return None
        idempotency_key = str(park.get("idempotency_key") or "")
        if not idempotency_key:
            return None
        stored = await self._store.read_state(_decision_key(idempotency_key))
        if stored is None:
            item = _pending_from_park(park)
            claim = await self._workflow_claim(item) if item is not None else None
            return _receipt_from_workflow_claim(item, claim) if item is not None and claim else None
        return _receipt_from_mapping(stored, already_recorded=True)

    async def _item_is_decided(self, item: HilPendingItem) -> bool:
        workflow_record = await self._workflow_record(item)
        if workflow_record is not None:
            if workflow_record.get("state") != "pending":
                return True
            raw_claims = workflow_record.get("decision_claims", {})
            if not isinstance(raw_claims, Mapping):
                raise RuntimeError("workflow approval decision claims are malformed")
            if item.idempotency_key in raw_claims:
                return True
        return await self._store.read_state(_decision_key(item.idempotency_key)) is not None

    async def _workflow_record(self, item: HilPendingItem) -> Mapping[str, object] | None:
        if item.metadata.get("decision_route") != "workflow":
            return None
        state_key = item.metadata.get("workflow_state_key", "")
        if not state_key:
            process_id = item.metadata.get("process_id", "")
            step_id = item.metadata.get("step_id", "")
            if process_id and step_id:
                state_key = _workflow_state_key(
                    process_id,
                    step_id,
                    int(item.metadata.get("attempt", "1")),
                )
        if not state_key:
            raise RuntimeError("workflow approval claim metadata is malformed")
        record = await self._store.read_state(state_key)
        if record is None:
            raise RuntimeError("workflow approval state is unavailable")
        return record

    async def _workflow_claim(self, item: HilPendingItem) -> Mapping[str, object] | None:
        record = await self._workflow_record(item)
        if record is None:
            return None
        raw_claims = record.get("decision_claims", {})
        if not isinstance(raw_claims, Mapping):
            raise RuntimeError("workflow approval decision claims are malformed")
        claim = raw_claims.get(item.idempotency_key)
        if claim is None:
            return None
        if not isinstance(claim, Mapping):
            raise RuntimeError("workflow approval decision claim is malformed")
        return claim

    async def list_undelivered(self, *, limit: int = 100) -> Sequence[HilDecisionReceipt]:
        cap = max(1, limit)
        offset = 0
        receipts: list[HilDecisionReceipt] = []
        while len(receipts) < cap:
            stored, total = await self._store.read_state_page(
                _DECISION_PREFIX,
                limit=min(100, cap),
                offset=offset,
            )
            for value in stored:
                receipt = _receipt_from_mapping(value, already_recorded=True)
                if not receipt.delivered and not receipt.delivery_abandoned:
                    receipts.append(receipt)
                    if len(receipts) == cap:
                        break
            offset += len(stored)
            if not stored or offset >= total:
                break
        return tuple(receipts)

    async def record_decision(
        self,
        *,
        idempotency_key: str,
        decision: HilApprovalDecision,
        approver_oid: str,
        justification: str = "",
        decided_at: datetime | None = None,
    ) -> HilDecisionReceipt:
        existing = await self._store.read_state(_decision_key(idempotency_key))
        if existing is not None:
            prior = _receipt_from_mapping(existing, already_recorded=True)
            if prior.decision is not decision:
                raise HilItemAlreadyResolvedError(
                    idempotency_key,
                    prior_decision=prior.decision.value,
                )
            return prior

        parked = await self._store.find_state(
            _PARK_PREFIX,
            field="idempotency_key",
            value=idempotency_key,
        )
        pending = _pending_from_park(parked)
        if pending is None:
            raise HilItemNotFoundError(idempotency_key)

        now = decided_at or datetime.now(tz=UTC)
        receipt_ref = (
            "hil-receipt:"
            + hashlib.sha256(
                f"{idempotency_key}:{decision.value}:{approver_oid}".encode()
            ).hexdigest()
        )
        claim, claim_created = await self._claim_workflow_principal(
            pending=pending,
            decision=decision,
            approver_oid=approver_oid,
            justification=justification,
            receipt_ref=receipt_ref,
            claimed_at=now,
        )
        receipt = (
            _receipt_from_workflow_claim(pending, claim, already_recorded=not claim_created)
            if claim is not None
            else HilDecisionReceipt(
                approval_id=pending.approval_id,
                idempotency_key=idempotency_key,
                decision=decision,
                approver_oid=approver_oid,
                decided_at=now,
                receipt_ref=receipt_ref,
                already_recorded=False,
                justification=justification,
                delivered=False,
            )
        )
        stored_receipt = {
            "approval_id": receipt.approval_id,
            "idempotency_key": receipt.idempotency_key,
            "decision": receipt.decision.value,
            "approver_oid": receipt.approver_oid,
            "decided_at": receipt.decided_at.isoformat(),
            "receipt_ref": receipt.receipt_ref,
            "justification": receipt.justification,
            "delivered": receipt.delivered,
            "delivery_attempts": 0,
            "delivery_abandoned": False,
            "last_delivery_error": "",
            "delivery_state": "delivered" if receipt.delivered else "pending",
            "decision_route": pending.metadata.get("decision_route", "action"),
        }
        created = await self._store.write_state_with_audit_if_absent(
            _decision_key(idempotency_key),
            stored_receipt,
            {
                "actor": "Var",
                "action_kind": "workflow.approval.receipt_projected"
                if receipt.delivered
                else "hil.decision.recorded",
                "approval_id": receipt.approval_id,
                "idempotency_key": receipt.idempotency_key,
                "decision": receipt.decision.value,
                "approver_oid": receipt.approver_oid,
                "decided_at": receipt.decided_at.isoformat(),
                "receipt_ref": receipt.receipt_ref,
                "process_id": pending.metadata.get("process_id"),
                "step_id": pending.metadata.get("step_id"),
                "required_role": pending.metadata.get("required_role"),
            },
        )
        if not created:
            existing = await self._store.read_state(_decision_key(idempotency_key))
            if existing is None:  # pragma: no cover - atomic store invariant
                raise RuntimeError("HIL decision disappeared after a concurrent write")
            prior = _receipt_from_mapping(existing, already_recorded=True)
            if (
                prior.decision is not decision
                or prior.approver_oid.strip().casefold() != approver_oid.strip().casefold()
            ):
                raise HilItemAlreadyResolvedError(
                    idempotency_key,
                    prior_decision=prior.decision.value,
                )
            return prior
        return receipt

    async def _claim_workflow_principal(
        self,
        *,
        pending: HilPendingItem,
        decision: HilApprovalDecision,
        approver_oid: str,
        justification: str,
        receipt_ref: str,
        claimed_at: datetime,
    ) -> tuple[Mapping[str, object] | None, bool]:
        if pending.metadata.get("decision_route") != "workflow":
            return None, False
        state_key = pending.metadata.get("workflow_state_key", "")
        if not state_key:
            process_id = pending.metadata.get("process_id", "")
            step_id = pending.metadata.get("step_id", "")
            if process_id and step_id:
                state_key = _workflow_state_key(
                    process_id,
                    step_id,
                    int(pending.metadata.get("attempt", "1")),
                )
        principal = approver_oid.strip().casefold()
        if not state_key or not principal:
            raise RuntimeError("workflow approval claim metadata is malformed")
        for _ in range(8):
            record = await self._store.read_state(state_key)
            if record is None or record.get("state") != "pending":
                raise HilItemNotFoundError(pending.idempotency_key)
            revision = int(record.get("revision", 0))
            raw_claims = record.get("decision_claims", {})
            if not isinstance(raw_claims, Mapping):
                raise RuntimeError("workflow approval decision claims are malformed")
            claims = {str(key): value for key, value in raw_claims.items()}
            prior_claim = claims.get(pending.idempotency_key)
            if prior_claim is not None:
                if not isinstance(prior_claim, Mapping):
                    raise RuntimeError("workflow approval decision claim is malformed")
                if prior_claim.get("principal") == principal and prior_claim.get("decision") == (
                    "approved" if decision is HilApprovalDecision.APPROVE else "rejected"
                ):
                    return prior_claim, False
                raise HilItemAlreadyResolvedError(
                    pending.idempotency_key,
                    prior_decision=str(prior_claim.get("decision") or "claimed"),
                )
            if any(
                isinstance(value, Mapping) and value.get("principal") == principal
                for value in claims.values()
            ):
                raise HilDuplicateApproverError(pending.idempotency_key)
            claim = {
                "principal": principal,
                "decision": ("approved" if decision is HilApprovalDecision.APPROVE else "rejected"),
                "receipt_ref": receipt_ref,
                "decided_at": claimed_at.isoformat(),
                "justification": justification,
            }
            updated = {
                **dict(record),
                "decision_claims": {**claims, pending.idempotency_key: claim},
                "state": (
                    "rejected"
                    if decision is HilApprovalDecision.REJECT
                    else record.get("state", "pending")
                ),
                "revision": revision + 1,
            }
            claimed = await self._store.compare_and_set_state_with_audit(
                state_key,
                updated,
                expected_revision=revision,
                audit_entry={
                    "actor": "Var",
                    "action_kind": "workflow.approval.decided",
                    "approval_id": pending.approval_id,
                    "idempotency_key": pending.idempotency_key,
                    "approver_oid": principal,
                    "decision": claim["decision"],
                    "receipt_ref": receipt_ref,
                    "process_id": pending.metadata.get("process_id"),
                    "step_id": pending.metadata.get("step_id"),
                    "claimed_at": claimed_at.isoformat(),
                },
            )
            if claimed:
                if decision is HilApprovalDecision.REJECT:
                    await self._close_rejected_workflow_slots(
                        updated,
                        rejected_at=claimed_at,
                    )
                return claim, True
        raise RuntimeError("workflow approval claim exceeded its concurrency retry bound")

    async def _close_rejected_workflow_slots(
        self,
        record: Mapping[str, object],
        *,
        rejected_at: datetime,
    ) -> None:
        raw_slots = record.get("slots")
        if not isinstance(raw_slots, list):
            raise RuntimeError("workflow approval slots are malformed")
        for raw_slot in raw_slots:
            if not isinstance(raw_slot, Mapping):
                raise RuntimeError("workflow approval slot is malformed")
            approval_id = str(raw_slot.get("approval_id") or "")
            if not approval_id:
                raise RuntimeError("workflow approval slot identity is malformed")
            key = _park_key(approval_id)
            parked = await self._store.read_state(key)
            if parked is None or parked.get("status") != "pending":
                continue
            revision = int(parked.get("revision", 0))
            closed = await self._store.compare_and_set_state_with_audit(
                key,
                {
                    **dict(parked),
                    "status": "resolved",
                    "decision": "reject",
                    "resolved_at": rejected_at.isoformat(),
                    "revision": revision + 1,
                },
                expected_revision=revision,
                audit_entry={
                    "actor": "Var",
                    "action_kind": "workflow.approval.slot_rejected",
                    "approval_id": approval_id,
                    "process_id": record.get("process_id"),
                    "step_id": record.get("step_id"),
                    "rejected_at": rejected_at.isoformat(),
                },
            )
            if not closed:
                current = await self._store.read_state(key)
                if current is not None and current.get("status") == "pending":
                    raise RuntimeError("workflow approval rejection left a pending slot")

    async def record_delivery_attempt(
        self,
        *,
        idempotency_key: str,
        delivered: bool,
        error_code: str = "",
        max_attempts: int,
    ) -> HilDecisionReceipt:
        key = _decision_key(idempotency_key)
        stored = await self._store.read_state(key)
        if stored is None:
            raise HilItemNotFoundError(idempotency_key)
        updated = _apply_delivery_attempt(
            stored,
            delivered=delivered,
            error_code=error_code,
            max_attempts=max_attempts,
        )
        await self._store.write_state(key, updated)
        return _receipt_from_mapping(updated, already_recorded=True)


class PostgresHilApprovalRegistry(StateStoreHilApprovalRegistry):
    """Multi-replica-safe HIL registry over Postgres ``state_kv``."""

    def __init__(
        self,
        *,
        store: StateStore,
        dsn: str,
        statement_timeout_ms: int = 15_000,
        connect_timeout_s: int = 10,
    ) -> None:
        super().__init__(store=store)
        if not dsn:
            raise ValueError("dsn MUST be non-empty")
        if statement_timeout_ms < 1 or connect_timeout_s < 1:
            raise ValueError("timeouts MUST be positive")
        self._dsn = dsn
        self._statement_timeout_ms = statement_timeout_ms
        self._connect_timeout_s = connect_timeout_s

    async def record_decision(
        self,
        *,
        idempotency_key: str,
        decision: HilApprovalDecision,
        approver_oid: str,
        justification: str = "",
        decided_at: datetime | None = None,
    ) -> HilDecisionReceipt:
        return await super().record_decision(
            idempotency_key=idempotency_key,
            decision=decision,
            approver_oid=approver_oid,
            justification=justification,
            decided_at=decided_at,
        )

    async def record_delivery_attempt(
        self,
        *,
        idempotency_key: str,
        delivered: bool,
        error_code: str = "",
        max_attempts: int,
    ) -> HilDecisionReceipt:
        key = _decision_key(idempotency_key)
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=self._connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._statement_timeout_ms),),
                )
                cursor = await conn.execute(
                    "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
                    (key,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise HilItemNotFoundError(idempotency_key)
                value = row["value"]
                if not isinstance(value, Mapping):
                    raise RuntimeError("stored HIL decision is not a JSON object")
                updated = _apply_delivery_attempt(
                    value,
                    delivered=delivered,
                    error_code=error_code,
                    max_attempts=max_attempts,
                )
                await conn.execute(
                    "UPDATE state_kv SET value = %s::jsonb WHERE key = %s",
                    (json.dumps(updated), key),
                )
        return _receipt_from_mapping(updated, already_recorded=True)


async def add_pending_approval(store: StateStore, approval_id: str) -> None:
    """Add an approval id to the durable projection index idempotently."""
    index = await store.read_state(_INDEX_KEY) or {}
    raw_ids = index.get("approval_ids", [])
    approval_ids = [str(value) for value in raw_ids] if isinstance(raw_ids, list) else []
    if approval_id not in approval_ids:
        approval_ids.append(approval_id)
        await store.write_state(_INDEX_KEY, {"approval_ids": approval_ids})


def _park_key(approval_id: str) -> str:
    return f"{_PARK_PREFIX}{approval_id}"


def _decision_key(idempotency_key: str) -> str:
    return f"{_DECISION_PREFIX}{idempotency_key}"


def _workflow_state_key(process_id: str, step_id: str, attempt: int = 1) -> str:
    identity = f"{process_id}\0{step_id}"
    if attempt > 1:
        identity += f"\0{attempt}"
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return f"workflow:approval:{digest}"


def _pending_from_park(park: Mapping[str, object] | None) -> HilPendingItem | None:
    if park is None or park.get("status") != "pending":
        return None
    action = park.get("action")
    if not isinstance(action, Mapping):
        return None
    approval_id = str(park.get("approval_id") or "")
    idempotency_key = str(park.get("idempotency_key") or "")
    if not approval_id or not idempotency_key:
        return None
    parked_at = park.get("parked_at")
    requested_at: datetime | None = None
    if isinstance(parked_at, str):
        try:
            requested_at = datetime.fromisoformat(parked_at.replace("Z", "+00:00"))
        except ValueError:
            requested_at = None
    mutation_target = None
    execution_path = park.get("execution_path")
    if isinstance(execution_path, str):
        try:
            mutation_target = MutationTarget(execution_path)
        except ValueError:
            mutation_target = None
    citing_rules = action.get("citing_rules", ())
    return HilPendingItem(
        idempotency_key=idempotency_key,
        approval_id=approval_id,
        event_id=str(action.get("event_id") or ""),
        action_id=str(action.get("action_id") or ""),
        action_kind=str(park.get("action_type") or action.get("action_type") or ""),
        target_resource_ref=str(action.get("target_resource_ref") or ""),
        reason=str(park.get("reason") or "Approval required by the risk gate."),
        submitter_oid=str(park.get("submitter_oid") or ""),
        citing_rule_ids=tuple(str(value) for value in citing_rules),
        requested_at=requested_at,
        correlation_id=str(park.get("correlation_id") or "") or None,
        mutation_target=mutation_target,
        metadata=_metadata_from_park(park),
    )


def _metadata_from_park(park: Mapping[str, object]) -> Mapping[str, str]:
    raw = park.get("metadata")
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _receipt_from_mapping(
    value: Mapping[str, object], *, already_recorded: bool
) -> HilDecisionReceipt:
    decided_at_raw = value.get("decided_at")
    if not isinstance(decided_at_raw, str):
        raise RuntimeError("stored HIL decision is missing decided_at")
    return HilDecisionReceipt(
        approval_id=str(value.get("approval_id") or ""),
        idempotency_key=str(value.get("idempotency_key") or ""),
        decision=HilApprovalDecision(str(value.get("decision") or "")),
        approver_oid=str(value.get("approver_oid") or ""),
        decided_at=datetime.fromisoformat(decided_at_raw.replace("Z", "+00:00")),
        receipt_ref=str(value.get("receipt_ref") or ""),
        already_recorded=already_recorded,
        justification=str(value.get("justification") or ""),
        delivered=value.get("delivered") is True or value.get("delivery_state") == "delivered",
        delivery_attempts=_non_negative_int(value.get("delivery_attempts")),
        delivery_abandoned=(
            value.get("delivery_abandoned") is True or value.get("delivery_state") == "abandoned"
        ),
        last_delivery_error=str(value.get("last_delivery_error") or ""),
    )


def _receipt_from_workflow_claim(
    item: HilPendingItem,
    claim: Mapping[str, object],
    *,
    already_recorded: bool = True,
) -> HilDecisionReceipt:
    decided_at = claim.get("decided_at")
    if not isinstance(decided_at, str):
        raise RuntimeError("workflow approval decision claim is missing decided_at")
    decision = str(claim.get("decision") or "")
    return HilDecisionReceipt(
        approval_id=item.approval_id,
        idempotency_key=item.idempotency_key,
        decision=(
            HilApprovalDecision.APPROVE
            if decision == "approved"
            else HilApprovalDecision.REJECT
            if decision == "rejected"
            else HilApprovalDecision(decision)
        ),
        approver_oid=str(claim.get("principal") or ""),
        decided_at=datetime.fromisoformat(decided_at.replace("Z", "+00:00")),
        receipt_ref=str(claim.get("receipt_ref") or ""),
        already_recorded=already_recorded,
        justification=str(claim.get("justification") or ""),
        delivered=True,
    )


def _non_negative_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        raise RuntimeError("stored HIL delivery_attempts MUST be a non-negative integer")
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise RuntimeError("stored HIL delivery_attempts MUST be a non-negative integer")


def _apply_delivery_attempt(
    stored: Mapping[str, object],
    *,
    delivered: bool,
    error_code: str,
    max_attempts: int,
) -> dict[str, object]:
    if max_attempts <= 0:
        raise ValueError("max_attempts MUST be positive")
    prior = _receipt_from_mapping(stored, already_recorded=True)
    if prior.delivered or prior.delivery_abandoned:
        return dict(stored)
    attempts = prior.delivery_attempts + 1
    updated = dict(stored)
    updated.update(
        {
            "delivered": delivered,
            "delivery_attempts": attempts,
            "delivery_abandoned": not delivered and attempts >= max_attempts,
            "last_delivery_error": "" if delivered else error_code,
            "delivery_state": (
                "delivered"
                if delivered
                else ("abandoned" if attempts >= max_attempts else "pending")
            ),
        }
    )
    return updated


__all__ = [
    "PostgresHilApprovalRegistry",
    "StateStoreHilApprovalRegistry",
    "add_pending_approval",
]
