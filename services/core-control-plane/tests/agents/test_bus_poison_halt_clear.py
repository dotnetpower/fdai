from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
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
    OperatorRequestReceipt,
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


class _CommitFailingReceiptGate:
    async def verify(self, raw: Mapping[str, Any]) -> Any:
        receipt = OperatorRequestReceipt.model_validate(raw["operator_request_receipt"])
        return type("Verified", (), {"receipt": receipt, "replay_key": "replay-key"})()

    async def reserve(self, _verified: Any) -> Any:
        raise ValueError("expired")


class _FinalizeFailingReceiptGate:
    async def verify(self, raw: Mapping[str, Any]) -> Any:
        receipt = OperatorRequestReceipt.model_validate(raw["operator_request_receipt"])
        return type("Verified", (), {"receipt": receipt, "replay_key": "replay-key"})()

    async def reserve(self, _verified: Any) -> Any:
        return object()

    async def finalize(self, _reservation: Any) -> None:
        raise ValueError("store unavailable")

    async def release(self, _reservation: Any) -> None:
        return None


class _NeverDlqBus(InMemoryEventBus):
    def subscribe(self, topic: str, group_id: str) -> Any:
        if topic.endswith(".dlq"):
            return _NeverStream()
        return super().subscribe(topic, group_id)


class _NeverStream:
    def __aiter__(self) -> _NeverStream:
        return self

    async def __anext__(self) -> Any:
        await asyncio.Event().wait()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        return None


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
async def test_runtime_poison_clear_resumes_applied_but_unfinalized_consumer() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    bridge = EventBusBridge(provider=bus, registry=load_pantheon(), halt_state_store=store)
    resume_calls: list[tuple[str, str, str | None]] = []

    async def handler(_topic: str, _payload: dict[str, object]) -> None:
        return None

    def record_resume(*, topic: str, agent_name: str, group_id: str | None = None) -> bool:
        resume_calls.append((topic, agent_name, group_id))
        return True

    bridge.subscribe(_TOPIC, _AGENT, handler)
    bridge.resume_ordered_consumer_after_clear = record_resume  # type: ignore[method-assign]
    bind_ordered_poison_halt_clear(
        bridge=bridge,
        provider=bus,
        state_store=store,
        consumer_group_prefix="fdai-pantheon",
        operator_request_receipt_gate=_FinalizeFailingReceiptGate(),  # type: ignore[arg-type]
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
    parked = {
        "payload": _action_run_payload(),
        "__fdai_dlq_metadata__": {
            "consumer_group": _GROUP,
            "agent": _AGENT,
            "topic": _TOPIC,
            "offset": 0,
        },
    }
    await bus.dead_letter(_TOPIC, "resource-one", parked, reason="handler error")
    dlq = [envelope async for envelope in bus.subscribe(f"{_TOPIC}.dlq", "dlq-evidence")]
    request = {
        "request_id": "clear-applied-unfinalized-runtime",
        "idempotency_key": "clear-applied-unfinalized-runtime",
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
    clear_handler = bridge._subs[ORDERED_POISON_HALT_CLEAR_TOPIC][0][1]

    await clear_handler(ORDERED_POISON_HALT_CLEAR_TOPIC, _signed_clear_request(request))

    assert resume_calls == [(_TOPIC, _AGENT, _GROUP)]
    assert bridge.metrics.ordered_poison_clear_applied_unfinalized == 1
    assert bridge.metrics.ordered_poison_clear_rejections == 0
    outcome = await store.read_state(
        ordered_poison_halt_clear_outcome_key("clear-applied-unfinalized-runtime")
    )
    assert outcome is not None
    assert outcome["status"] == "applied_but_unfinalized"


@pytest.mark.asyncio
async def test_runtime_poison_clear_records_resume_failure_without_crashing() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    bridge = EventBusBridge(provider=bus, registry=load_pantheon(), halt_state_store=store)

    async def handler(_topic: str, _payload: dict[str, object]) -> None:
        return None

    def fail_resume(*, topic: str, agent_name: str, group_id: str | None = None) -> bool:
        del topic, agent_name, group_id
        raise RuntimeError("consumer restart unavailable")

    bridge.subscribe(_TOPIC, _AGENT, handler)
    bridge.resume_ordered_consumer_after_clear = fail_resume  # type: ignore[method-assign]
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
    parked = {
        "payload": _action_run_payload(),
        "__fdai_dlq_metadata__": {
            "consumer_group": _GROUP,
            "agent": _AGENT,
            "topic": _TOPIC,
            "offset": 0,
        },
    }
    await bus.dead_letter(_TOPIC, "resource-one", parked, reason="handler error")
    dlq = [envelope async for envelope in bus.subscribe(f"{_TOPIC}.dlq", "dlq-evidence")]
    request = {
        "request_id": "clear-resume-fails-runtime",
        "idempotency_key": "clear-resume-fails-runtime",
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
    clear_handler = bridge._subs[ORDERED_POISON_HALT_CLEAR_TOPIC][0][1]

    await clear_handler(ORDERED_POISON_HALT_CLEAR_TOPIC, _signed_clear_request(request))

    assert bridge.metrics.ordered_poison_clear_resume_failures == 1
    assert bridge.metrics.ordered_poison_clear_rejections == 0
    assert bridge.metrics.recent_rejections()[-1] == {
        "topic": _TOPIC,
        "reason": "ordered poison halt clear resume failed: RuntimeError",
        "principal": "ordered-poison-halt-clear",
        "consumer_group": _GROUP,
        "offset": None,
        "correlation_id": "",
        "idempotency_key": "clear-resume-fails-runtime",
        "producer_principal": "",
    }


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
async def test_ordered_poison_halt_clear_keeps_halt_when_receipt_commit_fails() -> None:
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
    request = {
        "request_id": "clear-commit-fails",
        "idempotency_key": "clear-commit-fails",
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
        operator_request_receipt_gate=_CommitFailingReceiptGate(),  # type: ignore[arg-type]
        clock=lambda: _NOW,
    )

    result = await processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, _signed_clear_request(request))

    assert result.reason == "receipt_expired"
    assert (await store.read_state(halt_key(_GROUP, _TOPIC)))["status"] == "halted"  # type: ignore[index]


@pytest.mark.asyncio
async def test_ordered_poison_halt_clear_bounds_parked_record_scan_by_timeout() -> None:
    bus = _NeverDlqBus()
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
        "request_id": "clear-scan-timeout",
        "idempotency_key": "clear-scan-timeout",
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
        operator_request_receipt_gate=_receipt_gate(store),
        clock=lambda: _NOW,
        dlq_scan_timeout=timedelta(milliseconds=10),
    )

    result = await asyncio.wait_for(
        processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, _signed_clear_request(request)),
        timeout=1,
    )

    assert result.reason == "parked_missing"
    assert (await store.read_state(halt_key(_GROUP, _TOPIC)))["status"] == "halted"  # type: ignore[index]


