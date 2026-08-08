"""Bounded lifecycle runtime for isolated read-only task workers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai.core.operator_memory.sanitizer import detect_injection_markers
from fdai.core.task_worker.attenuation import attenuate_capabilities
from fdai.core.task_worker.models import (
    AttenuatedCapabilities,
    TaskWorkerOutput,
    TaskWorkerRequest,
    TaskWorkerResult,
    TaskWorkerSnapshot,
    TaskWorkerStatus,
    TaskWorkerUsage,
    isolated_context,
)
from fdai.core.task_worker.store import TaskWorkerStore
from fdai.core.task_worker.tools import (
    TaskWorkerBudgetExhaustedError,
    TaskWorkerTool,
    TaskWorkerToolDeniedError,
    TaskWorkerToolGateway,
)


class TaskWorkerExecutor(Protocol):
    async def execute(
        self,
        *,
        context: object,
        tools: TaskWorkerToolGateway,
        max_tokens: int,
        max_cost_microusd: int,
    ) -> TaskWorkerOutput: ...


class TaskWorkerCompletionSink(Protocol):
    async def publish(self, result: TaskWorkerResult) -> None: ...


@dataclass(frozen=True, slots=True)
class TaskWorkerRuntimeConfig:
    max_parallelism: int = 4
    profile_allowed_tools: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not 1 <= self.max_parallelism <= 16:
            raise ValueError("max_parallelism MUST be in [1, 16]")
        if len(self.profile_allowed_tools) > 64:
            raise ValueError("profile_allowed_tools exceeds 64")


class TaskWorkerCancellationError(PermissionError):
    """Cancellation did not come from the request's immutable owner."""


