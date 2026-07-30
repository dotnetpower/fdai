from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from copy import deepcopy
from threading import Lock
from typing import Any

from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.heimdall import Heimdall
from fdai.agents.var import Var
from fdai.shared.providers.event_bus import EventBus, EventEnvelope, PublishReceipt

_RAW_TOPIC = "fdai.events"


class LiveInMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self._records: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        self._offsets: dict[tuple[str, str], int] = {}
        self._lock = Lock()

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        with self._lock:
            queue = self._records.setdefault(topic, [])
            offset = len(queue)
            queue.append((key, deepcopy(dict(payload))))
        return PublishReceipt(topic=topic, partition=0, offset=offset)

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        return self._subscribe(topic, group_id)

    async def _subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        while True:
            with self._lock:
                offset = self._offsets.get((topic, group_id), 0)
                queue = self._records.get(topic, [])
                record = queue[offset] if offset < len(queue) else None
            if record is None:
                await asyncio.sleep(0)
                continue
            yield EventEnvelope(
                topic=topic,
                key=record[0],
                payload=deepcopy(record[1]),
                offset=offset,
            )
            with self._lock:
                self._offsets[(topic, group_id)] = offset + 1

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        del topic, key, payload, reason


def _raw_event(*, recovered: bool = False) -> dict[str, object]:
    return {
        "id": "t2-recovery-1",
        "event_id": "t2-recovery-1",
        "idempotency_key": "t2-recovery-1",
        "correlation_id": "corr-t2-recovery",
        "incident_correlation": "none" if recovered else "correlate",
        "source": "fdai.t2-recovery",
        "resource_id": "control-plane:t2-proposer",
        "resource_type": "llm-endpoint",
        "event_type": (
            "control_plane.t2_proposer_recovered"
            if recovered
            else "control_plane.t2_proposer_attempt"
        ),
        "severity": "info" if recovered else "high",
        "attributes": {
            "route_ref": "secondary",
            "attempt": 2,
            "candidate_count": 2,
            "status": "succeeded" if recovered else "failed",
            "failure_class": None if recovered else "provider_error",
            "retryable": not recovered,
            "terminal": True,
            "recovered": recovered,
        },
    }


async def _drive(
    runtime: PantheonRuntime,
    provider: LiveInMemoryEventBus,
    payload: dict[str, object],
) -> None:
    task = asyncio.create_task(runtime.run())
    await provider.publish(_RAW_TOPIC, str(payload["id"]), payload)
    for _ in range(3000):
        await asyncio.sleep(0)
        if task.done():
            task.result()
        var = runtime.agents["Var"]
        if isinstance(var, Var) and var.behavior_snapshot().get("ticket_pending"):
            break
    await runtime.stop()
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
        pass


def test_terminal_proposer_failure_reaches_real_hil_chain() -> None:
    provider = LiveInMemoryEventBus()
    runtime = PantheonRuntime.build(provider=provider, raw_event_topic=_RAW_TOPIC)

    asyncio.run(_drive(runtime, provider, _raw_event()))

    heimdall = runtime.agents["Heimdall"]
    var = runtime.agents["Var"]
    assert isinstance(heimdall, Heimdall)
    assert isinstance(var, Var)
    assert heimdall.behavior_snapshot().get("t2_proposer:unavailable") == 1
    assert runtime.shadow_decisions["verdict:hil"] >= 1
    assert runtime.shadow_decisions["action_run:hil_pending"] >= 1
    assert var.behavior_snapshot().get("ticket_pending") == 1


def test_recovered_proposer_signal_does_not_create_hil() -> None:
    provider = LiveInMemoryEventBus()
    runtime = PantheonRuntime.build(provider=provider, raw_event_topic=_RAW_TOPIC)

    asyncio.run(_drive(runtime, provider, _raw_event(recovered=True)))

    heimdall = runtime.agents["Heimdall"]
    var = runtime.agents["Var"]
    assert isinstance(heimdall, Heimdall)
    assert isinstance(var, Var)
    assert heimdall.behavior_snapshot().get("t2_proposer:recovered") == 1
    assert runtime.shadow_decisions["verdict:hil"] == 0
    assert var.behavior_snapshot().get("ticket_pending") is None
