"""Core-side processing for Operator ordered-poison-halt clear requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai_service_contracts.bus_poison_halt_clear import OrderedPoisonHaltClearRequest
from fdai_service_contracts.compatibility import canonical_digest

from fdai.agents._framework.bus_poison_halt import clear_ordered_halt_with_evidence
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore


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
    consumer_group_prefix: str = "fdai-pantheon"
    dlq_scan_limit: int = 100

    async def handle(
        self,
        _topic: str,
        payload: Mapping[str, object],
    ) -> OrderedPoisonHaltClearResult:
        request = OrderedPoisonHaltClearRequest.model_validate(payload)
        expected_group = f"{self.consumer_group_prefix}.{request.agent_name}"
        if request.group_id != expected_group:
            return OrderedPoisonHaltClearResult("rejected", halted=True, reason="group_mismatch")
        parked = await self._find_parked_record(request)
        if parked is None:
            return OrderedPoisonHaltClearResult("rejected", halted=True, reason="parked_missing")
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
        }
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
            return OrderedPoisonHaltClearResult("rejected", halted=True, reason="halt_mismatch")
        return OrderedPoisonHaltClearResult("cleared", halted=False)

    async def _find_parked_record(
        self,
        request: OrderedPoisonHaltClearRequest,
    ) -> Mapping[str, Any] | None:
        group = f"{self.consumer_group_prefix}.clear-evidence.{request.idempotency_key}"
        stream = self.bus.subscribe(request.parked_record_topic, group)
        try:
            for _ in range(self.dlq_scan_limit):
                try:
                    envelope = await anext(stream)
                except StopAsyncIteration:
                    return None
                if (
                    envelope.key == request.parked_record_key
                    and envelope.offset == request.parked_record_offset
                    and canonical_digest(dict(envelope.payload)) == request.parked_record_digest
                ):
                    return envelope.payload
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
        return None


__all__ = ["OrderedPoisonHaltClearProcessor", "OrderedPoisonHaltClearResult"]
