from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.bus_poison_clear import (
    OrderedPoisonHaltClearProcessor,
    ordered_poison_halt_clear_outcome_key,
)
from fdai.agents._framework.bus_poison_halt import halt_key, halt_record_digest
from fdai.agents._framework.huginn_operator_receipt import OperatorRequestReceiptGate
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.runtime_poison_clear import bind_ordered_poison_halt_clear
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


async def _drain_bridge(bridge: EventBusBridge) -> None:
    task = asyncio.create_task(bridge.run())
    try:
        await asyncio.wait_for(task, timeout=1)
    finally:
        await bridge.stop()


def _action_run_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "idempotency_key": "action-run-key",
        "correlation_id": "corr-one",
        "resource_id": "resource-one",
        "action_type": "ops.restart",
        "status": "failed",
    }


class _UnboundVerifier:
    def verify_operator_request_receipt(self, *, receipt: object, signing_bytes: bytes) -> bool:
        del receipt, signing_bytes
        return False


def _receipt_gate(
    store: InMemoryStateStore,
    *,
    trust_core: bool = False,
) -> OperatorRequestReceiptGate:
    trusted = {"operator-service": operator_request_public_key_from_seed(_OPERATOR_SEED)}
    if trust_core:
        trusted["core-control-plane"] = operator_request_public_key_from_seed(_OPERATOR_SEED)
    return OperatorRequestReceiptGate(
        verifier=_UnboundVerifier(),
        state_store=store,
        clock=lambda: _NOW,
        trusted_producer_public_keys=trusted,
    )


def _signed_clear_request(
    request: dict[str, Any],
    *,
    producer: str = "operator-service",
    seed: str = _OPERATOR_SEED,
) -> dict[str, Any]:
    validated = OrderedPoisonHaltClearRequest.model_validate(request)
    event = ordered_poison_halt_clear_receipt_event(validated)
    receipt = sign_operator_request_receipt(
        event,
        producer_service_identity=producer,
        private_key_seed=seed,
        issued_at=_NOW,
        expires_at=_NOW.replace(minute=5),
    )
    return {
        **validated.model_dump(mode="json"),
        "operator_request_receipt": receipt.model_dump(mode="json"),
    }


@pytest.mark.asyncio
async def test_ordered_poison_halt_clear_retains_evidence_and_resumes_consumer() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    bridge = EventBusBridge(
        provider=bus,
        registry=load_pantheon(),
        halt_state_store=store,
        handler_max_retries=0,
    )
    deliveries: list[dict[str, object]] = []

    async def handler(_topic: str, payload: dict[str, object]) -> None:
        if not deliveries:
            deliveries.append(payload)
            raise RuntimeError("park first record")
        deliveries.append(payload)

    bridge.subscribe(_TOPIC, _AGENT, handler)
    await bridge.publish("Thor", _TOPIC, _action_run_payload())
    await _drain_bridge(bridge)

    halt = await store.read_state(halt_key(_GROUP, _TOPIC))
    assert halt is not None
    dlq = [envelope async for envelope in bus.subscribe(f"{_TOPIC}.dlq", "dlq-evidence")]
    assert len(dlq) == 1
    request = {
        "request_id": "clear-one",
        "idempotency_key": "clear-key",
        "requested_at": _NOW,
        "principal_id": "owner-one",
        "principal_kind": OperatorPrincipalKind.HUMAN,
        "principal_roles": (OperatorRole.OWNER,),
        "group_id": _GROUP,
        "agent_name": _AGENT,
        "topic": _TOPIC,
        "halt_revision": halt["revision"],
        "halt_record_digest": halt_record_digest(halt),
        "parked_record_topic": f"{_TOPIC}.dlq",
        "parked_record_key": dlq[0].key,
        "parked_record_offset": dlq[0].offset,
        "parked_record_digest": canonical_digest(dict(dlq[0].payload)),
    }
    processor = OrderedPoisonHaltClearProcessor(
        bus=bus,
        halt_state_store=store,
        audit_store=store,
        operator_request_receipt_gate=_receipt_gate(store),
        clock=lambda: _NOW,
    )

    result = await processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, _signed_clear_request(request))
    assert result.status == "cleared"
    assert bridge.resume_ordered_consumer_after_clear(topic=_TOPIC, agent_name=_AGENT)
    for _ in range(100):
        await asyncio.sleep(0)
        if len(deliveries) == 2:
            break
    await bridge.stop()

    cleared = await store.read_state(halt_key(_GROUP, _TOPIC))
    assert cleared is not None
    assert cleared["status"] == "cleared"
    assert cleared["clear_evidence"]["parked_record_digest"] == request["parked_record_digest"]
    assert await store.verify_chain()
    assert [delivery["idempotency_key"] for delivery in deliveries] == [
        "action-run-key",
        "action-run-key",
    ]
    assert [delivery["correlation_id"] for delivery in deliveries] == ["corr-one", "corr-one"]


