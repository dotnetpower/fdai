"""Execute one persisted typed read investigation inside the bounded coordinator."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fdai.core.background_task.models import (
    BackgroundTask,
    BackgroundTaskResult,
    BackgroundTaskUsage,
)
from fdai.core.read_investigation.models import (
    ReadInvestigationBudget,
    ReadInvestigationRequest,
)
from fdai.core.read_investigation.planner import plan_read_investigation
from fdai.core.read_investigation.progress import ReadInvestigationProgressKind
from fdai.core.read_investigation.service import ReadInvestigationService
from fdai.shared.providers.read_investigation import ResourceSelector

ProgressCallback = Callable[[str, str, BackgroundTaskUsage], Awaitable[None]]


class ReadInvestigationBackgroundExecutor:
    """Adapt durable background tasks to the provider-neutral read service."""

    def __init__(
        self,
        service: ReadInvestigationService,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self,
        *,
        task: BackgroundTask,
        progress: ProgressCallback,
    ) -> BackgroundTaskResult:
        """Execute a verified spec or return an explicit no-provider limitation."""

        started_at = self._clock()
        spec = task.investigation
        if spec is None:
            return _limited_result(
                "read_investigation_spec_unavailable",
                started_at=started_at,
                finished_at=self._clock(),
            )
        if task.budget.max_tool_calls < 1:
            return _limited_result(
                "tool_budget_exhausted",
                started_at=started_at,
                finished_at=self._clock(),
            )
        request = ReadInvestigationRequest(
            requester_ref=task.owner_principal_id,
            conversation_ref=task.origin.conversation_id,
            correlation_ref=task.correlation_id,
            intent=spec.intent,
            selector=ResourceSelector(
                name=spec.resource_name,
                scope_ref=spec.scope_ref,
                resource_type=spec.resource_type,
                resource_group=spec.resource_group,
            ),
            lookback_seconds=spec.lookback_seconds,
            requested_evidence=(),
            budget=ReadInvestigationBudget(
                max_wall_seconds=task.budget.max_wall_seconds,
                max_cost_microusd=task.budget.max_cost_microusd,
                max_tool_calls=min(5, task.budget.max_tool_calls),
            ),
            idempotency_key=task.idempotency_key,
            created_at=task.created_at,
            explicit_deep=spec.explicit_deep,
        )

        async def report(kind: ReadInvestigationProgressKind) -> None:
            await progress(kind.value, kind.value, BackgroundTaskUsage())

        result = await self._service.execute(
            plan_read_investigation(request),
            progress_observer=report,
        )
        measured_costs = tuple(receipt.cost_microusd for receipt in result.receipts)
        cost_microusd = (
            sum(cost for cost in measured_costs if cost is not None)
            if all(cost is not None for cost in measured_costs)
            else task.budget.max_cost_microusd
        )
        usage = BackgroundTaskUsage(
            cost_microusd=cost_microusd,
            tool_calls=len(result.receipts),
        )
        return BackgroundTaskResult(
            summary=(
                f"Read investigation finished with outcome {result.outcome.value}; "
                f"evidence envelopes={len(result.evidence)}; receipts={len(result.receipts)}."
            ),
            evidence_refs=result.evidence_refs,
            terminal_reason=result.outcome.value,
            usage=usage,
            started_at=result.started_at,
            finished_at=result.finished_at,
        )


def _limited_result(
    reason: str,
    *,
    started_at: datetime,
    finished_at: datetime,
) -> BackgroundTaskResult:
    return BackgroundTaskResult(
        summary=None,
        evidence_refs=(),
        terminal_reason=reason,
        usage=BackgroundTaskUsage(),
        started_at=started_at,
        finished_at=max(started_at, finished_at),
    )


__all__ = ["ReadInvestigationBackgroundExecutor"]
