from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Protocol, cast

import yaml
from fdai.agents import EventBusBridge, InMemoryBus, load_pantheon
from fdai.agents.norns import Norns
from fdai.core.case_history import OperationalCaseInput, OperationalOutcomeClass
from fdai.core.case_history.testing import InMemoryCaseHistoryMetadataStore
from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.shared.providers import EventBus, EventEnvelope, StateStore
from fdai_service_contracts.semantic_turn import multiplexed_consumer_group

from tests.agents.test_operating_pattern_learning_e2e import (
    _case_history_clock,
    _learning_chain,
    _operational_input,
    _operational_raw,
)

_CONTEXT_TOPIC = "object.context-index"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_REDPANDA_IMAGE = (
    "redpandadata/redpanda:v26.2.2"
    "@sha256:468bd13a9f2bd24794cb7fddc867c767fb1008b9a07b297b89fde48c564d7d96"
)


class _EventBusHarness(Protocol):
    bus: EventBus
    prefix: str
    topics: set[str]
    groups: set[str]

    def topic(self, suffix: str) -> str: ...

    def group(self, suffix: str) -> str: ...

    async def collect(
        self,
        topic: str,
        group: str,
        *,
        expected_count: int,
    ) -> tuple[EventEnvelope, ...]: ...


def _unique_input(
    prefix: str,
    marker: str,
    outcome_class: OperationalOutcomeClass,
) -> OperationalCaseInput:
    digest = hashlib.sha256(f"{prefix}:{marker}".encode()).hexdigest()
    return replace(
        _operational_input(marker, outcome_class),
        case_identity_digest=digest,
        correlation_digest=digest,
    )


async def _wait_for_dead_letter(bridge: EventBusBridge) -> None:
    async def wait() -> None:
        while bridge.metrics.dead_lettered < 1:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout=10)


def test_local_broker_runtime_is_digest_pinned() -> None:
    compose = yaml.safe_load(
        (_REPOSITORY_ROOT / "infra/local/docker-compose.yml").read_text(encoding="utf-8")
    )

    assert compose["services"]["redpanda"]["image"] == _REDPANDA_IMAGE


async def test_pinned_broker_restart_and_redrive_preserve_throttled_candidate(
    event_bus_harness: _EventBusHarness,
    state_store: StateStore,
) -> None:
    source_bus, huginn, muninn, _source_norns, _mimir, _source_store = _learning_chain()
    for marker, outcome_class in (
        ("a", OperationalOutcomeClass.SUCCESS),
        ("b", OperationalOutcomeClass.SUCCESS),
        ("c", OperationalOutcomeClass.ROLLBACK),
    ):
        case_input = _unique_input(event_bus_harness.prefix, marker, outcome_class)
        await huginn.ingest(_operational_raw(marker, case_input))
    payload = dict(source_bus.messages_on(_CONTEXT_TOPIC)[-1].payload)
    materializer = muninn._case_history
    assert materializer is not None

    output_bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    throttled = Norns(
        clock=_case_history_clock,
        case_history_materializer=materializer,
        operational_state_store=state_store,
    )
    throttled.bind_bus(output_bus)
    throttled.bind_candidate_publication_gate(lambda: False)

    physical_topic = event_bus_harness.topic("pantheon")
    provider = MultiplexedEventBus(
        bus=event_bus_harness.bus,
        logical_topics=frozenset({_CONTEXT_TOPIC}),
        physical_topic=physical_topic,
    )
    consumer_prefix = f"{event_bus_harness.prefix}.case-history"
    bridge = EventBusBridge(
        provider=provider,
        registry=load_pantheon(),
        consumer_group_prefix=consumer_prefix,
    )
    bridge.subscribe(_CONTEXT_TOPIC, "Norns", throttled.on_typed_message)
    event_bus_harness.groups.add(
        multiplexed_consumer_group(f"{consumer_prefix}.Norns", _CONTEXT_TOPIC)
    )

    await bridge.publish("Muninn", _CONTEXT_TOPIC, payload)
    run_task = asyncio.create_task(bridge.run())
    await _wait_for_dead_letter(bridge)
    dlq = await event_bus_harness.collect(
        f"{physical_topic}.dlq",
        event_bus_harness.group("dlq-audit"),
        expected_count=1,
    )
    await bridge.stop()
    run_task.cancel()
    await asyncio.gather(run_task, return_exceptions=True)

    assert len(dlq) == 1
    assert dlq[0].payload["original_topic"] == physical_topic
    pending, total = await state_store.read_state_page(
        "pantheon/norns/operational-candidates/",
        limit=2,
        field="status",
        value="pending",
    )
    assert len(pending) == total == 1

    restarted_bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    restarted = Norns(
        clock=_case_history_clock,
        case_history_materializer=materializer,
        operational_state_store=state_store,
    )
    restarted.bind_bus(restarted_bus)
    assert await restarted.recover_operational_candidates() == 1
    assert await restarted.flush_candidates() == 1
    assert len(restarted_bus.messages_on("object.pattern")) == 1
    assert len(restarted_bus.messages_on("object.rule-candidate")) == 1

    first_redrive_group = f"{consumer_prefix}.redrive.{_CONTEXT_TOPIC}"
    event_bus_harness.groups.add(
        multiplexed_consumer_group(first_redrive_group, f"{_CONTEXT_TOPIC}.dlq")
    )
    assert await bridge.redrive(
        _CONTEXT_TOPIC,
        restarted.on_typed_message,
        max_records=1,
    ) == {"redriven": 1, "failed": 0}
    assert len(restarted_bus.messages_on("object.pattern")) == 1
    assert len(restarted_bus.messages_on("object.rule-candidate")) == 1

    source = cast(dict[str, object], cast(list[object], payload["cases"])[0])
    metadata = cast(InMemoryCaseHistoryMetadataStore, materializer._metadata)
    record = await metadata.latest(
        str(source["case_id"]),
        access_scope_digest=str(payload["access_scope_digest"]),
    )
    assert record is not None and record.storage_ref is not None
    await metadata.mark_deletion_started(
        record.case_id,
        access_scope_digest=record.access_scope_digest,
        revision=record.revision,
        storage_refs=(record.storage_ref,),
        started_at=record.deletion_due_at,
    )

    deleted_bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    after_deletion = Norns(
        clock=_case_history_clock,
        case_history_materializer=materializer,
        operational_state_store=state_store,
    )
    after_deletion.bind_bus(deleted_bus)
    after_deletion_group = f"{consumer_prefix}.redrive-after-deletion"
    event_bus_harness.groups.add(
        multiplexed_consumer_group(after_deletion_group, f"{_CONTEXT_TOPIC}.dlq")
    )
    assert await bridge.redrive(
        _CONTEXT_TOPIC,
        after_deletion.on_typed_message,
        group_id=after_deletion_group,
        max_records=1,
    ) == {"redriven": 1, "failed": 0}
    assert not deleted_bus.messages_on("object.pattern")
    assert not deleted_bus.messages_on("object.rule-candidate")
    assert after_deletion.behavior_snapshot()["operational_case_cohort_source_unavailable"] == 1

    terminal = (await state_store.read_states("pantheon/norns/operational-candidates/", limit=2))[0]
    assert terminal["status"] == "published"
    assert "candidate" not in terminal
    assert "pattern" not in terminal
