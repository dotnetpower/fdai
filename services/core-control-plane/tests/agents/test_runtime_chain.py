"""Runtime observer regression over a live (polling) event bus.

The shipped :class:`InMemoryEventBus` snapshots its queue per
``subscribe`` call, so a single ``run`` pass only drains one hop - fine
for unit checks but unable to prove the full fan-out chain. This module
adds a minimal *live* polling bus (records published mid-run become
visible to already-subscribed consumers) and drives the catalog-backed
shadow rejection path through it:

    raw event -> Huginn -> object.event -> Forseti -> object.verdict
              -> Thor (shadow) -> object.action-run -> Saga (audit)

The successful authority-chain coverage lives in
``test_runtime_end_to_end_delivery.py``; this file pins the rejected edge
identity so aggregate bridge counters never hide the source verdict.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.saga import Saga
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.event_bus import EventBus, EventEnvelope, PublishReceipt

_RAW_TOPIC = "fdai.events"
_REPO_ROOT = Path(__file__).resolve().parents[4]


@lru_cache(maxsize=1)
def _action_types() -> tuple[OntologyActionType, ...]:
    return load_action_type_catalog(
        _REPO_ROOT / "rule-catalog" / "action-types",
        schema_registry=PackageResourceSchemaRegistry(),
    )


class LiveInMemoryEventBus(EventBus):
    """In-memory bus whose subscribers keep polling for new records.

    Unlike the shipped snapshot fake, a record published after a
    consumer has subscribed still reaches it, so a chain of publishes
    propagates within one ``run`` - the behaviour a real broker gives.
    """

    def __init__(self) -> None:
        self._records: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        self._offsets: dict[tuple[str, str], int] = {}
        self._lock = Lock()

    async def publish(self, topic: str, key: str, payload: Mapping[str, Any]) -> PublishReceipt:
        with self._lock:
            queue = self._records.setdefault(topic, [])
            offset = len(queue)
            queue.append((key, deepcopy(dict(payload))))
            return PublishReceipt(topic=topic, partition=0, offset=offset)

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        return self._subscribe(topic, group_id)

    async def _subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        while True:
            record: tuple[str, dict[str, Any]] | None = None
            offset = 0
            with self._lock:
                offset = self._offsets.get((topic, group_id), 0)
                queue = self._records.get(topic, [])
                if offset < len(queue):
                    record = queue[offset]
            if record is None:
                await asyncio.sleep(0)  # yield; poll again
                continue
            yield EventEnvelope(
                topic=topic, key=record[0], payload=deepcopy(record[1]), offset=offset
            )
            with self._lock:
                self._offsets[(topic, group_id)] = offset + 1

    async def dead_letter(
        self, topic: str, key: str, payload: Mapping[str, Any], reason: str
    ) -> None:
        with self._lock:
            self._records.setdefault(f"{topic}.dlq", []).append(
                (
                    key,
                    {
                        "original_topic": topic,
                        "reason": reason,
                        "payload": deepcopy(dict(payload)),
                    },
                )
            )


def test_rejected_catalog_verdict_is_correlated_in_runtime_health() -> None:
    provider = LiveInMemoryEventBus()
    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic=_RAW_TOPIC,
        action_types=_action_types(),
    )

    async def _drive() -> None:
        run_task = asyncio.create_task(runtime.run())
        await provider.publish(
            _RAW_TOPIC,
            "sa-1",
            {
                "id": "e1",
                "correlation_id": "corr-chain",
                "resource_id": "sa-1",
                "event_type": "public_network_enabled",
            },
        )
        # Let the chain propagate hop by hop; break as soon as an
        # ActionRun terminal state has been observed.
        for _ in range(2000):
            await asyncio.sleep(0)
            if any(k.startswith("action_run:") for k in runtime.shadow_decisions):
                break
        await runtime.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

    asyncio.run(_drive())

    assert runtime.bridge.metrics.schema_violations >= 1
    assert runtime.shadow_decisions["verdict:auto"] == 0
    assert not any(k.startswith("shadow_action_run:") for k in runtime.shadow_decisions)
    rejected = runtime.health()["recent_rejected_edges"]
    assert rejected
    assert rejected[-1]["correlation_id"] == "corr-chain"
    assert rejected[-1]["topic"] == "object.verdict"
    assert "schema violation" in rejected[-1]["reason"]
    saga = runtime.agents["Saga"]
    assert isinstance(saga, Saga)
    assert saga.replay_for_correlation("corr-chain") == []


def test_bridge_run_rejects_reentry_while_running() -> None:
    from fdai.agents._framework.bus_bridge import EventBusBridge
    from fdai.agents._framework.registry import load_pantheon

    provider = LiveInMemoryEventBus()
    bridge = EventBusBridge(provider=provider, registry=load_pantheon())

    async def handler(_t: str, _p: dict) -> None:
        return None

    bridge.subscribe("object.event", "Heimdall", handler)

    async def _drive() -> bool:
        run_task = asyncio.create_task(bridge.run())
        for _ in range(5):
            await asyncio.sleep(0)  # let _tasks populate (live bus hangs)
        raised = False
        try:
            await bridge.run()
        except RuntimeError:
            raised = True
        await bridge.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass
        return raised

    assert asyncio.run(_drive()) is True
