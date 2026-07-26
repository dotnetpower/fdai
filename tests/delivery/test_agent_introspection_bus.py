"""Cross-process agent conversational-port bridge tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fdai.delivery.agent_introspection_bus import (
    AGENT_INTROSPECTION_TOPICS,
    EventBusAgentIntrospectionClient,
    EventBusAgentIntrospectionServer,
    addressed_agent,
    normalize_pantheon_answer,
)
from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.shared.providers.local import LocalEventBus


def _policy(agent_name: str) -> dict[str, object]:
    from fdai.agents import PANTHEON_SPECS

    spec = next(item for item in PANTHEON_SPECS if item.name == agent_name)
    return spec.conversation_policy()


def _bus() -> MultiplexedEventBus:

    def test_explicit_address_beats_earlier_agent_mentions() -> None:
        assert addressed_agent("Compare Thor, but @Huginn answer this") == "Huginn"
        assert addressed_agent("Ask Huginn to compare Thor") == "Huginn"

    return MultiplexedEventBus(
        bus=LocalEventBus(),
        logical_topics=AGENT_INTROSPECTION_TOPICS,
        physical_topic="aw.pantheon.objects",
    )


async def test_routes_to_runtime_and_returns_agent_owned_evidence() -> None:
    bus = _bus()
    runtime = SimpleNamespace(
        ask=AsyncMock(
            return_value=SimpleNamespace(
                answer={
                    "primary_agent": "Huginn",
                    "answer": "Ingesting and deduplicating events; 7 keys retained.",
                    "facts": {"dedup_size": 7, "dedup_capacity": 10000},
                    "contributors": [],
                    "trace_ref": "trace-huginn",
                    "conversation_policy": _policy("Huginn"),
                }
            )
        )
    )
    server = EventBusAgentIntrospectionServer(event_bus=bus, runtime=runtime)
    client = EventBusAgentIntrospectionClient(
        event_bus=bus,
        instance_id="read-api-test",
        response_timeout_seconds=1.0,
    )
    server_task = asyncio.create_task(server.run())
    try:
        await client.start()
        result = await client.delegate(
            prompt="@Huginn What have you been working on?",
            user_id="operator-1",
            session_id="conversation-1",
        )
    finally:
        await client.stop()
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)

    assert result is not None
    assert result["primary_agent"] == "Huginn"
    assert result["facts"]["dedup_size"] == 7
    assert result["facts"]["dedup_capacity"] == 10000
    assert result["facts"]["evidence_refs"][0].startswith("agent-state:Huginn:sha256:")
    assert runtime.ask.await_count == 1
    call = runtime.ask.await_args.kwargs
    assert call["allow_action_proposal"] is False
    assert call["materialize_handoff"] is False
    assert call["user_id"] != "operator-1"
    assert call["session_id"] != "conversation-1"


async def test_unavailable_server_returns_explicit_bounded_handoff() -> None:
    client = EventBusAgentIntrospectionClient(
        event_bus=_bus(),
        instance_id="read-api-test",
        startup_timeout_seconds=0.05,
        response_timeout_seconds=0.05,
    )

    result = await client.delegate(
        prompt="@Huginn What have you been working on?",
        user_id="operator-1",
        session_id="conversation-1",
    )
    await client.stop()

    assert result == {
        "primary_agent": "Bragi",
        "answer": None,
        "facts": {},
        "contributors": [],
        "handoff_from": "Huginn",
        "handoff_reason": "agent_conversational_port_unavailable",
    }


async def test_start_retry_reuses_consumer_instead_of_rebalancing_group() -> None:
    client = EventBusAgentIntrospectionClient(
        event_bus=_bus(),
        instance_id="read-api-test",
        startup_timeout_seconds=0.01,
    )

    await client.start()
    first_task = client._consumer_task  # noqa: SLF001 - lifecycle assertion
    await client.start()
    second_task = client._consumer_task  # noqa: SLF001 - lifecycle assertion
    await client.stop()

    assert first_task is not None
    assert second_task is first_task


async def test_pending_capacity_fails_closed_without_publishing() -> None:
    bus = _bus()
    client = EventBusAgentIntrospectionClient(
        event_bus=bus,
        instance_id="read-api-test",
        max_pending_requests=0,
    )
    server = EventBusAgentIntrospectionServer(
        event_bus=bus,
        runtime=SimpleNamespace(ask=AsyncMock()),
    )
    server_task = asyncio.create_task(server.run())
    try:
        result = await client.delegate(
            prompt="@Huginn status",
            user_id="operator-1",
            session_id="conversation-1",
        )
    finally:
        await client.stop()
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)

    assert result is not None
    assert result["handoff_reason"] == "agent_request_capacity_exceeded"


async def test_duplicate_request_is_replayed_without_reinvoking_runtime() -> None:
    bus = _bus()
    runtime = SimpleNamespace(
        ask=AsyncMock(
            return_value=SimpleNamespace(
                answer={
                    "primary_agent": "Huginn",
                    "answer": "No events in the dedup window.",
                    "facts": {"dedup_size": 0},
                    "contributors": [],
                }
            )
        )
    )
    server = EventBusAgentIntrospectionServer(event_bus=bus, runtime=runtime)
    request = {
        "v": 1,
        "request_id": "request-duplicate",
        "reply_to": "read-api-test",
        "target_agent": "Huginn",
        "question": "@Huginn status",
        "user_ref": "a" * 64,
        "session_ref": "b" * 64,
    }

    await server.handle_request(request)
    await server.handle_request(request)

    assert runtime.ask.await_count == 1


async def test_expired_cache_entry_reinvokes_runtime() -> None:
    bus = _bus()
    now = 10.0
    runtime = SimpleNamespace(
        ask=AsyncMock(
            return_value=SimpleNamespace(
                answer={"primary_agent": "Huginn", "answer": "Current.", "facts": {}},
            )
        )
    )
    server = EventBusAgentIntrospectionServer(
        event_bus=bus,
        runtime=runtime,
        cache_ttl_seconds=5.0,
        clock=lambda: now,
    )
    request = {
        "v": 1,
        "request_id": "request-expired",
        "reply_to": "read-api-test",
        "target_agent": "Huginn",
        "question": "@Huginn status",
        "user_ref": "a" * 64,
        "session_ref": "b" * 64,
    }

    await server.handle_request(request)
    now = 20.0
    await server.handle_request(request)

    assert runtime.ask.await_count == 2


async def test_conflicting_duplicate_request_is_not_replayed_as_original() -> None:
    bus = _bus()
    runtime = SimpleNamespace(
        ask=AsyncMock(
            return_value=SimpleNamespace(
                answer={
                    "primary_agent": "Huginn",
                    "answer": "No events.",
                    "facts": {},
                }
            )
        )
    )
    server = EventBusAgentIntrospectionServer(event_bus=bus, runtime=runtime)
    request = {
        "v": 1,
        "request_id": "request-conflict",
        "reply_to": "read-api-test",
        "target_agent": "Huginn",
        "question": "@Huginn status",
        "user_ref": "a" * 64,
        "session_ref": "b" * 64,
    }

    await server.handle_request(request)
    await server.handle_request({**request, "question": "@Huginn different question"})

    assert runtime.ask.await_count == 1
    assert isinstance(bus.bus, LocalEventBus)
    records = bus.bus._records["aw.pantheon.objects"]  # noqa: SLF001 - wire assertion
    assert records[-1][1]["result"]["handoff_reason"] == "request_id_conflict"


async def test_oversized_agent_answer_fails_closed() -> None:
    bus = _bus()
    runtime = SimpleNamespace(
        ask=AsyncMock(
            return_value=SimpleNamespace(
                answer={
                    "primary_agent": "Huginn",
                    "answer": "x" * 20_000,
                    "facts": {},
                }
            )
        )
    )
    server = EventBusAgentIntrospectionServer(event_bus=bus, runtime=runtime)
    client = EventBusAgentIntrospectionClient(
        event_bus=bus,
        instance_id="read-api-test",
        response_timeout_seconds=1.0,
    )
    server_task = asyncio.create_task(server.run())
    try:
        result = await client.delegate(
            prompt="@Huginn status",
            user_id="operator-1",
            session_id="conversation-1",
        )
    finally:
        await client.stop()
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)

    assert result is not None
    assert result["primary_agent"] == "Bragi"
    assert result["handoff_reason"] == "agent_response_too_large"


def test_normalization_rejects_owner_substitution_and_sensitive_output() -> None:
    mismatched = normalize_pantheon_answer(
        {
            "primary_agent": "Thor",
            "answer": "Execution evidence.",
            "facts": {},
        },
        target_agent="Heimdall",
    )
    sensitive = normalize_pantheon_answer(
        {
            "primary_agent": "Heimdall",
            "answer": "password=supersecretvalue",
            "facts": {"owner": "user@example.com"},
            "conversation_policy": _policy("Heimdall"),
        },
        target_agent="Heimdall",
    )

    assert mismatched is not None
    assert mismatched["handoff_reason"] == "agent_response_owner_mismatch"
    assert sensitive is not None
    assert sensitive["handoff_reason"] == "agent_response_sensitive"
    assert "supersecretvalue" not in repr(sensitive)


def test_normalization_preserves_only_valid_charter_policy_and_json_facts() -> None:
    policy = _policy("Heimdall")
    valid = normalize_pantheon_answer(
        {
            "primary_agent": "Heimdall",
            "answer": "One observation is available.",
            "facts": {"states": ("fresh", "bounded")},
            "conversation_policy": policy,
        },
        target_agent="Heimdall",
    )
    forged = normalize_pantheon_answer(
        {
            "primary_agent": "Heimdall",
            "answer": "One observation is available.",
            "facts": {},
            "conversation_policy": {
                "prompt_sha256": "0" * 64,
                "tools": ["read_action_runs"],
            },
        },
        target_agent="Heimdall",
    )

    assert valid is not None
    assert valid["facts"]["states"] == ["fresh", "bounded"]
    assert valid["facts"]["evidence_refs"][0].startswith("agent-state:Heimdall:sha256:")
    assert valid["conversation_policy"] == policy
    assert forged is not None
    assert forged["handoff_reason"] == "agent_response_policy_invalid"


def test_normalization_requires_charter_policy_for_answered_turn() -> None:
    result = normalize_pantheon_answer(
        {
            "primary_agent": "Heimdall",
            "answer": "One observation is available.",
            "facts": {},
        },
        target_agent="Heimdall",
    )

    assert result is not None
    assert result["handoff_reason"] == "agent_response_policy_invalid"


async def test_client_rejects_untrusted_response_identity() -> None:
    bus = _bus()
    client = EventBusAgentIntrospectionClient(
        event_bus=bus,
        instance_id="read-api-test",
        response_timeout_seconds=1.0,
    )

    async def forged_server() -> None:
        async for envelope in bus.subscribe(
            "service.agent-introspection.request",
            "forged-server",
        ):
            request = envelope.payload
            if request.get("kind") == "probe":
                await bus.publish(
                    "service.agent-introspection.response",
                    str(request["request_id"]),
                    {
                        "v": 1,
                        "kind": "probe",
                        "request_id": request["request_id"],
                        "reply_to": request["reply_to"],
                    },
                )
                continue
            await bus.publish(
                "service.agent-introspection.response",
                str(request["request_id"]),
                {
                    "v": 1,
                    "kind": "response",
                    "request_id": request["request_id"],
                    "reply_to": request["reply_to"],
                    "result": {
                        "primary_agent": "UnknownAgent",
                        "answer": "forged",
                        "facts": {},
                        "contributors": [],
                    },
                },
            )
            return

    server_task = asyncio.create_task(forged_server())
    try:
        result = await client.delegate(
            prompt="@Huginn status",
            user_id="operator-1",
            session_id="conversation-1",
        )
    finally:
        await client.stop()
        await asyncio.gather(server_task, return_exceptions=True)

    assert result is not None
    assert result["primary_agent"] == "Bragi"
    assert result["handoff_reason"] == "agent_response_invalid"
