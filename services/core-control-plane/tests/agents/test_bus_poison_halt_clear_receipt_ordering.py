from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.agents._framework.bus_poison_clear import OrderedPoisonHaltClearProcessor
from fdai.agents._framework.bus_poison_halt import halt_key, halt_record_digest
from fdai.agents._framework.huginn_operator_receipt import OperatorRequestReceiptGate
from fdai.shared.providers.testing import InMemoryEventBus, InMemoryStateStore
from fdai_service_contracts.bus_poison_halt_clear import (
    ORDERED_POISON_HALT_CLEAR_TOPIC,
    OrderedPoisonHaltClearRequest,
    ordered_poison_halt_clear_receipt_event,
)
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.operator import OperatorPrincipalKind, OperatorRole
from fdai_service_contracts.operator_request_receipt import (
    operator_request_public_key_from_seed,
    sign_operator_request_receipt,
)

_TOPIC = "object.action-run"
_AGENT = "Vidar"
_GROUP = f"fdai-pantheon.{_AGENT}"
_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_OPERATOR_SEED = "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE"


class _UnboundVerifier:
    def verify_operator_request_receipt(self, *, receipt: object, signing_bytes: bytes) -> bool:
        del receipt, signing_bytes
        return False


class _ClearCasRaisesOnceStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.raises_remaining = 1

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if self.raises_remaining:
            self.raises_remaining -= 1
            raise RuntimeError("simulated clear storage failure")
        return await super().compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=expected_revision,
            audit_entry=audit_entry,
        )


class _FinalizeFailsOnceStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.finalize_failures_remaining = 1

    async def compare_and_set_state(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> bool:
        if key.startswith("pantheon/huginn/operator-request-receipts/"):
            if self.finalize_failures_remaining:
                self.finalize_failures_remaining -= 1
                return False
        return await super().compare_and_set_state(
            key,
            value,
            expected_revision=expected_revision,
        )


def _receipt_gate(store: InMemoryStateStore) -> OperatorRequestReceiptGate:
    return OperatorRequestReceiptGate(
        verifier=_UnboundVerifier(),
        state_store=store,
        clock=lambda: _NOW,
        trusted_producer_public_keys={
            "operator-service": operator_request_public_key_from_seed(_OPERATOR_SEED)
        },
    )


def _signed_clear_request(request: dict[str, Any]) -> dict[str, Any]:
    validated = OrderedPoisonHaltClearRequest.model_validate(request)
    event = ordered_poison_halt_clear_receipt_event(validated)
    receipt = sign_operator_request_receipt(
        event,
        producer_service_identity="operator-service",
        private_key_seed=_OPERATOR_SEED,
        issued_at=_NOW,
        expires_at=_NOW.replace(minute=5),
    )
    return {
        **validated.model_dump(mode="json"),
        "operator_request_receipt": receipt.model_dump(mode="json"),
    }


async def _parked_clear_request(
    bus: InMemoryEventBus,
    store: InMemoryStateStore,
    *,
    request_id: str,
) -> dict[str, Any]:
    halt = {
        "schema_version": "1.0.0",
        "revision": 1,
        "status": "halted",
        "consumer_id": f"{_AGENT}:{_TOPIC}",
        "group_id": _GROUP,
        "topic": _TOPIC,
        "partition_key": "resource-one",
        "offset": 0,
    }
    halt["halt_record_digest"] = halt_record_digest(halt)
    await store.write_state(halt_key(_GROUP, _TOPIC), halt)
    parked = {
        "payload": "halted",
        "__fdai_dlq_metadata__": {
            "consumer_group": _GROUP,
            "agent": _AGENT,
            "topic": _TOPIC,
            "offset": 0,
        },
    }
    await bus.dead_letter(_TOPIC, "resource-one", parked, reason="handler error")
    dlq = [envelope async for envelope in bus.subscribe(f"{_TOPIC}.dlq", "dlq-evidence")]
    return {
        "request_id": request_id,
        "idempotency_key": request_id,
        "requested_at": _NOW,
        "principal_id": "owner-one",
        "principal_kind": OperatorPrincipalKind.HUMAN,
        "principal_roles": (OperatorRole.OWNER,),
        "group_id": _GROUP,
        "agent_name": _AGENT,
        "topic": _TOPIC,
        "halt_revision": 1,
        "halt_record_digest": halt_record_digest(halt),
        "parked_record_topic": f"{_TOPIC}.dlq",
        "parked_record_key": dlq[0].key,
        "parked_record_offset": dlq[0].offset,
        "parked_record_digest": canonical_digest(dict(dlq[0].payload)),
    }


@pytest.mark.asyncio
async def test_clear_cas_failure_releases_receipt_for_same_signed_retry() -> None:
    bus = InMemoryEventBus()
    store = _ClearCasRaisesOnceStore()
    request = await _parked_clear_request(bus, store, request_id="clear-retryable")
    processor = OrderedPoisonHaltClearProcessor(
        bus=bus,
        halt_state_store=store,
        audit_store=store,
        operator_request_receipt_gate=_receipt_gate(store),
        clock=lambda: _NOW,
    )
    signed = _signed_clear_request(request)

    with pytest.raises(RuntimeError, match="simulated clear storage failure"):
        await processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, signed)

    assert await store.read_states("pantheon/huginn/operator-request-receipts/", limit=10) == ()

    result = await processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, signed)

    assert result.status == "cleared"
    cleared = await store.read_state(halt_key(_GROUP, _TOPIC))
    assert cleared is not None
    assert cleared["status"] == "cleared"
    assert await store.verify_chain()


@pytest.mark.asyncio
async def test_finalize_failure_after_clear_reports_applied_but_unfinalized() -> None:
    bus = InMemoryEventBus()
    store = _FinalizeFailsOnceStore()
    request = await _parked_clear_request(bus, store, request_id="clear-finalize-fails")
    processor = OrderedPoisonHaltClearProcessor(
        bus=bus,
        halt_state_store=store,
        audit_store=store,
        operator_request_receipt_gate=_receipt_gate(store),
        clock=lambda: _NOW,
    )

    result = await processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, _signed_clear_request(request))

    assert result.status == "applied_but_unfinalized"
    assert result.halted is False
    assert result.reason == "receipt_finalize_replayed"
    cleared = await store.read_state(halt_key(_GROUP, _TOPIC))
    assert cleared is not None
    assert cleared["status"] == "cleared"
    outcome = await store.read_state(
        "pantheon/bus/ordered-poison-halt-clear-outcomes/clear-finalize-fails"
    )
    assert outcome is not None
    assert outcome["status"] == "applied_but_unfinalized"
    assert await store.verify_chain()
