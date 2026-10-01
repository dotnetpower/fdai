"""Forseti retrospective what-if replay remains judge-only and inert."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fdai.agents._framework.runtime import PantheonRuntime
from fdai.shared.providers.local.event_bus import LocalEventBus

_RAW_TOPIC = "fdai.events.what-if-test"


async def _run_until(
    runtime: PantheonRuntime,
    predicate: Callable[[], bool],
    *,
    steps: int = 2000,
) -> None:
    run_task = asyncio.create_task(runtime.run())
    try:
        for _ in range(steps):
            await asyncio.sleep(0)
            if predicate():
                return
        raise AssertionError("runtime condition was not observed")
    finally:
        await runtime.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup path
            pass


def _runtime() -> tuple[PantheonRuntime, LocalEventBus]:
    provider = LocalEventBus()
    return PantheonRuntime.build(provider=provider, raw_event_topic=_RAW_TOPIC), provider


def _payloads(provider: LocalEventBus, topic: str) -> list[dict[str, Any]]:
    return [dict(payload) for _key, payload in provider._records.get(topic, [])]


def _consumer_committed(
    runtime: PantheonRuntime,
    provider: LocalEventBus,
    topic: str,
    agent: str,
) -> bool:
    group_id = f"{runtime.bridge.consumer_group_prefix}.{agent}"
    end_offset = provider._base_offsets.get(topic, 0) + len(provider._records.get(topic, ()))
    return end_offset > 0 and provider._offsets.get((topic, group_id), 0) >= end_offset


def test_retrospective_what_if_publishes_inert_disagreement_on_async_bus() -> None:
    runtime, provider = _runtime()
    forseti = runtime.agents["Forseti"]

    async def _drive() -> None:
        await forseti.judge(
            {
                "event_type": "unknown_signal",
                "resource_id": "resource-what-if",
                "correlation_id": "corr-original",
            }
        )
        await runtime.bridge.publish(
            "Huginn",
            "object.event",
            {
                "kind": "retrospective_what_if_request",
                "event_type": "retrospective.what_if.request",
                "correlation_id": "corr-what-if",
                "idempotency_key": "what-if-request-1",
                "resource_id": "resource-what-if",
                "judgment_table": {
                    "source": "focused-test-overlay",
                    "rule_match": {"unknown_signal": "remediate.disable-public-access"},
                    "risk_verdict": {"remediate.disable-public-access": "auto"},
                },
                "sample_limit": 4,
            },
        )
        await _run_until(
            runtime,
            lambda: (
                any(
                    payload.get("kind") == "retrospective_what_if"
                    for payload in _payloads(provider, "object.verdict")
                )
                and _consumer_committed(runtime, provider, "object.verdict", "Thor")
            ),
        )

    asyncio.run(_drive())

    what_if = [
        payload
        for payload in _payloads(provider, "object.verdict")
        if payload.get("kind") == "retrospective_what_if"
    ][0]
    assert what_if["what_if_contract"]["contract_version"] == "retrospective-what-if.v1"
    assert what_if["what_if_contract"]["selection"] == "recent_retained_judgment_inputs"
    assert what_if["disagreement_count"] == 1
    assert what_if["outcomes"][0]["disagrees"] is True
    assert "risk_verdict_changed" in what_if["outcomes"][0]["reason_codes"]
    assert _payloads(provider, "object.action-run") == []
    assert runtime.agents["Thor"].behavior_snapshot()["non_action_verdict_ignored"] >= 1


def test_retrospective_what_if_is_idempotent_per_input_digest() -> None:
    runtime, provider = _runtime()
    forseti = runtime.agents["Forseti"]

    async def _drive() -> None:
        await forseti.judge(
            {
                "event_type": "unknown_signal",
                "resource_id": "resource-what-if",
                "correlation_id": "corr-original",
            }
        )
        request = {
            "kind": "retrospective_what_if_request",
            "event_type": "retrospective.what_if.request",
            "correlation_id": "corr-what-if",
            "idempotency_key": "what-if-request-1",
            "resource_id": "resource-what-if",
            "judgment_table": {
                "source": "focused-test-overlay",
                "rule_match": {"unknown_signal": "remediate.disable-public-access"},
                "risk_verdict": {"remediate.disable-public-access": "auto"},
            },
            "sample_limit": 4,
        }
        await runtime.bridge.publish("Huginn", "object.event", request)
        await runtime.bridge.publish("Huginn", "object.event", {**request, "idempotency_key": "2"})
        await _run_until(
            runtime,
            lambda: _consumer_committed(runtime, provider, "object.event", "Forseti"),
        )

    asyncio.run(_drive())

    what_if = [
        payload
        for payload in _payloads(provider, "object.verdict")
        if payload.get("kind") == "retrospective_what_if"
    ]
    assert len(what_if) == 1
    assert runtime.agents["Forseti"].behavior_snapshot()["retrospective_what_if:duplicate"] == 1


def test_retrospective_what_if_answers_distinct_operator_correlations() -> None:
    runtime, provider = _runtime()
    forseti = runtime.agents["Forseti"]

    async def _drive() -> None:
        await forseti.judge(
            {
                "event_type": "unknown_signal",
                "resource_id": "resource-what-if",
                "correlation_id": "corr-original",
            }
        )
        request = {
            "kind": "retrospective_what_if_request",
            "event_type": "retrospective.what_if.request",
            "idempotency_key": "what-if-request",
            "resource_id": "resource-what-if",
            "judgment_table": {
                "source": "focused-test-overlay",
                "rule_match": {"unknown_signal": "remediate.disable-public-access"},
                "risk_verdict": {"remediate.disable-public-access": "auto"},
            },
            "sample_limit": 4,
        }
        await runtime.bridge.publish(
            "Huginn",
            "object.event",
            {**request, "correlation_id": "corr-what-if-a"},
        )
        await runtime.bridge.publish(
            "Huginn",
            "object.event",
            {**request, "correlation_id": "corr-what-if-b", "idempotency_key": "what-if-b"},
        )
        await _run_until(
            runtime,
            lambda: (
                sum(
                    1
                    for payload in _payloads(provider, "object.verdict")
                    if payload.get("kind") == "retrospective_what_if"
                )
                == 2
                and _consumer_committed(runtime, provider, "object.verdict", "Thor")
            ),
        )

    asyncio.run(_drive())

    what_if = [
        payload
        for payload in _payloads(provider, "object.verdict")
        if payload.get("kind") == "retrospective_what_if"
    ]
    assert {payload["correlation_id"] for payload in what_if} == {
        "corr-what-if-a",
        "corr-what-if-b",
    }
    assert _payloads(provider, "object.action-run") == []