@pytest.mark.asyncio
async def test_ordered_poison_halt_clear_rejects_stale_or_missing_evidence() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    await store.write_state(
        halt_key(_GROUP, _TOPIC),
        {
            "schema_version": "1.0.0",
            "revision": 3,
            "status": "halted",
            "consumer_id": f"{_AGENT}:{_TOPIC}",
            "group_id": _GROUP,
            "topic": _TOPIC,
            "partition_key": "resource-one",
            "offset": 0,
        },
    )
    halt = await store.read_state(halt_key(_GROUP, _TOPIC))
    assert halt is not None
    processor = OrderedPoisonHaltClearProcessor(
        bus=bus,
        halt_state_store=store,
        audit_store=store,
        operator_request_receipt_gate=_receipt_gate(store),
        clock=lambda: _NOW,
    )
    request: dict[str, Any] = {
        "request_id": "clear-two",
        "idempotency_key": "clear-key-two",
        "requested_at": _NOW,
        "principal_id": "owner-one",
        "principal_kind": OperatorPrincipalKind.HUMAN,
        "principal_roles": (OperatorRole.OWNER,),
        "group_id": _GROUP,
        "agent_name": _AGENT,
        "topic": _TOPIC,
        "halt_revision": 2,
        "halt_record_digest": halt_record_digest(halt),
        "parked_record_topic": f"{_TOPIC}.dlq",
        "parked_record_key": "missing",
        "parked_record_offset": 0,
        "parked_record_digest": "sha256:" + "a" * 64,
    }

    result = await processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, _signed_clear_request(request))

    assert result == result.__class__("rejected", halted=True, reason="parked_missing")
    assert (await store.read_state(halt_key(_GROUP, _TOPIC)))["status"] == "halted"  # type: ignore[index]


@pytest.mark.asyncio
async def test_ordered_poison_halt_clear_rejects_unsigned_forged_owner() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
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
    request = {
        "request_id": "clear-unsigned",
        "idempotency_key": "clear-unsigned",
        "requested_at": _NOW,
        "principal_id": "forged-owner",
        "principal_kind": OperatorPrincipalKind.HUMAN,
        "principal_roles": (OperatorRole.OWNER,),
        "group_id": _GROUP,
        "agent_name": _AGENT,
        "topic": _TOPIC,
        "halt_revision": 1,
        "halt_record_digest": halt_record_digest(halt),
        "parked_record_topic": f"{_TOPIC}.dlq",
        "parked_record_key": "resource-one",
        "parked_record_offset": 0,
        "parked_record_digest": "sha256:" + "b" * 64,
    }
    processor = OrderedPoisonHaltClearProcessor(
        bus=bus,
        halt_state_store=store,
        audit_store=store,
        operator_request_receipt_gate=_receipt_gate(store),
        clock=lambda: _NOW,
    )

    result = await processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, request)

    assert result.reason == "receipt_missing"
    assert (await store.read_state(halt_key(_GROUP, _TOPIC)))["status"] == "halted"  # type: ignore[index]


