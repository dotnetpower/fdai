from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

from fdai.core.executor import DirectApiExecutionOutcome, DirectApiShadowExecutor
from fdai.core.executor.lock import ResourceLockManager
from fdai.shared.providers.direct_api import DirectApiReceipt, DirectApiRequest
from fdai.shared.providers.testing import InMemoryStateStore, RecordingDirectApiExecutor
from fdai.shared.providers.testing.idempotency import InMemoryIdempotencyStore
from tests.core.executor.test_direct_api_executor import _action


def _executor(
    *,
    adapter: RecordingDirectApiExecutor | None = None,
    idempotency: InMemoryIdempotencyStore | None = None,
) -> tuple[DirectApiShadowExecutor, RecordingDirectApiExecutor, InMemoryStateStore]:
    resolved_adapter = adapter or RecordingDirectApiExecutor()
    audit = InMemoryStateStore()
    return (
        DirectApiShadowExecutor(
            executor=resolved_adapter,
            audit_store=audit,
            resource_lock=ResourceLockManager(),
            idempotency=idempotency,
        ),
        resolved_adapter,
        audit,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"action_id": UUID("00000000-0000-0000-0000-000000000012")},
        {"event_id": UUID("00000000-0000-0000-0000-000000000013")},
        {"target_resource_ref": "resource:example/rg/vm2"},
        {"params": {"cooldown_seconds": 60}},
        {"stop_condition": "different_stop"},
        {"citing_rules": ["different.rule"]},
    ],
)
async def test_same_key_with_different_action_is_audited_conflict(
    changes: dict[str, Any],
) -> None:
    executor, adapter, audit = _executor()
    original = _action()
    await executor.execute(action=original)

    conflict = await executor.execute(action=original.model_copy(update=changes))

    assert conflict.outcome is DirectApiExecutionOutcome.REJECTED_IDEMPOTENCY_CONFLICT
    assert len(adapter.records) == 1
    assert [row["entry"]["outcome"] for row in audit.audit_entries] == [
        "dispatched",
        "rejected_idempotency_conflict",
    ]


async def test_conflict_does_not_poison_original_cache() -> None:
    executor, adapter, _ = _executor()
    original = _action()
    first = await executor.execute(action=original)
    await executor.execute(
        action=original.model_copy(update={"target_resource_ref": "resource:other"})
    )

    retry = await executor.execute(action=original)

    assert retry is first
    assert len(adapter.records) == 1


async def test_durable_collision_after_restart_is_rejected() -> None:
    idempotency = InMemoryIdempotencyStore()
    first_executor, _, _ = _executor(idempotency=idempotency)
    original = _action()
    await first_executor.execute(action=original)
    second_executor, adapter, _ = _executor(idempotency=idempotency)

    result = await second_executor.execute(
        action=original.model_copy(update={"target_resource_ref": "resource:other"})
    )

    assert result.outcome is DirectApiExecutionOutcome.REJECTED_IDEMPOTENCY_CONFLICT
    assert adapter.records == ()


async def test_legacy_durable_payload_without_fingerprint_fails_closed() -> None:
    idempotency = InMemoryIdempotencyStore()
    action = _action()
    await idempotency.record(
        action.idempotency_key,
        {
            "action_id": str(action.action_id),
            "outcome": "dispatched",
            "mode": "shadow",
            "audit_context": {},
        },
    )
    executor, adapter, audit = _executor(idempotency=idempotency)

    result = await executor.execute(action=action)

    assert result.outcome is DirectApiExecutionOutcome.REJECTED_IDEMPOTENCY_CONFLICT
    assert adapter.records == ()
    assert len(list(audit.audit_entries)) == 1


async def test_concurrent_same_key_different_resources_are_serialized() -> None:
    class _BlockingAdapter(RecordingDirectApiExecutor):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = 0

        async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return await super().execute(request)

    adapter = _BlockingAdapter()
    executor, _, _ = _executor(adapter=adapter)
    original = _action()
    conflict = original.model_copy(update={"target_resource_ref": "resource:other"})
    first_task = asyncio.create_task(executor.execute(action=original))
    await adapter.started.wait()
    conflict_task = asyncio.create_task(executor.execute(action=conflict))
    await asyncio.sleep(0)

    assert adapter.calls == 1
    adapter.release.set()
    first, second = await asyncio.gather(first_task, conflict_task)

    assert first.outcome is DirectApiExecutionOutcome.DISPATCHED
    assert second.outcome is DirectApiExecutionOutcome.REJECTED_IDEMPOTENCY_CONFLICT
    assert adapter.calls == 1
