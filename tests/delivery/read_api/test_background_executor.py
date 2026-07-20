from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskBudget,
    BackgroundTaskKind,
    BackgroundTaskOrigin,
    BackgroundTaskUsage,
)
from fdai.delivery.read_api.background_executor import ChatBackendBackgroundTaskExecutor


class _Backend:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        self.calls.append({"prompt": prompt, "view_context": view_context, "history": history})
        return {"answer": "Bounded answer.", "model": "test-model"}


async def test_executor_passes_no_parent_history_or_screen_state() -> None:
    now = datetime(2026, 7, 20, tzinfo=UTC)
    task = BackgroundTask(
        task_id="background-one",
        owner_principal_id="operator-one",
        origin=BackgroundTaskOrigin("conversation-one", "web", "channel-one"),
        kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
        prompt="Inspect bounded evidence.",
        context_digest="sha256:context",
        capability_profile_id="background.read-only",
        budget=BackgroundTaskBudget(),
        correlation_id="correlation-one",
        idempotency_key="idempotency-one",
        created_at=now,
        retention_until=now + timedelta(days=30),
    )
    backend = _Backend()
    progress: list[tuple[str, str, BackgroundTaskUsage]] = []

    async def report(kind: str, message: str, usage: BackgroundTaskUsage) -> None:
        progress.append((kind, message, usage))

    result = await ChatBackendBackgroundTaskExecutor(backend=backend).execute(
        task=task,
        progress=report,
    )

    assert result.summary == "Bounded answer."
    assert result.trusted is False
    assert backend.calls[0]["history"] == []
    assert backend.calls[0]["view_context"] == {
        "task_id": "background-one",
        "correlation_id": "correlation-one",
        "context_digest": "sha256:context",
        "capability_profile_id": "background.read-only",
    }
    assert len(progress) == 2