@pytest.mark.asyncio
async def test_ordered_poison_halt_clear_rejects_wrong_producer_and_replay() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
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
    request = {
        "request_id": "clear-wrong-producer",
        "idempotency_key": "clear-wrong-producer",
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
        "parked_record_key": "resource-one",
        "parked_record_offset": 0,
        "parked_record_digest": "sha256:" + "b" * 64,
    }
    processor = OrderedPoisonHaltClearProcessor(
        bus=bus,
        halt_state_store=store,
        audit_store=store,
        operator_request_receipt_gate=_receipt_gate(store, trust_core=True),
        clock=lambda: _NOW,
    )
    wrong_producer = _signed_clear_request(request, producer="core-control-plane")

    first = await processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, wrong_producer)
    second = await processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, wrong_producer)

    assert first.reason == "receipt_wrong_producer"
    assert second.reason == "receipt_wrong_producer"
    assert (await store.read_state(halt_key(_GROUP, _TOPIC)))["status"] == "halted"  # type: ignore[index]


@pytest.mark.asyncio
async def test_ordered_poison_halt_clear_rejects_unrelated_parked_record() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    halt = {
        "schema_version": "1.0.0",
        "revision": 1,
        "status": "halted",
        "consumer_id": f"{_AGENT}:{_TOPIC}",
        "group_id": _GROUP,
        "topic": _TOPIC,
        "partition_key": "resource-a",
        "offset": 0,
    }
    halt["halt_record_digest"] = halt_record_digest(halt)
    await store.write_state(halt_key(_GROUP, _TOPIC), halt)
    parked = {
        "payload": "unrelated",
        "__fdai_dlq_metadata__": {
            "consumer_group": _GROUP,
            "agent": _AGENT,
            "topic": _TOPIC,
            "offset": 3,
        },
    }
    await bus.dead_letter(_TOPIC, "resource-b", parked, reason="handler error")
    dlq = [envelope async for envelope in bus.subscribe(f"{_TOPIC}.dlq", "dlq-evidence")]
    request = {
        "request_id": "clear-unrelated",
        "idempotency_key": "clear-unrelated",
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
    processor = OrderedPoisonHaltClearProcessor(
        bus=bus,
        halt_state_store=store,
        audit_store=store,
        operator_request_receipt_gate=_receipt_gate(store),
        clock=lambda: _NOW,
    )

    result = await processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, _signed_clear_request(request))

    assert result.reason == "halt_mismatch"
    assert (await store.read_state(halt_key(_GROUP, _TOPIC)))["status"] == "halted"  # type: ignore[index]


@pytest.mark.asyncio
async def test_ordered_poison_halt_clear_accepts_halted_multi_handler_group() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    group = f"fdai-pantheon.{_AGENT}.object-action-run.1"
    halt = {
        "schema_version": "1.0.0",
        "revision": 1,
        "status": "halted",
        "consumer_id": f"{_AGENT}:{_TOPIC}#1",
        "group_id": group,
        "topic": _TOPIC,
        "partition_key": "resource-one",
        "offset": 0,
    }
    halt["halt_record_digest"] = halt_record_digest(halt)
    await store.write_state(halt_key(group, _TOPIC), halt)
    parked = {
        "payload": "halted",
        "__fdai_dlq_metadata__": {
            "consumer_group": group,
            "agent": _AGENT,
            "topic": _TOPIC,
            "offset": 0,
        },
    }
    await bus.dead_letter(_TOPIC, "resource-one", parked, reason="handler error")
    dlq = [envelope async for envelope in bus.subscribe(f"{_TOPIC}.dlq", "dlq-evidence")]
    request = {
        "request_id": "clear-multi",
        "idempotency_key": "clear-multi",
        "requested_at": _NOW,
        "principal_id": "owner-one",
        "principal_kind": OperatorPrincipalKind.HUMAN,
        "principal_roles": (OperatorRole.OWNER,),
        "group_id": group,
        "agent_name": _AGENT,
        "topic": _TOPIC,
        "halt_revision": 1,
        "halt_record_digest": halt_record_digest(halt),
        "parked_record_topic": f"{_TOPIC}.dlq",
        "parked_record_key": dlq[0].key,
        "parked_record_offset": dlq[0].offset,
        "parked_record_digest": canonical_digest(dict(dlq[0].payload)),
    }
    processor = OrderedPoisonHaltClearProcessor(
        bus=bus,
        halt_state_store=store,
        audit_store=store,
        operator_request_receipt_gate=_receipt_gate(store),
        clock=lambda: _NOW,
    )

    result = await processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, _signed_clear_request(request))

    assert result.status == "cleared"
    assert (await store.read_state(halt_key(group, _TOPIC)))["status"] == "cleared"  # type: ignore[index]


