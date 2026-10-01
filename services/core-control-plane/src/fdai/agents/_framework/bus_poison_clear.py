"""Core-side processing for Operator ordered-poison-halt clear requests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai_service_contracts.bus_poison_halt_clear import (
    OrderedPoisonHaltClearRequest,
    ordered_poison_halt_clear_receipt_event,
)
from fdai_service_contracts.compatibility import canonical_digest

from fdai.agents._framework.bus_poison_halt import clear_ordered_halt_with_evidence
from fdai.agents._framework.huginn_operator_receipt import (
    OperatorRequestReceiptGate,
    VerifiedOperatorRequestReceipt,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore

_CLEAR_OUTCOME_PREFIX = "pantheon/bus/ordered-poison-halt-clear-outcomes/"
_DEFAULT_OPERATOR_PRODUCER_ID = "operator-service"
_DEFAULT_CLEAR_TTL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class OrderedPoisonHaltClearResult:
    """Outcome of one exact poison-halt clear request."""

    status: str
    halted: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class OrderedPoisonHaltClearProcessor:
    """Verify parked DLQ evidence, audit, and clear one durable halt by CAS."""

    bus: EventBus
    halt_state_store: StateStore
    audit_store: StateStore
    operator_request_receipt_gate: OperatorRequestReceiptGate | None = None
    trusted_operator_producer_id: str = _DEFAULT_OPERATOR_PRODUCER_ID
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    request_ttl: timedelta = _DEFAULT_CLEAR_TTL
    consumer_group_prefix: str = "fdai-pantheon"
    dlq_scan_limit: int = 100
    dlq_scan_timeout: timedelta = timedelta(seconds=5)

    async def handle(
        self,
        _topic: str,
        payload: Mapping[str, object],
    ) -> OrderedPoisonHaltClearResult:
        request = OrderedPoisonHaltClearRequest.model_validate(payload)
        receipt_verification, receipt_rejection = await self._verify_operator_receipt(request)
        if receipt_rejection is not None:
            await self._record_rejected_outcome(request, receipt_rejection)
            return OrderedPoisonHaltClearResult("rejected", halted=True, reason=receipt_rejection)
        group_rejection = self._validate_group_id(request)
        if group_rejection is not None:
            await self._record_rejected_outcome(request, group_rejection)
            return OrderedPoisonHaltClearResult("rejected", halted=True, reason=group_rejection)
        expiry_rejection = self._validate_request_freshness(request)
        if expiry_rejection is not None:
            await self._record_rejected_outcome(request, expiry_rejection)
            return OrderedPoisonHaltClearResult("rejected", halted=True, reason=expiry_rejection)
        parked = await self._find_parked_record(request)
        if parked is None:
            await self._record_rejected_outcome(request, "parked_missing")
            return OrderedPoisonHaltClearResult("rejected", halted=True, reason="parked_missing")
        dlq_metadata = {
            "consumer_group": parked.get("consumer_group"),
            "topic": parked.get("topic") or parked.get("original_topic"),
            "offset": parked.get("offset"),
        }
        evidence = {
            "schema_version": "1.0.0",
            "request_id": request.request_id,
            "idempotency_key": request.idempotency_key,
            "principal_id": request.principal_id,
            "group_id": request.group_id,
            "topic": request.topic,
            "halt_revision": request.halt_revision,
            "halt_record_digest": request.halt_record_digest,
            "parked_record_topic": request.parked_record_topic,
            "parked_record_key": request.parked_record_key,
            "parked_record_offset": request.parked_record_offset,
            "parked_record_digest": request.parked_record_digest,
            "parked_record_metadata": dlq_metadata,
        }
        if receipt_verification is None or self.operator_request_receipt_gate is None:
            await self._record_rejected_outcome(request, "receipt_verifier_unbound")
            return OrderedPoisonHaltClearResult(
                "rejected",
                halted=True,
                reason="receipt_verifier_unbound",
            )
        try:
            await self.operator_request_receipt_gate.commit(receipt_verification)
        except ValueError as exc:
            reason = f"receipt_{_safe_reason(str(exc))}"
            await self._record_rejected_outcome(request, reason)
            return OrderedPoisonHaltClearResult("rejected", halted=True, reason=reason)
        cleared = await clear_ordered_halt_with_evidence(
            self.halt_state_store,
            group_id=request.group_id,
            topic=request.topic,
            expected_revision=request.halt_revision,
            expected_halt_digest=request.halt_record_digest,
            parked_record_evidence=evidence,
            audit_entry={
                "schema_version": "1.0.0",
                "agent": "Saga",
                "event_type": "ordered_poison_halt_clear",
                "request_id": request.request_id,
                "idempotency_key": request.idempotency_key,
                "principal_id": request.principal_id,
                "group_id": request.group_id,
                "topic": request.topic,
                "evidence_digest": canonical_digest(evidence),
            },
        )
        if not cleared:
            await self._record_rejected_outcome(request, "halt_mismatch")
            return OrderedPoisonHaltClearResult("rejected", halted=True, reason="halt_mismatch")
        return OrderedPoisonHaltClearResult("cleared", halted=False)

    async def _verify_operator_receipt(
        self,
        request: OrderedPoisonHaltClearRequest,
    ) -> tuple[VerifiedOperatorRequestReceipt | None, str | None]:
        if self.operator_request_receipt_gate is None:
            return None, "receipt_verifier_unbound"
        if not isinstance(request.operator_request_receipt, Mapping):
            return None, "receipt_missing"
        raw = ordered_poison_halt_clear_receipt_event(request)
        raw["operator_request_receipt"] = dict(request.operator_request_receipt)
        try:
            verified = await self.operator_request_receipt_gate.verify(raw)
        except ValueError as exc:
            return None, f"receipt_{_safe_reason(str(exc))}"
        if verified.receipt.producer_service_identity != self.trusted_operator_producer_id:
            return None, "receipt_wrong_producer"
        return verified, None

    def _validate_group_id(self, request: OrderedPoisonHaltClearRequest) -> str | None:
        single = f"{self.consumer_group_prefix}.{request.agent_name}"
        if request.group_id == single:
            return None
        safe_topic = request.topic.replace(".", "-")
        prefix = f"{single}.{safe_topic}."
        if not request.group_id.startswith(prefix):
            return "group_mismatch"
        ordinal = request.group_id.removeprefix(prefix)
        if not ordinal.isdecimal() or int(ordinal) < 1:
            return "group_mismatch"
        return None

    def _validate_request_freshness(
        self,
        request: OrderedPoisonHaltClearRequest,
    ) -> str | None:
        now = self.clock().astimezone(UTC)
        if request.requested_at > now:
            return "request_not_yet_valid"
        if now - request.requested_at > self.request_ttl:
            return "request_expired"
        return None

    async def _record_rejected_outcome(
        self,
        request: OrderedPoisonHaltClearRequest,
        reason: str,
    ) -> None:
        observed_at = self.clock().astimezone(UTC)
        outcome = {
            "schema_version": "1.0.0",
            "kind": "ordered_poison_halt_clear_outcome",
            "status": "rejected",
            "reason": reason,
            "request_id": request.request_id,
            "idempotency_key": request.idempotency_key,
            "group_id": request.group_id,
            "topic": request.topic,
            "halt_revision": request.halt_revision,
            "halt_record_digest": request.halt_record_digest,
            "requested_at": request.requested_at.isoformat(),
            "observed_at": observed_at.isoformat(),
        }
        key = ordered_poison_halt_clear_outcome_key(request.request_id)
        await self.audit_store.write_state(key, outcome)
        await self.audit_store.append_audit_entry(
            {
                "schema_version": "1.0.0",
                "agent": "Saga",
                "event_type": "ordered_poison_halt_clear_rejected",
                "request_id": request.request_id,
                "idempotency_key": request.idempotency_key,
                "group_id": request.group_id,
                "topic": request.topic,
                "reason": reason,
                "evidence_digest": canonical_digest(outcome),
            }
        )

    async def _find_parked_record(
        self,
        request: OrderedPoisonHaltClearRequest,
    ) -> Mapping[str, Any] | None:
        group = f"{self.consumer_group_prefix}.clear-evidence.{request.idempotency_key}"
        stream = self.bus.subscribe(request.parked_record_topic, group)
        try:
            try:
                async with asyncio.timeout(self.dlq_scan_timeout.total_seconds()):
                    for _ in range(self.dlq_scan_limit):
                        try:
                            envelope = await anext(stream)
                        except StopAsyncIteration:
                            return None
                        if (
                            envelope.key == request.parked_record_key
                            and envelope.offset == request.parked_record_offset
                            and canonical_digest(dict(envelope.payload))
                            == request.parked_record_digest
                        ):
                            return envelope.payload
            except TimeoutError:
                return None
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
        return None


def ordered_poison_halt_clear_outcome_key(request_id: str) -> str:
    return _CLEAR_OUTCOME_PREFIX + request_id


def _safe_reason(reason: str) -> str:
    normalized = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in reason.strip())
    return normalized[:64] or "invalid"


__all__ = [
    "OrderedPoisonHaltClearProcessor",
    "OrderedPoisonHaltClearResult",
    "ordered_poison_halt_clear_outcome_key",
]
