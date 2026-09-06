"""Measured mini routing must agree with dispatch without weakening independent review."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.llm import t1_probe
from fdai.delivery.azure.llm.adaptive_answer import AzureOpenAIAdaptiveModelConfig
from fdai.delivery.azure.llm.t1_latency import T1_ROUTING_STATE_KEY, T1MiniRouting
from fdai.delivery.azure.llm.t1_probe import T1MiniProbe
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.delivery.azure.llm.test_adaptive_answer import (
    PROPOSAL,
    SCHEMA,
    _envelope,
    _Identity,
    _target,
)


def _routing(client, **kwargs):
    primary = _target("narrator-primary", "gpt-5.4-mini")
    reviewer = _target("narrator-reviewer", "gpt-5-mini")
    escalation = _target("reasoner-primary", "gpt-5.6-sol")
    return T1MiniRouting(
        candidates=(primary, reviewer, escalation),
        config=AzureOpenAIAdaptiveModelConfig(
            primary=primary, reviewer=reviewer, escalation=escalation
        ),
        identity=_Identity(),
        http_client=client,
        enabled=True,
        **kwargs,
    )


async def test_fastest_mini_is_the_dispatched_author_and_pair_is_frozen():
    requests = []

    def respond(request):
        requests.append(request.url.path)
        return httpx.Response(200, json=_envelope())

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        routing = _routing(client)
        assert len(routing.candidates) == 2
        routing.record("narrator-primary", 500)
        routing.record("narrator-reviewer", 100)
        model = routing.model_for_turn()
        assert model is not None
        assert routing.snapshot()["model"] == "narrator-reviewer"
        # A periodic measurement arriving mid-turn must not replace its reviewer.
        routing.record("narrator-primary", 1)
        routing.record("narrator-primary", 1)
        assert routing.snapshot()["model"] == "narrator-primary"
        for stage in ("plan", "review", "verify", "refine"):
            result = await model.complete(
                stage=stage,
                system_prompt="Bounded server instructions.",
                payload={"text": "Example"},
                schema=SCHEMA,
                escalated=stage == "refine",
            )
            assert result.proposal == PROPOSAL
        assert "/narrator-reviewer/" in requests[0]
        assert "/narrator-primary/" in requests[1]
        assert "/narrator-primary/" in requests[2]
        assert "/reasoner-primary/" in requests[3]


async def test_freshness_failures_and_sample_bounds_are_truthful():
    current = [datetime(2026, 1, 1, tzinfo=UTC)]
    async with httpx.AsyncClient() as client:
        routing = _routing(client, now=lambda: current[0])
        assert routing.snapshot()["router"]["reason"] == "unmeasured"
        for _ in range(10):
            routing.record("narrator-primary", 100)
            routing.record("narrator-reviewer", 10)
        assert routing.snapshot()["router"]["candidates"][0]["samples"] == 8
        current[0] += timedelta(seconds=601)
        snapshot = routing.snapshot()
        assert snapshot["model"] == "narrator-primary"
        assert snapshot["router"]["reason"] == "stale"
        assert all(c["p50_ms"] is None for c in snapshot["router"]["candidates"])
        routing.record("narrator-primary", None)
        assert routing.model_for_turn() is None
        assert routing.snapshot()["router"]["reason"] == "unavailable"
        routing.record("narrator-primary", 20)
        assert routing.model_for_turn() is not None


async def test_aliases_cannot_become_an_independent_reviewer():
    async with httpx.AsyncClient() as client:
        routing = _routing(client)
        routing.candidates = (
            routing.candidates[0],
            replace(routing.candidates[1], family=routing.candidates[0].family),
        )
        assert routing.model_for_turn() is None


@pytest.mark.parametrize("status", [429, 503])
async def test_rate_limit_or_unavailable_stops_cycle_without_retry(status):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        routing = _routing(client)
        store = InMemoryStateStore()
        probe = T1MiniProbe(
            routing=routing, identity=_Identity(), http_client=client, state_store=store
        )
        await probe.refresh()
        assert len(calls) == 1
        snapshot = await store.read_state(T1_ROUTING_STATE_KEY)
        assert snapshot["router"]["candidates"][0]["status"] == "failed"
        assert snapshot["router"]["candidates"][1]["status"] == "unmeasured"


async def test_probe_is_bounded_synthetic_and_excludes_t2():
    calls = []
    times = iter((0, 0.3, 1, 1.1))

    def respond(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["max_completion_tokens"] == 256
        assert body["reasoning_effort"] == "low"
        assert body["messages"][1]["content"] == "OK"
        assert "tools" not in body
        return httpx.Response(200, json=_envelope("OK"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        routing = _routing(client)
        store = InMemoryStateStore()
        probe = T1MiniProbe(
            routing=routing,
            identity=_Identity(),
            http_client=client,
            state_store=store,
            clock=lambda: next(times),
        )
        await probe.refresh()
        assert len(calls) == 2
        assert all("reasoner" not in request.url.path for request in calls)
        snapshot = await store.read_state(T1_ROUTING_STATE_KEY)
        assert snapshot["model"] == routing.selected_config().primary.target.deployment
        assert snapshot["model"] == "narrator-reviewer"
        assert "https://" not in json.dumps(snapshot)
        assert "test-token" not in json.dumps(snapshot)


async def test_overlap_and_cancellation_do_not_leave_probe_running():
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    calls = []

    async def respond(request):
        calls.append(request)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        probe = T1MiniProbe(
            routing=_routing(client),
            identity=_Identity(),
            http_client=client,
            state_store=InMemoryStateStore(),
        )
        task = asyncio.create_task(probe.run(asyncio.Event()))
        await asyncio.wait_for(entered.wait(), 1)
        await probe.refresh()
        assert len(calls) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()


async def test_timeout_stops_cycle_without_trying_another_model():
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic deadline", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        probe = T1MiniProbe(
            routing=_routing(client),
            identity=_Identity(),
            http_client=client,
            state_store=InMemoryStateStore(),
        )
        await probe.refresh()
        assert len(calls) == 1
        assert probe.routing.snapshot()["router"]["reason"] == "unavailable"


async def test_supervised_loop_runs_next_interval_and_stops(monkeypatch):
    calls = []
    waits = []
    stop = asyncio.Event()

    async def interval(awaitable, *, timeout):
        waits.append(timeout)
        if len(waits) == 2:
            stop.set()
            return await awaitable
        awaitable.close()
        raise TimeoutError

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=_envelope("OK"))

    monkeypatch.setattr(asyncio, "wait_for", interval)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        probe = T1MiniProbe(
            routing=_routing(client),
            identity=_Identity(),
            http_client=client,
            state_store=InMemoryStateStore(),
        )
        await probe.run(stop)
        assert waits == [300, 300]
        assert len(calls) == 4


async def test_disabled_probe_publishes_configuration_without_provider_calls():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("unexpected live probe"))
    ) as client:
        routing = _routing(client)
        routing.enabled = False
        store = InMemoryStateStore()
        probe = T1MiniProbe(
            routing=routing, identity=_Identity(), http_client=client, state_store=store
        )
        await probe.refresh()
        snapshot = await store.read_state(T1_ROUTING_STATE_KEY)
        assert snapshot["model"] == "narrator-primary"
        assert snapshot["router"]["reason"] == "disabled"


async def test_projection_deadline_cancels_blocked_store_before_any_live_probe(monkeypatch):
    cancelled = asyncio.Event()

    class Store(InMemoryStateStore):
        async def write_state(self, key, value):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    monkeypatch.setattr(t1_probe, "_PROJECTION_TIMEOUT_SECONDS", 0.01)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("unexpected probe"))
    ) as client:
        probe = T1MiniProbe(
            routing=_routing(client),
            identity=_Identity(),
            http_client=client,
            state_store=Store(),
        )
        with pytest.raises(TimeoutError):
            await probe.run(asyncio.Event())
        assert cancelled.is_set()
