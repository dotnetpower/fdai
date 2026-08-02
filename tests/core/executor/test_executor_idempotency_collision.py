from __future__ import annotations

import asyncio
from typing import Any

import pytest

from fdai.core.executor import ExecutorOutcome, ShadowExecutor, TemplateRenderer
from fdai.core.executor.lock import ResourceLockManager
from fdai.shared.contracts.models import Action
from fdai.shared.providers.remediation_pr import PublishReceipt, RemediationPr
from fdai.shared.providers.testing import InMemoryStateStore, RecordingRemediationPrPublisher
from fdai.shared.providers.testing.idempotency import InMemoryIdempotencyStore
from tests.core.executor.test_executor import REMEDIATION_ROOT, _action, _rule


def _executor(
    *,
    publisher: RecordingRemediationPrPublisher | None = None,
    audit: InMemoryStateStore | None = None,
    idempotency: InMemoryIdempotencyStore | None = None,
) -> tuple[ShadowExecutor, RecordingRemediationPrPublisher, InMemoryStateStore]:
    resolved_publisher = publisher or RecordingRemediationPrPublisher()
    resolved_audit = audit or InMemoryStateStore()
    return (
        ShadowExecutor(
            publisher=resolved_publisher,
            audit_store=resolved_audit,
            renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
            resource_lock=ResourceLockManager(),
            idempotency=idempotency,
        ),
        resolved_publisher,
        resolved_audit,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"action_id": "00000000-0000-0000-0000-000000000012"},
        {"event_id": "00000000-0000-0000-0000-000000000013"},
        {"target_resource_ref": "resource:example/rg/stg2"},
        {"params": {"tag_value": "team-b"}},
        {"stop_condition": "different_stop"},
        {"citing_rules": ["different.rule"]},
    ],
)
async def test_same_key_with_different_action_is_audited_conflict(
    changes: dict[str, Any],
) -> None:
    executor, publisher, audit = _executor()
    first = await executor.execute(action=_action(), rule=_rule())
    changed_action = _action().model_copy(update=changes)

    conflict = await executor.execute(action=changed_action, rule=_rule())

    assert first.outcome is ExecutorOutcome.PUBLISHED
    assert conflict.outcome is ExecutorOutcome.REJECTED_IDEMPOTENCY_CONFLICT
    assert len(publisher.records) == 1
    assert [item["entry"]["outcome"] for item in audit.audit_entries] == [
        "intent_persisted",
        "published",
        "rejected_idempotency_conflict",
    ]


async def test_conflict_does_not_poison_original_cached_result() -> None:
    executor, publisher, _ = _executor()
    original = _action()
    first = await executor.execute(action=original, rule=_rule())
    await executor.execute(
        action=original.model_copy(update={"target_resource_ref": "resource:example/rg/other"}),
        rule=_rule(),
    )

    retry = await executor.execute(action=original, rule=_rule())

    assert retry is first
    assert len(publisher.records) == 1


async def test_durable_collision_after_restart_is_rejected_without_publish() -> None:
    idempotency = InMemoryIdempotencyStore()
    first_executor, _, _ = _executor(idempotency=idempotency)
    original = _action()
    await first_executor.execute(action=original, rule=_rule())
    second_executor, publisher, _ = _executor(idempotency=idempotency)

    result = await second_executor.execute(
        action=original.model_copy(update={"target_resource_ref": "resource:example/rg/other"}),
        rule=_rule(),
    )

    assert result.outcome is ExecutorOutcome.REJECTED_IDEMPOTENCY_CONFLICT
    assert publisher.records == ()


async def test_legacy_durable_payload_without_fingerprint_fails_closed() -> None:
    idempotency = InMemoryIdempotencyStore()
    action: Action = _action()
    await idempotency.record(
        action.idempotency_key,
        {
            "action_id": str(action.action_id),
            "outcome": "published",
            "mode": "shadow",
            "audit_context": {},
        },
    )
    executor, publisher, audit = _executor(idempotency=idempotency)

    result = await executor.execute(action=action, rule=_rule())

    assert result.outcome is ExecutorOutcome.REJECTED_IDEMPOTENCY_CONFLICT
    assert publisher.records == ()
    assert len(list(audit.audit_entries)) == 1


async def test_concurrent_same_key_different_resources_are_serialized() -> None:
    class _BlockingPublisher(RecordingRemediationPrPublisher):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = 0

        async def publish(self, pr: RemediationPr) -> PublishReceipt:
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return await super().publish(pr)

    publisher = _BlockingPublisher()
    executor, _, audit = _executor(publisher=publisher)
    original = _action()
    conflicting = original.model_copy(update={"target_resource_ref": "resource:example/rg/other"})
    first_task = asyncio.create_task(executor.execute(action=original, rule=_rule()))
    await publisher.started.wait()
    conflict_task = asyncio.create_task(executor.execute(action=conflicting, rule=_rule()))
    await asyncio.sleep(0)

    assert publisher.calls == 1
    publisher.release.set()
    first, conflict = await asyncio.gather(first_task, conflict_task)

    assert first.outcome is ExecutorOutcome.PUBLISHED
    assert conflict.outcome is ExecutorOutcome.REJECTED_IDEMPOTENCY_CONFLICT
    assert publisher.calls == 1
    assert [item["entry"]["outcome"] for item in audit.audit_entries] == [
        "intent_persisted",
        "published",
        "rejected_idempotency_conflict",
    ]