class TaskWorkerRuntime:
    def __init__(
        self,
        *,
        store: TaskWorkerStore,
        executor: TaskWorkerExecutor,
        tools: tuple[TaskWorkerTool, ...],
        config: TaskWorkerRuntimeConfig | None = None,
        completion_sink: TaskWorkerCompletionSink | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._executor = executor
        self._tools = tools
        self._config = config or TaskWorkerRuntimeConfig()
        self._completion_sink = completion_sink
        self._clock = clock or (lambda: datetime.now(UTC))
        self._semaphore = asyncio.Semaphore(self._config.max_parallelism)
        self._tasks: dict[str, asyncio.Task[TaskWorkerResult]] = {}

    async def start(
        self,
        request: TaskWorkerRequest,
        *,
        parent_visible_tools: frozenset[str],
    ) -> asyncio.Task[TaskWorkerResult]:
        capabilities = self._attenuate(request, parent_visible_tools)
        snapshot, created = await self._store.create(
            TaskWorkerSnapshot(
                request=request,
                capabilities=capabilities,
                status=TaskWorkerStatus.PENDING,
                usage=TaskWorkerUsage(),
                updated_at=request.created_at,
            )
        )
        if not created:
            if snapshot.result is not None:
                return asyncio.create_task(self._return(snapshot.result))
            active = self._tasks.get(request.worker_id)
            if active is not None:
                return active
            raise RuntimeError("worker exists without a live task or terminal result")
        await self._store.append_event(
            request.worker_id,
            kind="worker.created",
            at=request.created_at,
            details=(("parent_trace_ref", request.parent_trace_ref),),
        )
        task = asyncio.create_task(
            self._run(request, capabilities),
            name=f"task-worker:{request.worker_id}",
        )
        self._tasks[request.worker_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(request.worker_id, None))
        return task

    async def run(
        self,
        request: TaskWorkerRequest,
        *,
        parent_visible_tools: frozenset[str],
    ) -> TaskWorkerResult:
        return await (await self.start(request, parent_visible_tools=parent_visible_tools))

    async def cancel(self, worker_id: str, *, owner: str) -> None:
        snapshot = await self._store.get(worker_id)
        if snapshot is None:
            raise LookupError(f"task worker {worker_id!r} was not found")
        if snapshot.request.cancellation_owner != owner:
            raise TaskWorkerCancellationError("worker cancellation owner mismatch")
        task = self._tasks.get(worker_id)
        if task is not None and not task.done():
            task.cancel()
            return
        if snapshot.status in {TaskWorkerStatus.PENDING, TaskWorkerStatus.RUNNING}:
            now = max(self._clock(), snapshot.request.created_at)
            result = self._terminal(
                snapshot.request,
                status=TaskWorkerStatus.CANCELLED,
                reason="cancelled_by_owner",
                usage=snapshot.usage,
                started_at=snapshot.request.created_at,
                finished_at=now,
            )
            await self._finish(snapshot, result)

    async def recover_interrupted(self) -> tuple[TaskWorkerResult, ...]:
        recovered: list[TaskWorkerResult] = []
        for snapshot in await self._store.list(limit=1_000):
            if snapshot.status not in {TaskWorkerStatus.PENDING, TaskWorkerStatus.RUNNING}:
                continue
            now = max(self._clock(), snapshot.request.created_at)
            result = self._terminal(
                snapshot.request,
                status=TaskWorkerStatus.FAILED,
                reason="runtime_restart_interrupted",
                usage=snapshot.usage,
                started_at=snapshot.request.created_at,
                finished_at=now,
            )
            await self._finish(snapshot, result)
            recovered.append(result)
        return tuple(recovered)

    async def _run(
        self,
        request: TaskWorkerRequest,
        capabilities: AttenuatedCapabilities,
    ) -> TaskWorkerResult:
        async with self._semaphore:
            started = max(self._clock(), request.created_at)
            running = await self._store.transition(
                request.worker_id,
                expected=frozenset({TaskWorkerStatus.PENDING}),
                status=TaskWorkerStatus.RUNNING,
                usage=TaskWorkerUsage(),
                at=started,
            )
            await self._store.append_event(
                request.worker_id,
                kind="worker.started",
                at=started,
                details=(("allowed_tools", str(len(capabilities.allowed_tools))),),
            )
            if request.requested_tools and not capabilities.allowed_tools:
                result = self._terminal(
                    request,
                    status=TaskWorkerStatus.DENIED,
                    reason="no_allowed_capabilities",
                    usage=TaskWorkerUsage(),
                    started_at=started,
                    finished_at=max(self._clock(), started),
                )
                return await self._finish(running, result)
            gateway = TaskWorkerToolGateway(
                tools=self._tools,
                capabilities=capabilities,
                budget=request.budget,
            )
            heartbeat_stop = asyncio.Event()
            heartbeat_task = asyncio.create_task(
                self._heartbeat(request.worker_id, gateway, heartbeat_stop),
                name=f"task-worker-heartbeat:{request.worker_id}",
            )
            try:
                async with asyncio.timeout(request.budget.max_wall_seconds):
                    output = await self._executor.execute(
                        context=isolated_context(request),
                        tools=gateway,
                        max_tokens=request.budget.max_tokens,
                        max_cost_microusd=request.budget.max_cost_microusd,
                    )
                usage = TaskWorkerUsage(
                    tokens=output.usage.tokens,
                    cost_microusd=output.usage.cost_microusd,
                    tool_calls=gateway.usage.tool_calls,
                )
                status, reason = self._validate_output(request, output, gateway, usage)
                result = self._terminal(
                    request,
                    status=status,
                    reason=reason,
                    usage=usage,
                    started_at=started,
                    finished_at=max(self._clock(), started),
                    output=output
                    if status in {TaskWorkerStatus.SUCCEEDED, TaskWorkerStatus.ABSTAINED}
                    else None,
                )
            except TimeoutError:
                result = self._terminal(
                    request,
                    status=TaskWorkerStatus.TIMED_OUT,
                    reason="wall_clock_exhausted",
                    usage=gateway.usage,
                    started_at=started,
                    finished_at=max(self._clock(), started),
                )
            except asyncio.CancelledError:
                result = self._terminal(
                    request,
                    status=TaskWorkerStatus.CANCELLED,
                    reason="cancelled_by_owner",
                    usage=gateway.usage,
                    started_at=started,
                    finished_at=max(self._clock(), started),
                )
            except TaskWorkerBudgetExhaustedError:
                result = self._terminal(
                    request,
                    status=TaskWorkerStatus.BUDGET_EXHAUSTED,
                    reason="tool_call_budget_exhausted",
                    usage=gateway.usage,
                    started_at=started,
                    finished_at=max(self._clock(), started),
                )
            except TaskWorkerToolDeniedError:
                result = self._terminal(
                    request,
                    status=TaskWorkerStatus.DENIED,
                    reason="tool_invocation_denied",
                    usage=gateway.usage,
                    started_at=started,
                    finished_at=max(self._clock(), started),
                )
            except Exception as exc:  # noqa: BLE001 - terminal state owns worker failure
                result = self._terminal(
                    request,
                    status=TaskWorkerStatus.FAILED,
                    reason=f"executor_error:{type(exc).__name__}",
                    usage=gateway.usage,
                    started_at=started,
                    finished_at=max(self._clock(), started),
                )
            finally:
                heartbeat_stop.set()
                await heartbeat_task
            return await self._finish(running, result)

    async def _heartbeat(
        self,
        worker_id: str,
        gateway: TaskWorkerToolGateway,
        stop: asyncio.Event,
    ) -> None:
        snapshot = await self._store.get(worker_id)
        if snapshot is None:
            return
        interval = snapshot.request.budget.heartbeat_seconds
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                now = self._clock()
                await self._store.heartbeat(worker_id, usage=gateway.usage, at=now)
                await self._store.append_event(
                    worker_id,
                    kind="worker.heartbeat",
                    at=now,
                    details=(("tool_calls", str(gateway.usage.tool_calls)),),
                )

    async def _finish(
        self,
        snapshot: TaskWorkerSnapshot,
        result: TaskWorkerResult,
    ) -> TaskWorkerResult:
        await self._store.transition(
            snapshot.request.worker_id,
            expected=frozenset({TaskWorkerStatus.PENDING, TaskWorkerStatus.RUNNING}),
            status=result.status,
            usage=result.usage,
            at=result.finished_at,
            result=result,
        )
        await self._store.append_event(
            snapshot.request.worker_id,
            kind=f"worker.{result.status.value}",
            at=result.finished_at,
            details=(("reason", result.terminal_reason),),
        )
        if self._completion_sink is not None:
            try:
                await self._completion_sink.publish(result)
            except Exception as exc:  # noqa: BLE001 - delivery never rewrites durable completion
                await self._store.append_event(
                    snapshot.request.worker_id,
                    kind="worker.completion_delivery_failed",
                    at=result.finished_at,
                    details=(("error", type(exc).__name__),),
                )
        return result

    def _attenuate(
        self,
        request: TaskWorkerRequest,
        parent_visible_tools: frozenset[str],
    ) -> AttenuatedCapabilities:
        return attenuate_capabilities(
            requested=request.requested_tools,
            parent_visible=parent_visible_tools,
            profile_allowed=self._config.profile_allowed_tools,
            side_effect_classes={tool.name: tool.side_effect_class for tool in self._tools},
        )

    @staticmethod
    async def _return(result: TaskWorkerResult) -> TaskWorkerResult:
        return result

    @staticmethod
    def _validate_output(
        request: TaskWorkerRequest,
        output: TaskWorkerOutput,
        gateway: TaskWorkerToolGateway,
        usage: TaskWorkerUsage,
    ) -> tuple[TaskWorkerStatus, str]:
        if not usage.within(request.budget):
            return TaskWorkerStatus.BUDGET_EXHAUSTED, "reported_usage_exceeded"
        allowed_evidence = {*request.evidence_refs, *gateway.evidence_refs}
        if not set(output.evidence_refs).issubset(allowed_evidence):
            return TaskWorkerStatus.DENIED, "unsupported_evidence"
        if detect_injection_markers(output.summary) or any(
            detect_injection_markers(caveat) for caveat in output.caveats
        ):
            return TaskWorkerStatus.DENIED, "unsafe_worker_output"
        if output.abstained:
            return TaskWorkerStatus.ABSTAINED, "worker_abstained"
        return TaskWorkerStatus.SUCCEEDED, "completed"

    @staticmethod
    def _terminal(
        request: TaskWorkerRequest,
        *,
        status: TaskWorkerStatus,
        reason: str,
        usage: TaskWorkerUsage,
        started_at: datetime,
        finished_at: datetime,
        output: TaskWorkerOutput | None = None,
    ) -> TaskWorkerResult:
        return TaskWorkerResult(
            worker_id=request.worker_id,
            parent_trace_ref=request.parent_trace_ref,
            status=status,
            summary=output.summary if output is not None else None,
            evidence_refs=output.evidence_refs if output is not None else (),
            caveats=output.caveats if output is not None else (),
            usage=usage,
            terminal_reason=reason,
            started_at=started_at,
            finished_at=finished_at,
        )


__all__ = [
    "TaskWorkerCancellationError",
    "TaskWorkerCompletionSink",
    "TaskWorkerExecutor",
    "TaskWorkerRuntime",
    "TaskWorkerRuntimeConfig",
]
