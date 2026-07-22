"""Background investigation adapter over the configured narrator backend."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Protocol

from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskResult,
    BackgroundTaskUsage,
    ProgressCallback,
)
from fdai.core.read_investigation import (
    ReadInvestigationBudget,
    ReadInvestigationProgressKind,
    ReadInvestigationRequest,
    ReadInvestigationResult,
    ReadInvestigationService,
    classify_read_investigation_intent,
    plan_read_investigation,
    resource_name_from_question,
)
from fdai.delivery.read_api.routes.chat_backend_common import ChatBackend
from fdai.shared.providers.read_investigation import ResourceSelector

_DEEP = re.compile(r"\b(?:deep|thorough|comprehensive)\b|(?:심층|자세히|종합)", re.IGNORECASE)


class BackgroundReadInvestigationRequestFactory(Protocol):
    def build(self, task: BackgroundTask) -> ReadInvestigationRequest: ...


class ServerOwnedReadInvestigationRequestFactory:
    def __init__(self, *, scope_ref: str, lookback_seconds: int = 3_600) -> None:
        if not scope_ref.strip() or len(scope_ref) > 256:
            raise ValueError("scope_ref MUST be a bounded identifier")
        if not 60 <= lookback_seconds <= 2_592_000:
            raise ValueError("lookback_seconds MUST be in [60, 2592000]")
        self._scope_ref = scope_ref
        self._lookback_seconds = lookback_seconds

    def build(self, task: BackgroundTask) -> ReadInvestigationRequest:
        intent = classify_read_investigation_intent(task.prompt)
        if intent is None:
            raise ValueError("background prompt is not a supported read investigation")
        resource_name = resource_name_from_question(task.prompt)
        if resource_name is None:
            raise ValueError("background prompt requires one bounded resource name")
        return ReadInvestigationRequest(
            requester_ref=task.owner_principal_id,
            conversation_ref=task.origin.conversation_id,
            correlation_ref=task.correlation_id,
            intent=intent,
            selector=ResourceSelector(name=resource_name, scope_ref=self._scope_ref),
            lookback_seconds=self._lookback_seconds,
            requested_evidence=(),
            budget=ReadInvestigationBudget(
                max_wall_seconds=task.budget.max_wall_seconds,
                max_cost_microusd=task.budget.max_cost_microusd,
                max_tool_calls=min(task.budget.max_tool_calls, 5),
                max_results=32,
                max_output_bytes=256_000,
            ),
            idempotency_key=task.idempotency_key,
            created_at=task.created_at,
            explicit_deep=_DEEP.search(task.prompt) is not None,
        )


class ReadInvestigationBackgroundTaskExecutor:
    """Execute typed read tools without narrator or mutation capabilities."""

    def __init__(
        self,
        *,
        service: ReadInvestigationService,
        request_factory: BackgroundReadInvestigationRequestFactory,
    ) -> None:
        self._service = service
        self._request_factory = request_factory

    async def execute(
        self,
        *,
        task: BackgroundTask,
        progress: ProgressCallback,
    ) -> BackgroundTaskResult:
        started_at = datetime.now(UTC)
        request = self._request_factory.build(task)

        async def observe(kind: ReadInvestigationProgressKind) -> None:
            await progress(kind.value, _progress_message(kind), BackgroundTaskUsage())

        result = await self._service.execute(
            plan_read_investigation(request),
            progress_observer=observe,
        )
        finished_at = datetime.now(UTC)
        return BackgroundTaskResult(
            summary=_render_result(result),
            evidence_refs=result.evidence_refs,
            terminal_reason=result.outcome.value,
            usage=BackgroundTaskUsage(tool_calls=len(result.receipts)),
            started_at=started_at,
            finished_at=max(finished_at, started_at),
        )


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


def _progress_message(kind: ReadInvestigationProgressKind) -> str:
    return kind.value.replace(".", " ").replace("-", " ").capitalize() + "."


def _render_result(result: ReadInvestigationResult) -> str:
    lines = [f"Investigation result: {result.outcome.value}."]
    if result.resolution.resource is not None:
        lines.append(
            "Resolved resource: "
            f"{result.resolution.resource.name} ({result.resolution.resource.resource_type})."
        )
    elif result.resolution.candidates:
        candidates = ", ".join(
            f"{item.name} ({item.resource_group or 'group unavailable'})"
            for item in result.resolution.candidates
        )
        lines.append(f"Ambiguous candidates: {candidates}.")
    for envelope in result.evidence:
        lines.append(
            f"{envelope.authority}: {envelope.status.value}, "
            f"records={len(envelope.records)}, truncated={str(envelope.truncated).lower()}."
        )
    return " ".join(lines)[:8_000]


__all__ = [
    "BackgroundReadInvestigationRequestFactory",
    "ChatBackendBackgroundTaskExecutor",
    "ReadInvestigationBackgroundTaskExecutor",
    "ServerOwnedReadInvestigationRequestFactory",
]