@pytest.mark.asyncio
async def test_resume_after_clear_targets_exact_halted_ordinal_consumer() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    bridge = EventBusBridge(provider=bus, registry=load_pantheon(), halt_state_store=store)

    async def handler_one(_topic: str, _payload: dict[str, object]) -> None:
        return None

    async def handler_two(_topic: str, _payload: dict[str, object]) -> None:
        return None

    bridge.subscribe(_TOPIC, _AGENT, handler_one)
    bridge.subscribe(_TOPIC, _AGENT, handler_two)
    group = f"fdai-pantheon.{_AGENT}.object-action-run.1"
    bridge._consumer_states[f"{_AGENT}:{_TOPIC}#1"] = "halted"  # noqa: SLF001
    bridge._consumer_states[f"{_AGENT}:{_TOPIC}#2"] = "halted"  # noqa: SLF001

    resumed = bridge.resume_ordered_consumer_after_clear(
        topic=_TOPIC,
        agent_name=_AGENT,
        group_id=group,
    )

    assert resumed is True
    assert bridge._consumer_states[f"{_AGENT}:{_TOPIC}#1"] == "cleared"  # noqa: SLF001
    assert bridge._consumer_states[f"{_AGENT}:{_TOPIC}#2"] == "halted"  # noqa: SLF001
    assert [task.get_name() for task in bridge._tasks] == [  # noqa: SLF001
        f"pantheon-consumer.{_AGENT}:{_TOPIC}#1"
    ]
    await bridge.stop()


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
