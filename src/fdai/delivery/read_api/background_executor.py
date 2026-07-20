"""Background investigation adapter over the configured narrator backend."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskResult,
    BackgroundTaskUsage,
    ProgressCallback,
)
from fdai.delivery.read_api.routes.chat_backend_common import ChatBackend


class ChatBackendBackgroundTaskExecutor:
    def __init__(self, *, backend: ChatBackend) -> None:
        self._backend = backend

    async def execute(
        self,
        *,
        task: BackgroundTask,
        progress: ProgressCallback,
    ) -> BackgroundTaskResult:
        started_at = datetime.now(UTC)
        await progress(
            "investigation.started", "Read-only investigation started.", BackgroundTaskUsage()
        )
        payload = await self._backend.answer(
            prompt=(
                "Perform one bounded read-only investigation. Do not propose or execute changes, "
                "do not request clarification, and hold when evidence is unavailable.\n"
                + task.prompt
            ),
            view_context={
                "task_id": task.task_id,
                "correlation_id": task.correlation_id,
                "context_digest": task.context_digest,
                "capability_profile_id": task.capability_profile_id,
            },
            history=[],
        )
        answer = payload.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("background narrator returned no answer")
        usage = BackgroundTaskUsage()
        await progress("investigation.completed", "Read-only investigation completed.", usage)
        finished_at = datetime.now(UTC)
        return BackgroundTaskResult(
            summary=answer[:8_000],
            evidence_refs=(),
            terminal_reason="completed",
            usage=usage,
            started_at=started_at,
            finished_at=max(finished_at, started_at),
        )


__all__ = ["ChatBackendBackgroundTaskExecutor"]
