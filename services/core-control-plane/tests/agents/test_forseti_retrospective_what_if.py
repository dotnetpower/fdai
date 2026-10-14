"""Forseti retrospective what-if replay remains judge-only and inert."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.agents._framework.forseti_judgment import JudgmentTable
from fdai.agents._framework.forseti_quality_retention import (
    MAX_QUALITY_INPUTS,
    QUALITY_WINDOW_KEY,
    restore_quality_samples,
    retain_quality_sample,
)
from fdai.agents._framework.forseti_what_if_publication import PUBLICATION_WINDOW_KEY
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.forseti import Forseti
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_RAW_TOPIC = "fdai.events.what-if-test"


class _FailOnceWhatIfBus:
    def __init__(self) -> None:
        self.failures_remaining = 1
        self.published: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.verdict" and payload.get("kind") == "retrospective_what_if":
            if self.failures_remaining:
                self.failures_remaining -= 1
                raise RuntimeError("transient verdict publish failure")
        self.published.append((principal, topic, payload))


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


async def test_retrospective_what_if_publish_failure_stays_retryable_until_success() -> None:
    bus = _FailOnceWhatIfBus()
    forseti = Forseti(bus=bus)
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
        "producer_principal": "Huginn",
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

    with pytest.raises(RuntimeError, match="transient verdict publish failure"):
        await forseti.on_typed_message("object.event", request)
    assert forseti.behavior_snapshot()["retrospective_what_if:publication_failed"] == 1

    await forseti.on_typed_message("object.event", request)
    await forseti.on_typed_message("object.event", {**request, "idempotency_key": "retry-2"})

    what_if = [
        payload
        for _principal, topic, payload in bus.published
        if topic == "object.verdict" and payload.get("kind") == "retrospective_what_if"
    ]
    assert len(what_if) == 1
    behavior = forseti.behavior_snapshot()
    assert behavior["retrospective_what_if:published"] == 1
    assert behavior["retrospective_what_if:duplicate"] == 1


async def test_what_if_preserves_the_original_abstention_and_table_after_an_update() -> None:
    bus = _FailOnceWhatIfBus()
    bus.failures_remaining = 0
    forseti = Forseti(bus=bus)
    original = await forseti.judge(
        {
            "event_type": "unknown_signal",
            "resource_id": "resource-what-if",
            "correlation_id": "corr-original",
        }
    )
    assert original is not None
    assert original["action_type"] == ""
    forseti._judgment_table = JudgmentTable(
        rule_match={"unknown_signal": "remediate.disable-public-access"},
        risk_verdict={"remediate.disable-public-access": "auto"},
        source="updated-after-judgment",
    )
    await forseti.on_typed_message(
        "object.event",
        {
            "kind": "retrospective_what_if_request",
            "producer_principal": "Huginn",
            "event_type": "retrospective.what_if.request",
            "correlation_id": "corr-what-if",
            "idempotency_key": "what-if-update",
            "resource_id": "resource-what-if",
            "judgment_table": {
                "source": "proposed-overlay",
                "rule_match": {"unknown_signal": "remediate.disable-public-access"},
                "risk_verdict": {"remediate.disable-public-access": "auto"},
            },
            "sample_limit": 4,
        },
    )
    payload = next(
        payload
        for _, topic, payload in bus.published
        if topic == "object.verdict" and payload.get("kind") == "retrospective_what_if"
    )
    assert payload["outcomes"][0]["original"] == {
        "action_type": original["action_type"],
        "risk_verdict": original["risk_verdict"],
        "judgment_table_digest": original["judgment_table_digest"],
    }
    assert payload["action_type"] == ""
    assert payload["resolved_autonomy_ceiling"] == "shadow_only"


async def test_what_if_restores_the_bounded_comparison_inputs_after_restart() -> None:
    store = InMemoryStateStore()
    bus = _FailOnceWhatIfBus()
    bus.failures_remaining = 0
    initial = Forseti(bus=bus, state_store=store)
    original = await initial.judge(
        {
            "event_type": "unknown_signal",
            "resource_id": "resource-retained",
            "correlation_id": "corr-retained",
        }
    )
    assert original is not None
    restarted = Forseti(bus=bus, state_store=store)
    await restarted.rehydrate()
    await restarted.on_typed_message(
        "object.event",
        {
            "kind": "retrospective_what_if_request",
            "producer_principal": "Huginn",
            "event_type": "retrospective.what_if.request",
            "correlation_id": "corr-restart",
            "idempotency_key": "restart-inputs",
            "resource_id": "resource-retained",
            "judgment_table": {
                "source": "restart-overlay",
                "rule_match": {"unknown_signal": "remediate.disable-public-access"},
                "risk_verdict": {"remediate.disable-public-access": "auto"},
            },
        },
    )
    payloads = [
        payload
        for _, topic, payload in bus.published
        if topic == "object.verdict" and payload.get("kind") == "retrospective_what_if"
    ]
    assert len(payloads) == 1
    assert payloads[0]["outcomes"][0]["original"] == {
        "action_type": original["action_type"],
        "risk_verdict": original["risk_verdict"],
        "judgment_table_digest": original["judgment_table_digest"],
    }


async def test_what_if_deduplicates_a_successful_publication_after_restart() -> None:
    store = InMemoryStateStore()
    bus = _FailOnceWhatIfBus()
    bus.failures_remaining = 0
    initial = Forseti(bus=bus, state_store=store)
    await initial.judge(
        {
            "event_type": "unknown_signal",
            "resource_id": "resource-retained",
            "correlation_id": "corr-retained",
        }
    )
    request = {
        "kind": "retrospective_what_if_request",
        "producer_principal": "Huginn",
        "event_type": "retrospective.what_if.request",
        "correlation_id": "corr-same-comparison",
        "idempotency_key": "comparison-retry",
        "judgment_table": {
            "source": "retry-overlay",
            "rule_match": {},
            "risk_verdict": {},
        },
    }
    await initial.on_typed_message("object.event", request)
    restarted = Forseti(bus=bus, state_store=store)
    await restarted.rehydrate()
    await restarted.on_typed_message("object.event", request)
    payloads = [
        payload
        for _, topic, payload in bus.published
        if topic == "object.verdict" and payload.get("kind") == "retrospective_what_if"
    ]
    assert len(payloads) == 1


async def test_what_if_failed_publication_recovers_its_frozen_payload_without_input_window() -> (
    None
):
    store = InMemoryStateStore()
    bus = _FailOnceWhatIfBus()
    initial = Forseti(bus=bus, state_store=store)
    await initial.judge(
        {
            "event_type": "unknown_signal",
            "resource_id": "resource-frozen",
            "correlation_id": "corr-frozen",
        }
    )
    request = {
        "kind": "retrospective_what_if_request",
        "producer_principal": "Huginn",
        "event_type": "retrospective.what_if.request",
        "correlation_id": "corr-frozen-retry",
        "idempotency_key": "frozen-retry",
        "judgment_table": {"rule_match": {}, "risk_verdict": {}, "source": "frozen"},
    }
    with pytest.raises(RuntimeError, match="transient verdict publish failure"):
        await initial.on_typed_message("object.event", request)
    journal = await store.read_state(PUBLICATION_WINDOW_KEY)
    assert journal is not None
    original_payload = journal["records"][0]["payload"]
    await store.delete_state(QUALITY_WINDOW_KEY)
    restarted = Forseti(bus=bus, state_store=store)
    await restarted.on_typed_message("object.event", request)
    published = [
        payload for _, _, payload in bus.published if payload.get("kind") == "retrospective_what_if"
    ]
    assert published == [original_payload]


async def test_what_if_two_replicas_publish_one_frozen_comparison() -> None:
    store = InMemoryStateStore()
    bus = _FailOnceWhatIfBus()
    bus.failures_remaining = 0
    initial = Forseti(bus=bus, state_store=store)
    await initial.judge(
        {
            "event_type": "unknown_signal",
            "resource_id": "resource-race",
            "correlation_id": "corr-race",
        }
    )
    request = {
        "kind": "retrospective_what_if_request",
        "producer_principal": "Huginn",
        "event_type": "retrospective.what_if.request",
        "correlation_id": "corr-race-request",
        "idempotency_key": "race-request",
        "judgment_table": {"rule_match": {}, "risk_verdict": {}, "source": "race"},
    }
    replicas = [Forseti(bus=bus, state_store=store), Forseti(bus=bus, state_store=store)]
    await asyncio.gather(
        *(replica.on_typed_message("object.event", request) for replica in replicas)
    )
    assert (
        len(
            [
                payload
                for _, _, payload in bus.published
                if payload.get("kind") == "retrospective_what_if"
            ]
        )
        == 1
    )


async def test_what_if_acceptance_checkpoint_failure_replays_identical_payload() -> None:
    class FailingCheckpointStore(InMemoryStateStore):
        fail_checkpoint = True

        async def compare_and_set_state(
            self, key: str, value: dict[str, Any], *, expected_revision: int
        ) -> bool:
            if (
                key == PUBLICATION_WINDOW_KEY
                and self.fail_checkpoint
                and any(row["status"] == "published" for row in value["records"])
            ):
                return False
            return await super().compare_and_set_state(
                key, value, expected_revision=expected_revision
            )

    store = FailingCheckpointStore()
    bus = _FailOnceWhatIfBus()
    bus.failures_remaining = 0
    initial = Forseti(bus=bus, state_store=store)
    await initial.judge(
        {
            "event_type": "unknown_signal",
            "resource_id": "resource-crash",
            "correlation_id": "corr-crash",
        }
    )
    request = {
        "kind": "retrospective_what_if_request",
        "producer_principal": "Huginn",
        "event_type": "retrospective.what_if.request",
        "correlation_id": "corr-crash-request",
        "idempotency_key": "crash-request",
        "judgment_table": {"rule_match": {}, "risk_verdict": {}, "source": "crash"},
    }
    with pytest.raises(RuntimeError, match="CAS contention"):
        await initial.on_typed_message("object.event", request)
    store.fail_checkpoint = False
    await Forseti(bus=bus, state_store=store).on_typed_message("object.event", request)
    payloads = [
        payload for _, _, payload in bus.published if payload.get("kind") == "retrospective_what_if"
    ]
    assert len(payloads) == 2
    assert payloads[0] == payloads[1]


async def test_what_if_completed_request_does_not_reselect_new_inputs() -> None:
    store = InMemoryStateStore()
    bus = _FailOnceWhatIfBus()
    bus.failures_remaining = 0
    forseti = Forseti(bus=bus, state_store=store)
    await forseti.judge(
        {
            "event_type": "unknown_signal",
            "resource_id": "resource-first",
            "correlation_id": "corr-first",
        }
    )
    request = {
        "kind": "retrospective_what_if_request",
        "producer_principal": "Huginn",
        "event_type": "retrospective.what_if.request",
        "correlation_id": "corr-fixed-request",
        "idempotency_key": "fixed-request",
        "judgment_table": {"rule_match": {}, "risk_verdict": {}, "source": "fixed"},
    }
    await forseti.on_typed_message("object.event", request)
    await forseti.judge(
        {
            "event_type": "another_signal",
            "resource_id": "resource-second",
            "correlation_id": "corr-second",
        }
    )
    await Forseti(bus=bus, state_store=store).on_typed_message("object.event", request)
    await forseti.on_typed_message(
        "object.event", {**request, "correlation_id": "corr-new-request"}
    )
    payloads = [
        payload for _, _, payload in bus.published if payload.get("kind") == "retrospective_what_if"
    ]
    assert [len(payload["outcomes"]) for payload in payloads] == [1, 2]


@pytest.mark.parametrize("corruption", ["payload", "authority", "revision", "claim", "request"])
async def test_what_if_publication_corruption_holds_without_republishing(corruption: str) -> None:
    store = InMemoryStateStore()
    bus = _FailOnceWhatIfBus()
    bus.failures_remaining = 0
    forseti = Forseti(bus=bus, state_store=store)
    await forseti.judge(
        {
            "event_type": "unknown_signal",
            "resource_id": "resource-corrupt",
            "correlation_id": "corr-corrupt",
        }
    )
    request = {
        "kind": "retrospective_what_if_request",
        "producer_principal": "Huginn",
        "event_type": "retrospective.what_if.request",
        "correlation_id": "corr-corrupt-request",
        "idempotency_key": "corrupt-request",
        "judgment_table": {"rule_match": {}, "risk_verdict": {}, "source": "corrupt"},
    }
    await forseti.on_typed_message("object.event", request)
    raw = await store.read_state(PUBLICATION_WINDOW_KEY)
    assert raw is not None
    if corruption == "payload":
        raw["records"][0]["payload"]["outcomes"][0]["original"]["risk_verdict"] = "auto"
    elif corruption == "authority":
        raw["execution_authority"] = True
    elif corruption == "revision":
        raw["revision"] = True
    elif corruption == "request":
        raw["records"][0]["request_key"] = "different-request"
    else:
        raw["records"][0].update(status="publishing", claim_owner="foreign", claimed_at="invalid")
    await store.write_state(PUBLICATION_WINDOW_KEY, raw)
    restarted = Forseti(bus=bus, state_store=store)
    await restarted.on_typed_message("object.event", request)
    assert (
        len(
            [
                payload
                for _, _, payload in bus.published
                if payload.get("kind") == "retrospective_what_if"
            ]
        )
        == 1
    )
    assert restarted.health()["retrospective_what_if"]["evidence_state"] == "retention_unavailable"


def _retained_sample() -> dict[str, str]:
    return {
        "event_type": "unknown_signal",
        "action_type": "",
        "risk_verdict": "hil",
        "judgment_table_digest": "sha256:" + "a" * 64,
        "tier": "T0",
    }


async def test_quality_window_keeps_512_inputs_and_rejects_identity_substitution() -> None:
    store = InMemoryStateStore()
    host = SimpleNamespace(_forseti_state_store=store)
    for index in range(MAX_QUALITY_INPUTS + 1):
        await retain_quality_sample(host, f"retained-{index}", _retained_sample())
    assert await restore_quality_samples(host) == MAX_QUALITY_INPUTS
    assert host._verdict_quality_samples.get("retained-0") is None
    with pytest.raises(ValueError, match="substituted"):
        await retain_quality_sample(
            host, "retained-1", {**_retained_sample(), "risk_verdict": "auto"}
        )


async def test_quality_window_preserves_two_replica_updates_after_a_cas_race() -> None:
    class RacingStore(InMemoryStateStore):
        raced = False

        async def compare_and_set_state(
            self, key: str, value: dict[str, Any], *, expected_revision: int
        ) -> bool:
            if key == QUALITY_WINDOW_KEY and not self.raced:
                self.raced = True
                await retain_quality_sample(
                    SimpleNamespace(_forseti_state_store=self), "peer", _retained_sample()
                )
                return False
            return await super().compare_and_set_state(
                key, value, expected_revision=expected_revision
            )

    store = RacingStore()
    host = SimpleNamespace(_forseti_state_store=store)
    await retain_quality_sample(host, "initial", _retained_sample())
    await retain_quality_sample(host, "second", _retained_sample())
    assert await restore_quality_samples(host) == 3
    assert {key for key, _sample in host._verdict_quality_samples.items()} == {
        "initial",
        "peer",
        "second",
    }


@pytest.mark.parametrize(
    "corruption", ["revision", "digest", "authority", "extra", "duplicate", "decision"]
)
async def test_quality_window_corruption_holds_comparison_without_memory_fallback(
    corruption: str,
) -> None:
    store = InMemoryStateStore()
    bus = _FailOnceWhatIfBus()
    bus.failures_remaining = 0
    forseti = Forseti(bus=bus, state_store=store)
    await forseti.judge(
        {
            "event_type": "unknown_signal",
            "resource_id": "resource-retained",
            "correlation_id": "corr-retained",
        }
    )
    raw = await store.read_state(QUALITY_WINDOW_KEY)
    assert raw is not None
    if corruption == "revision":
        raw["revision"] = True
    elif corruption == "digest":
        raw["records"][0]["sample"]["judgment_table_digest"] = "sha256:wrong"
    elif corruption == "authority":
        raw["execution_authority"] = True
    elif corruption == "extra":
        raw["records"][0]["sample"]["raw_body"] = "must never be retained"
    elif corruption == "decision":
        raw["records"][0]["sample"]["risk_verdict"] = "auto"
    else:
        raw["records"].append(raw["records"][0])
    await store.write_state(QUALITY_WINDOW_KEY, raw)
    await forseti.on_typed_message(
        "object.event",
        {
            "kind": "retrospective_what_if_request",
            "producer_principal": "Huginn",
            "event_type": "retrospective.what_if.request",
            "correlation_id": "corr-held",
            "idempotency_key": "held-retention",
            "judgment_table": {"rule_match": {}, "risk_verdict": {}, "source": "held-overlay"},
        },
    )
    assert not [
        payload for _, _, payload in bus.published if payload.get("kind") == "retrospective_what_if"
    ]
    assert forseti.health()["retrospective_what_if"]["evidence_state"] == "retention_unavailable"


async def test_quality_store_failure_does_not_replace_the_original_judgment() -> None:
    class FailingQualityStore(InMemoryStateStore):
        async def read_state(self, key: str) -> dict[str, Any] | None:
            if key == QUALITY_WINDOW_KEY:
                raise RuntimeError("quality storage unavailable")
            return await super().read_state(key)

    bus = _FailOnceWhatIfBus()
    bus.failures_remaining = 0
    forseti = Forseti(bus=bus, state_store=FailingQualityStore())
    original = await forseti.judge(
        {
            "event_type": "unknown_signal",
            "resource_id": "resource-retained",
            "correlation_id": "corr-retained",
        }
    )
    assert original is not None and original["risk_verdict"] == "hil"
    assert any(payload == original for _, _, payload in bus.published)
    assert forseti.behavior_snapshot()["retrospective_what_if:retention_failed"] == 1


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
