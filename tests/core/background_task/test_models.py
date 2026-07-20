from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskAttempt,
    BackgroundTaskBudget,
    BackgroundTaskKind,
    BackgroundTaskLease,
    BackgroundTaskOrigin,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskUsage,
)

_NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _task() -> BackgroundTask:
    return BackgroundTask(
        task_id="background-one",
        owner_principal_id="operator-one",
        origin=BackgroundTaskOrigin("conversation-one", "web", "channel-one"),
        kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
        prompt="Inspect the bounded evidence.",
        context_digest="sha256:context",
        capability_profile_id="background.read-only",
        budget=BackgroundTaskBudget(),
        correlation_id="correlation-one",
        idempotency_key="background:idempotency-one",
        created_at=_NOW,
        retention_until=_NOW + timedelta(days=30),
    )


def test_attempt_state_contract_requires_lease_or_terminal_result() -> None:
    task = _task()
    lease = BackgroundTaskLease("coordinator-one", "lease-one", _NOW + timedelta(seconds=30))

    claimed = BackgroundTaskAttempt(
        attempt_id="attempt-one",
        task=task,
        attempt_number=1,
        status=BackgroundTaskStatus.CLAIMED,
        revision=2,
        updated_at=_NOW,
        lease=lease,
    )
    terminal = BackgroundTaskAttempt(
        attempt_id="attempt-one",
        task=task,
        attempt_number=1,
        status=BackgroundTaskStatus.UNKNOWN,
        revision=3,
        updated_at=_NOW,
        result=BackgroundTaskResult(
            summary=None,
            evidence_refs=(),
            terminal_reason="process_lost",
            usage=BackgroundTaskUsage(),
            started_at=_NOW,
            finished_at=_NOW,
        ),
    )

    assert claimed.lease == lease
    assert terminal.result is not None and terminal.status is BackgroundTaskStatus.UNKNOWN
    with pytest.raises(ValueError, match="require a lease"):
        BackgroundTaskAttempt(
            attempt_id="attempt-invalid",
            task=task,
            attempt_number=1,
            status=BackgroundTaskStatus.RUNNING,
            revision=1,
            updated_at=_NOW,
        )
    with pytest.raises(ValueError, match="require a result"):
        BackgroundTaskAttempt(
            attempt_id="attempt-invalid",
            task=task,
            attempt_number=1,
            status=BackgroundTaskStatus.FAILED,
            revision=1,
            updated_at=_NOW,
        )


def test_task_rejects_mutation_profile_or_invalid_retention() -> None:
    task = _task()
    with pytest.raises(ValueError, match="background.read-only"):
        BackgroundTask(
            task_id=task.task_id,
            owner_principal_id=task.owner_principal_id,
            origin=task.origin,
            kind=task.kind,
            prompt=task.prompt,
            context_digest=task.context_digest,
            capability_profile_id="background.mutate",
            budget=task.budget,
            correlation_id=task.correlation_id,
            idempotency_key=task.idempotency_key,
            created_at=task.created_at,
            retention_until=task.retention_until,
        )
    with pytest.raises(ValueError, match="after created_at"):
        BackgroundTask(
            task_id=task.task_id,
            owner_principal_id=task.owner_principal_id,
            origin=task.origin,
            kind=task.kind,
            prompt=task.prompt,
            context_digest=task.context_digest,
            capability_profile_id=task.capability_profile_id,
            budget=task.budget,
            correlation_id=task.correlation_id,
            idempotency_key=task.idempotency_key,
            created_at=task.created_at,
            retention_until=task.created_at,
        )
