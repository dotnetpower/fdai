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
from fdai.core.read_investigation import ReadInvestigationService
from fdai.delivery.read_api.routes.background_executor import (
    ChatBackendBackgroundTaskExecutor,
    ReadInvestigationBackgroundTaskExecutor,
    ServerOwnedReadInvestigationRequestFactory,
)
from fdai.shared.providers.read_investigation import (
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceAttempt,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ReadToolId,
    ResolvedResource,
    ResourceResolution,
    ResourceResolutionAttempt,
    ResourceResolutionStatus,
)
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt


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


class _ReadProvider:
    transport = "rest"

    def __init__(self) -> None:
        self.calls: list[ReadToolId] = []

    async def resolve_resource(self, selector, *, limits):  # type: ignore[no-untyped-def]
        del limits
        self.calls.append(ReadToolId.RESOLVE_RESOURCE)
        resource = ResolvedResource(
            resource_ref="resource:opaque",
            scope_ref=selector.scope_ref,
            name=selector.name,
            resource_type="compute.vm",
        )
        return ResourceResolutionAttempt(
            ResourceResolution(ResourceResolutionStatus.MATCHED, resource=resource),
            _read_receipt(ReadToolId.RESOLVE_RESOURCE, "resource_resolution"),
        )

    async def get_resource_state(self, resource, *, limits):  # type: ignore[no-untyped-def]
        del limits
        self.calls.append(ReadToolId.GET_RESOURCE_STATE)
        record = ReadEvidenceRecord(
            occurred_at=datetime(2026, 7, 20, tzinfo=UTC),
            status="observed",
            state="stopped",
        )
        return ReadEvidenceAttempt(
            ReadToolId.GET_RESOURCE_STATE,
            ReadEvidenceEnvelope(
                status=EvidenceStatus.MATCHED,
                authority="azure.resource_state",
                resource_ref=resource.resource_ref,
                observed_at=record.occurred_at,
                freshness=EvidenceFreshness.LIVE,
                truncated=False,
                records=(record,),
                evidence_refs=("evidence:opaque",),
            ),
            _read_receipt(ReadToolId.GET_RESOURCE_STATE, "resource_state", result_count=1),
        )

    async def query_resource_activity(self, resource, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("state investigation must not query activity")

    async def query_resource_health(self, resource, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("state investigation must not query health")

    async def query_guest_shutdown_events(self, resource, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("state investigation must not query guest logs")


def _read_receipt(
    tool_id: ReadToolId,
    operation_class: str,
    *,
    result_count: int = 0,
) -> ToolCallReceipt:
    now = datetime(2026, 7, 20, tzinfo=UTC)
    return ToolCallReceipt(
        outcome=ToolCallOutcome.SUCCEEDED,
        receipt_ref=f"receipt:{tool_id.value}",
        tool_id=tool_id.value,
        transport="rest",
        operation_class=operation_class,
        result_count=result_count,
        recorded_at=now,
        trace_ref="trace:one",
    )


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


async def test_typed_executor_uses_only_read_service_and_semantic_progress() -> None:
    now = datetime(2026, 7, 20, tzinfo=UTC)
    task = BackgroundTask(
        task_id="background-read-one",
        owner_principal_id="operator-one",
        origin=BackgroundTaskOrigin("conversation-one", "web", "channel-one"),
        kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
        prompt="What is the current state of vm-01?",
        context_digest="sha256:context",
        capability_profile_id="background.read-only",
        budget=BackgroundTaskBudget(),
        correlation_id="correlation-one",
        idempotency_key="idempotency-one",
        created_at=now,
        retention_until=now + timedelta(days=30),
    )
    provider = _ReadProvider()
    executor = ReadInvestigationBackgroundTaskExecutor(
        service=ReadInvestigationService(provider, clock=lambda: now),
        request_factory=ServerOwnedReadInvestigationRequestFactory(scope_ref="scope:allowed"),
    )
    progress: list[str] = []

    async def report(kind: str, message: str, usage: BackgroundTaskUsage) -> None:
        del message, usage
        progress.append(kind)

    result = await executor.execute(task=task, progress=report)

    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]
    assert result.terminal_reason == "matched"
    assert result.evidence_refs == ("evidence:opaque",)
    assert result.usage.tool_calls == 2
    assert progress.count("investigation.completed") == 1
    assert not hasattr(executor, "backend")
    assert not hasattr(executor, "identity")
    assert not hasattr(executor, "bus")
