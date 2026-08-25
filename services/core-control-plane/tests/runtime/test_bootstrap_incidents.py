from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from fdai.core.incident import IncidentLifecycleNotice
from fdai.runtime.bootstrap_incidents import build_incident_runtime
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallReceipt,
    ToolCallRequest,
)


class _RecordingNotifier:
    def __init__(self) -> None:
        self.replayed: tuple[Mapping[str, Any], ...] | None = None

    async def notify(self, notice: IncidentLifecycleNotice) -> None:
        del notice

    async def replay(self, entries: tuple[Mapping[str, Any], ...]) -> int:
        self.replayed = entries
        return len(entries)


class _RetryingNotifier(_RecordingNotifier):
    def __init__(self, failure: Exception) -> None:
        super().__init__()
        self.failure = failure
        self.calls = 0

    async def replay(self, entries: tuple[Mapping[str, Any], ...]) -> int:
        self.calls += 1
        if self.calls == 1:
            raise self.failure
        return await super().replay(entries)


def _runtime_values(*, enabled: bool = True) -> dict[str, object]:
    return {
        "incident.auto_open.enabled": enabled,
        "incident.auto_open.min_severity": "sev2",
    }


async def test_incident_runtime_rehydrates_without_blocking_on_notification_replay() -> None:
    store = InMemoryStateStore()
    notifier = _RecordingNotifier()

    runtime = await build_incident_runtime(
        state_store=store,
        runtime_values=_runtime_values(),
        http_client=None,
        notifier_builder=lambda *_args, **_kwargs: notifier,
    )

    assert runtime.entries == ()
    assert notifier.replayed is None

    stop = asyncio.Event()
    replay = asyncio.create_task(runtime.notification_replay_worker.run(stop))
    for _ in range(10):
        if notifier.replayed is not None:
            break
        await asyncio.sleep(0)
    stop.set()
    await replay

    assert notifier.replayed == ()


async def test_incident_notification_replay_retries_transient_failure() -> None:
    notifier = _RetryingNotifier(ConnectionError("provider unavailable"))
    runtime = await build_incident_runtime(
        state_store=InMemoryStateStore(),
        runtime_values=_runtime_values(),
        http_client=None,
        notifier_builder=lambda *_args, **_kwargs: notifier,
    )
    worker = runtime.notification_replay_worker
    object.__setattr__(worker, "retry_interval_seconds", 0.001)
    stop = asyncio.Event()
    replay = asyncio.create_task(worker.run(stop))
    for _ in range(100):
        if notifier.replayed is not None:
            break
        await asyncio.sleep(0.001)
    stop.set()
    await replay

    assert notifier.calls == 2
    assert notifier.replayed == ()


async def test_incident_notification_replay_isolates_programming_failure() -> None:
    notifier = _RetryingNotifier(ValueError("invalid durable record"))
    runtime = await build_incident_runtime(
        state_store=InMemoryStateStore(),
        runtime_values=_runtime_values(),
        http_client=None,
        notifier_builder=lambda *_args, **_kwargs: notifier,
    )
    stop = asyncio.Event()
    replay = asyncio.create_task(runtime.notification_replay_worker.run(stop))
    await asyncio.sleep(0)

    assert notifier.calls == 1
    assert not replay.done()

    stop.set()
    await replay


async def test_incident_runtime_respects_disabled_auto_open_policy() -> None:
    runtime = await build_incident_runtime(
        state_store=InMemoryStateStore(),
        runtime_values=_runtime_values(enabled=False),
        http_client=None,
        notifier_builder=lambda *_args, **_kwargs: _RecordingNotifier(),
    )

    opened = await runtime.open_incident_candidate(
        {
            "incident_correlation": "correlate",
            "correlation_id": "correlation-1",
            "evidence_keys": ["evidence-1"],
            "resource_id": "resource-1",
            "event_type": "resource.health",
            "severity": "sev1",
        }
    )

    assert opened is False


async def test_incident_runtime_ignores_unrelated_tool_receipt() -> None:
    store = InMemoryStateStore()
    runtime = await build_incident_runtime(
        state_store=store,
        runtime_values=_runtime_values(),
        http_client=None,
        notifier_builder=lambda *_args, **_kwargs: _RecordingNotifier(),
    )
    request = ToolCallRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000010"),
        idempotency_key="tool-1",
        action_type_name="tool.open-incident-ticket",
        rule_ids=("operator-request",),
        tool_ref="incident-ticket",
        labels=("enforce",),
        mode=Mode.ENFORCE,
    )
    receipt = ToolCallReceipt(
        outcome=ToolCallOutcome.SUCCEEDED,
        receipt_ref="ticket-1",
    )

    await runtime.observe_tool_receipt(request, receipt)

    assert await store.read_incident_transitions() == ()