@pytest.mark.asyncio
async def test_ordered_poison_halt_clear_rejects_expired_request() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
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
    request = {
        "request_id": "clear-expired",
        "idempotency_key": "clear-expired",
        "requested_at": datetime(2026, 10, 1, 11, 54, tzinfo=UTC),
        "principal_id": "owner-one",
        "principal_kind": OperatorPrincipalKind.HUMAN,
        "principal_roles": (OperatorRole.OWNER,),
        "group_id": _GROUP,
        "agent_name": _AGENT,
        "topic": _TOPIC,
        "halt_revision": 1,
        "halt_record_digest": halt_record_digest(halt),
        "parked_record_topic": f"{_TOPIC}.dlq",
        "parked_record_key": "resource-one",
        "parked_record_offset": 0,
        "parked_record_digest": "sha256:" + "b" * 64,
    }
    processor = OrderedPoisonHaltClearProcessor(
        bus=bus,
        halt_state_store=store,
        audit_store=store,
        operator_request_receipt_gate=_receipt_gate(store),
        clock=lambda: _NOW,
    )

    result = await processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, _signed_clear_request(request))

    assert result.reason == "request_expired"
    assert (await store.read_state(halt_key(_GROUP, _TOPIC)))["status"] == "halted"  # type: ignore[index]


@pytest.mark.asyncio
async def test_runtime_records_rejected_clear_outcome_and_counter() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    bridge = EventBusBridge(provider=bus, registry=load_pantheon(), halt_state_store=store)
    bind_ordered_poison_halt_clear(
        bridge=bridge,
        provider=bus,
        state_store=store,
        consumer_group_prefix="fdai-pantheon",
        operator_request_receipt_gate=_receipt_gate(store),
        clock=lambda: _NOW,
    )
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
    request = {
        "request_id": "clear-recorded-reject",
        "idempotency_key": "clear-recorded-reject",
        "requested_at": _NOW,
        "principal_id": "owner-one",
        "principal_kind": OperatorPrincipalKind.HUMAN,
        "principal_roles": (OperatorRole.OWNER,),
        "group_id": "fdai-pantheon.Thor",
        "agent_name": _AGENT,
        "topic": _TOPIC,
        "halt_revision": 1,
        "halt_record_digest": halt_record_digest(halt),
        "parked_record_topic": f"{_TOPIC}.dlq",
        "parked_record_key": "resource-one",
        "parked_record_offset": 0,
        "parked_record_digest": "sha256:" + "b" * 64,
    }

    await bus.publish(
        ORDERED_POISON_HALT_CLEAR_TOPIC,
        "clear-recorded-reject",
        _signed_clear_request(request),
    )
    await _drain_bridge(bridge)

    outcome = await store.read_state(ordered_poison_halt_clear_outcome_key("clear-recorded-reject"))
    assert outcome is not None
    assert outcome["status"] == "rejected"
    assert outcome["reason"] == "group_mismatch"
    assert bridge.metrics.ordered_poison_clear_rejections == 1


@pytest.mark.asyncio
async def test_runtime_rejects_executable_hil_verdict_missing_safeguards() -> None:
    bus = InMemoryEventBus()
    runtime = PantheonRuntime.build(provider=bus, raw_event_topic="object.event")

    with pytest.raises(ValueError, match="executable verdict missing safeguard"):
        await runtime.bridge.publish(
            "Forseti",
            "object.verdict",
            {
                "schema_version": "1.0.0",
                "idempotency_key": "verdict-hil-missing-safeguards",
                "correlation_id": "corr-hil-missing-safeguards",
                "resource_id": "resource-one",
                "risk_verdict": "hil",
                "resolved_autonomy_ceiling": "enforce_hil",
                "action_type": "ops.restart",
            },
        )
