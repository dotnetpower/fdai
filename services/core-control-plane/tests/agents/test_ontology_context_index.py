"""Ontology ContextIndex ownership and typed-event isolation."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fdai.agents import PantheonRuntime, StateStoreAuditChainAdapter, request_context_index
from fdai.agents._framework.ontology_index import (
    ContextIndexMessage,
    ContextIndexWorkerBindings,
    IndexPhase,
    owned_context_index_handler,
)
from fdai.agents._framework.provider_adapters import _digest as audit_payload_digest
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _prepare() -> ContextIndexMessage:
    return ContextIndexMessage.create(
        phase="prepare",
        correlation_id="example-index-request",
        body={"request_ref": "example"},
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("producer_principal", "Mimir"),
        ("body", {"request_ref": "changed"}),
        ("execution_authority", True),
        ("phase", "terminal"),
    ],
)
def test_context_index_envelope_rejects_owner_content_and_authority_drift(
    field: str, value: object
) -> None:
    payload = _prepare().model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValueError):
        ContextIndexMessage.model_validate(payload)


async def test_owner_wrapper_publishes_only_the_exact_next_owned_phase() -> None:
    agent = Muninn()
    bus = AsyncMock()
    agent.bind_bus(bus)
    fallback = AsyncMock()
    message = _prepare()
    prepared = ContextIndexMessage.create(
        phase="prepared",
        correlation_id=message.correlation_id,
        body={"snapshot_ref": "example"},
    )
    worker = AsyncMock(return_value=prepared)
    bindings = ContextIndexWorkerBindings(muninn=worker, heimdall=AsyncMock(), saga=AsyncMock())
    handler = owned_context_index_handler(agent, bindings, fallback)
    await handler(message.topic, message.model_dump(mode="json"))
    fallback.assert_not_awaited()
    worker.assert_awaited_once()
    bus.publish.assert_awaited_once_with(
        "Muninn",
        "object.context-index",
        prepared.model_dump(mode="json"),
    )
    worker.return_value = ContextIndexMessage.create(
        phase="terminal",
        correlation_id=message.correlation_id,
        body={"result": "fabricated"},
    )
    with pytest.raises(ValueError, match="owned transition"):
        await handler(message.topic, message.model_dump(mode="json"))
    assert bus.publish.await_count == 1


async def test_context_index_cannot_enter_learning_fallback_or_wrong_topic() -> None:
    fallback = AsyncMock()
    handler = owned_context_index_handler(Norns(), None, fallback)
    message = ContextIndexMessage.create(
        phase="prepared",
        correlation_id="example-index-request",
        body={"snapshot_ref": "example"},
    )
    await handler(message.topic, message.model_dump(mode="json"))
    fallback.assert_not_awaited()
    with pytest.raises(ValueError, match="wrong owned topic"):
        await handler("object.event", message.model_dump(mode="json"))


async def test_missing_worker_and_nondurable_saga_fail_before_publication() -> None:
    message = _prepare()
    muninn = Muninn()
    muninn.bind_bus(AsyncMock())
    with pytest.raises(RuntimeError, match="binding is unavailable"):
        await owned_context_index_handler(muninn, None, AsyncMock())(
            message.topic,
            message.model_dump(mode="json"),
        )
    intent = ContextIndexMessage.create(
        phase="intent",
        correlation_id=message.correlation_id,
        body={"transition_ref": "example"},
    )
    saga = Saga()
    saga.bind_bus(AsyncMock())
    fallback = AsyncMock()
    with pytest.raises(RuntimeError, match="durable Saga"):
        await owned_context_index_handler(saga, None, fallback)(
            intent.topic,
            intent.model_dump(mode="json"),
        )
    fallback.assert_not_awaited()


async def test_runtime_delivers_every_phase_through_its_real_owned_subscription() -> None:
    provider = InMemoryEventBus()
    state = InMemoryStateStore()
    saga = Saga(audit_chain=StateStoreAuditChainAdapter(state))
    seen: list[tuple[str, str]] = []
    following: dict[str, IndexPhase] = {
        "prepare": "prepared",
        "prepared": "validated",
        "validated": "intent",
        "intent": "intent_sealed",
        "intent_sealed": "terminal",
        "terminal": "terminal_sealed",
        "terminal_sealed": "ready",
    }

    async def muninn(message: ContextIndexMessage) -> ContextIndexMessage:
        seen.append(("Muninn", message.phase))
        return ContextIndexMessage.create(
            phase=following[message.phase],
            correlation_id=message.correlation_id,
            body=message.body,
        )

    async def heimdall(message: ContextIndexMessage) -> ContextIndexMessage:
        seen.append(("Heimdall", message.phase))
        return ContextIndexMessage.create(
            phase="validated",
            correlation_id=message.correlation_id,
            body=message.body,
        )

    async def auditor(message: ContextIndexMessage) -> ContextIndexMessage:
        assert any(
            entry.topic == message.topic
            and entry.payload_digest == audit_payload_digest(message.model_dump(mode="json"))
            for entry in saga.audit_chain.entries
        )
        seen.append(("Saga", message.phase))
        return ContextIndexMessage.create(
            phase=following[message.phase],
            correlation_id=message.correlation_id,
            body=message.body,
        )

    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic="raw-events",
        saga=saga,
        context_index_workers=ContextIndexWorkerBindings(
            muninn=muninn, heimdall=heimdall, saga=auditor
        ),
    )
    await request_context_index(runtime, _prepare())
    for _ in range(8):
        await runtime.run()
    assert seen == [
        ("Muninn", "prepare"),
        ("Heimdall", "prepared"),
        ("Muninn", "validated"),
        ("Saga", "intent"),
        ("Muninn", "intent_sealed"),
        ("Saga", "terminal"),
        ("Muninn", "terminal_sealed"),
    ]
    assert not any(entry.topic == "object.verdict" for entry in saga.audit_chain.entries)
    assert await state.verify_chain()


async def test_invalid_envelope_diagnostics_do_not_disclose_raw_body() -> None:
    payload = _prepare().model_dump(mode="json")
    payload["body"] = "private-provider-marker"
    handler = owned_context_index_handler(Muninn(), None, AsyncMock())
    with pytest.raises(ValueError) as error:
        await handler("object.event", payload)
    assert "private-provider-marker" not in str(error.value)
