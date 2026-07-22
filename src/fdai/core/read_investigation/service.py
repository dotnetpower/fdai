"""Bounded provider orchestration for one exact resolved resource."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fdai.core.read_investigation.catalog import read_tool_spec
from fdai.core.read_investigation.models import (
    ReadInvestigationOutcome,
    ReadInvestigationPlan,
    ReadInvestigationResult,
    ReadInvestigationStep,
)
from fdai.core.read_investigation.progress import (
    ReadInvestigationProgressKind,
    completed_progress,
    querying_progress,
    unavailable_progress,
)
from fdai.shared.providers.read_investigation import (
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceAttempt,
    ReadEvidenceEnvelope,
    ReadInvestigationProvider,
    ReadLatencyProfileStore,
    ReadLatencySample,
    ReadToolId,
    ReadToolLimits,
    ResolvedResource,
    ResourceResolution,
    ResourceResolutionAttempt,
    ResourceResolutionStatus,
)
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt

ProgressObserver = Callable[[ReadInvestigationProgressKind], Awaitable[None]]
Clock = Callable[[], datetime]
Monotonic = Callable[[], float]
_LOG = logging.getLogger(__name__)


class ReadInvestigationService:
    """Execute a server-owned plan without widening scope or budgets."""

    def __init__(
        self,
        provider: ReadInvestigationProvider,
        *,
        clock: Clock | None = None,
        monotonic: Monotonic | None = None,
        latency_store: ReadLatencyProfileStore | None = None,
    ) -> None:
        self._provider = provider
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._monotonic = monotonic or time.monotonic
        self._latency_store = latency_store

    @property
    def transport(self) -> str:
        return self._provider.transport

    async def execute(
        self,
        plan: ReadInvestigationPlan,
        *,
        progress_observer: ProgressObserver | None = None,
    ) -> ReadInvestigationResult:
        started_at = self._clock()
        started_tick = self._monotonic()
        progress: list[str] = []
        receipts: list[ToolCallReceipt] = []
        evidence: list[ReadEvidenceEnvelope] = []

        async def emit(kind: ReadInvestigationProgressKind) -> None:
            progress.append(kind.value)
            if progress_observer is not None:
                await progress_observer(kind)

        await emit(ReadInvestigationProgressKind.PLANNED)
        await emit(ReadInvestigationProgressKind.RESOURCE_RESOLVING)
        resolution_attempt = await self._resolve(plan, started_tick=started_tick)
        resolution = resolution_attempt.resolution
        receipts.append(resolution_attempt.receipt)
        await self._record_latency(resolution_attempt.receipt, plan)

        if resolution.status is not ResourceResolutionStatus.MATCHED:
            await emit(_resolution_progress(resolution.status))
            await emit(ReadInvestigationProgressKind.COMPLETED)
            return self._result(
                plan,
                outcome=_resolution_outcome(resolution.status),
                resolution=resolution,
                evidence=evidence,
                receipts=receipts,
                progress=progress,
                started_at=started_at,
            )

        resource = resolution.resource
        if resource is None:  # pragma: no cover - guarded by ResourceResolution
            raise RuntimeError("matched resource resolution lost its resource")
        await emit(ReadInvestigationProgressKind.RESOURCE_RESOLVED)

        timed_out = False
        for step in plan.evidence_steps:
            remaining = plan.request.budget.max_wall_seconds - (self._monotonic() - started_tick)
            if remaining <= 0:
                timed_out = True
                break
            await emit(querying_progress(step.tool_id))
            attempt = await self._query(
                plan,
                step,
                resource,
                timeout_seconds=min(step.timeout_seconds, remaining),
            )
            receipts.append(attempt.receipt)
            await self._record_latency(attempt.receipt, plan)
            evidence.append(attempt.evidence)
            if attempt.evidence.status is EvidenceStatus.UNAVAILABLE:
                await emit(unavailable_progress(step.tool_id))
            else:
                await emit(completed_progress(step.tool_id))

        await emit(ReadInvestigationProgressKind.EVIDENCE_CORRELATING)
        await emit(ReadInvestigationProgressKind.COMPLETED)
        outcome = ReadInvestigationOutcome.TIMED_OUT if timed_out else _evidence_outcome(evidence)
        return self._result(
            plan,
            outcome=outcome,
            resolution=resolution,
            evidence=evidence,
            receipts=receipts,
            progress=progress,
            started_at=started_at,
        )

    async def _resolve(
        self,
        plan: ReadInvestigationPlan,
        *,
        started_tick: float,
    ) -> ResourceResolutionAttempt:
        step = plan.steps[0]
        remaining = plan.request.budget.max_wall_seconds - (self._monotonic() - started_tick)
        timeout = max(0.001, min(step.timeout_seconds, remaining))
        tick = self._monotonic()
        try:
            attempt = await asyncio.wait_for(
                self._provider.resolve_resource(
                    plan.request.selector,
                    limits=_limits(step),
                ),
                timeout=timeout,
            )
            resource = attempt.resolution.resource
            if resource is not None and resource.scope_ref != plan.request.selector.scope_ref:
                raise ValueError("provider widened the resolved resource scope")
            return attempt
        except Exception:
            return ResourceResolutionAttempt(
                resolution=ResourceResolution(
                    status=ResourceResolutionStatus.UNAVAILABLE,
                    detail="resource resolution unavailable",
                ),
                receipt=self._failed_receipt(
                    step.tool_id,
                    plan,
                    elapsed_ms=_elapsed_ms(self._monotonic() - tick),
                ),
            )

    async def _query(
        self,
        plan: ReadInvestigationPlan,
        step: ReadInvestigationStep,
        resource: ResolvedResource,
        *,
        timeout_seconds: float,
    ) -> ReadEvidenceAttempt:
        tick = self._monotonic()
        try:
            attempt = await asyncio.wait_for(
                self._dispatch(plan, step, resource),
                timeout=max(0.001, timeout_seconds),
            )
            if attempt.evidence.resource_ref != resource.resource_ref:
                raise ValueError("provider widened the evidence resource")
            return attempt
        except Exception:
            return ReadEvidenceAttempt(
                tool_id=step.tool_id,
                evidence=ReadEvidenceEnvelope(
                    status=EvidenceStatus.UNAVAILABLE,
                    authority=read_tool_spec(step.tool_id).operation_class,
                    resource_ref=resource.resource_ref,
                    observed_at=self._clock(),
                    freshness=EvidenceFreshness.LIVE,
                    truncated=False,
                    records=(),
                    evidence_refs=(),
                ),
                receipt=self._failed_receipt(
                    step.tool_id,
                    plan,
                    elapsed_ms=_elapsed_ms(self._monotonic() - tick),
                ),
            )

    async def _dispatch(
        self,
        plan: ReadInvestigationPlan,
        step: ReadInvestigationStep,
        resource: ResolvedResource,
    ) -> ReadEvidenceAttempt:
        limits = _limits(step)
        if step.tool_id is ReadToolId.GET_RESOURCE_STATE:
            return await self._provider.get_resource_state(resource, limits=limits)
        if step.tool_id is ReadToolId.QUERY_RESOURCE_ACTIVITY:
            return await self._provider.query_resource_activity(
                resource,
                lookback_seconds=plan.request.lookback_seconds,
                limits=limits,
            )
        if step.tool_id is ReadToolId.QUERY_RESOURCE_HEALTH:
            return await self._provider.query_resource_health(
                resource,
                lookback_seconds=plan.request.lookback_seconds,
                limits=limits,
            )
        if step.tool_id is ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS:
            return await self._provider.query_guest_shutdown_events(
                resource,
                lookback_seconds=plan.request.lookback_seconds,
                limits=limits,
            )
        raise ValueError("resolve_resource cannot be dispatched as evidence")

    def _failed_receipt(
        self,
        tool_id: ReadToolId,
        plan: ReadInvestigationPlan,
        *,
        elapsed_ms: int,
    ) -> ToolCallReceipt:
        spec = read_tool_spec(tool_id)
        return ToolCallReceipt(
            outcome=ToolCallOutcome.FAILED,
            receipt_ref=f"read-attempt:{tool_id.value}:{plan.request.correlation_ref}",
            detail="provider attempt unavailable",
            tool_id=tool_id.value,
            transport=self._provider.transport,
            operation_class=spec.operation_class,
            execution_duration_ms=elapsed_ms,
            recorded_at=self._clock(),
            trace_ref=plan.request.correlation_ref,
        )

    async def _record_latency(
        self,
        receipt: ToolCallReceipt,
        plan: ReadInvestigationPlan,
    ) -> None:
        if self._latency_store is None:
            return
        try:
            if (
                receipt.tool_id is None
                or receipt.transport is None
                or receipt.operation_class is None
                or receipt.recorded_at is None
            ):
                raise ValueError("investigation receipt is missing latency dimensions")
            sample = ReadLatencySample(
                tool_id=ReadToolId(receipt.tool_id),
                transport=receipt.transport,
                operation_class=receipt.operation_class,
                succeeded=receipt.outcome
                in {ToolCallOutcome.SUCCEEDED, ToolCallOutcome.ALREADY_APPLIED},
                queue_duration_ms=receipt.queue_duration_ms,
                execution_duration_ms=receipt.execution_duration_ms,
                recorded_at=receipt.recorded_at,
            )
            await self._latency_store.append(sample)
        except Exception as exc:  # noqa: BLE001 - telemetry cannot rewrite evidence
            _LOG.warning(
                "read_investigation_latency_record_failed",
                extra={
                    "correlation_id": plan.request.correlation_ref,
                    "error_kind": type(exc).__name__,
                },
            )

    def _result(
        self,
        plan: ReadInvestigationPlan,
        *,
        outcome: ReadInvestigationOutcome,
        resolution: ResourceResolution,
        evidence: list[ReadEvidenceEnvelope],
        receipts: list[ToolCallReceipt],
        progress: list[str],
        started_at: datetime,
    ) -> ReadInvestigationResult:
        return ReadInvestigationResult(
            request=plan.request,
            outcome=outcome,
            resolution=resolution,
            evidence=tuple(evidence),
            receipts=tuple(receipts),
            progress_kinds=tuple(progress),
            started_at=started_at,
            finished_at=self._clock(),
        )


def _limits(step: ReadInvestigationStep) -> ReadToolLimits:
    return ReadToolLimits(
        timeout_seconds=step.timeout_seconds,
        max_results=step.max_results,
        max_output_bytes=step.max_output_bytes,
    )


def _resolution_progress(
    status: ResourceResolutionStatus,
) -> ReadInvestigationProgressKind:
    return {
        ResourceResolutionStatus.NOT_FOUND: ReadInvestigationProgressKind.RESOURCE_NOT_FOUND,
        ResourceResolutionStatus.AMBIGUOUS: ReadInvestigationProgressKind.RESOURCE_AMBIGUOUS,
        ResourceResolutionStatus.UNAVAILABLE: ReadInvestigationProgressKind.RESOURCE_UNAVAILABLE,
    }[status]


def _resolution_outcome(status: ResourceResolutionStatus) -> ReadInvestigationOutcome:
    return {
        ResourceResolutionStatus.NOT_FOUND: ReadInvestigationOutcome.NONE,
        ResourceResolutionStatus.AMBIGUOUS: ReadInvestigationOutcome.AMBIGUOUS,
        ResourceResolutionStatus.UNAVAILABLE: ReadInvestigationOutcome.UNAVAILABLE,
    }[status]


def _evidence_outcome(evidence: list[ReadEvidenceEnvelope]) -> ReadInvestigationOutcome:
    statuses = {item.status for item in evidence}
    if not statuses or statuses == {EvidenceStatus.UNAVAILABLE}:
        return ReadInvestigationOutcome.UNAVAILABLE
    if EvidenceStatus.MATCHED in statuses:
        return (
            ReadInvestigationOutcome.PARTIAL
            if EvidenceStatus.UNAVAILABLE in statuses
            else ReadInvestigationOutcome.MATCHED
        )
    if EvidenceStatus.AMBIGUOUS in statuses:
        return ReadInvestigationOutcome.AMBIGUOUS
    if statuses == {EvidenceStatus.NONE}:
        return ReadInvestigationOutcome.NONE
    return ReadInvestigationOutcome.PARTIAL


def _elapsed_ms(seconds: float) -> int:
    return max(0, round(seconds * 1_000))


__all__ = ["ProgressObserver", "ReadInvestigationService"]
