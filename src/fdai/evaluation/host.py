"""Concrete FDAI implementation of the public evaluation host SPI."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from fdai_evaluation_sdk import (
    EVALUATION_API_VERSION,
    ArtifactRef,
    ArtifactSpec,
    AuthorityCeiling,
    DecisionReceipt,
    EvaluationRequest,
    EvaluationResult,
    EvaluationStatus,
    EvaluationTask,
    ExternalValidationReceipt,
    QualityGateStatus,
    SideEffectClass,
)

from fdai.core.control_loop import ControlLoopOutcome, ControlLoopResult
from fdai.core.tiers.t2_reasoning import T2Outcome
from fdai.evaluation.artifacts import InMemoryArtifactBroker
from fdai.evaluation.capabilities import (
    AuthorityAxes,
    CapabilityAxes,
    EffectiveCapabilities,
    attenuate_authority,
    attenuate_capabilities,
)
from fdai.evaluation.outputs import (
    EvaluationOutputCollector,
    NoopEvaluationOutputCollector,
    collect_verified_outputs,
)
from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode


class EvaluationHostError(RuntimeError):
    """Evaluation session negotiation or lifecycle failed closed."""


class EventProcessor(Protocol):
    """Typed ingress owned by the FDAI host implementation."""

    async def process(self, event: Event | Mapping[str, Any]) -> ControlLoopResult: ...


class ExternalValidationSink(Protocol):
    """Append-only sink for untrusted benchmark validation evidence."""

    async def append(self, receipt: ExternalValidationReceipt) -> None: ...


class InMemoryExternalValidationSink:
    def __init__(self) -> None:
        self.receipts: list[ExternalValidationReceipt] = []
        self._lock = asyncio.Lock()

    async def append(self, receipt: ExternalValidationReceipt) -> None:
        async with self._lock:
            self.receipts.append(receipt)


@dataclass(frozen=True, slots=True)
class EvaluationHostPolicy:
    """Server-owned ceilings used to negotiate every session."""

    capability_catalog: Mapping[str, SideEffectClass]
    capability_axes: CapabilityAxes
    authority_axes: AuthorityAxes
    max_tasks: int = 1_000
    max_concurrency: int = 16

    def __post_init__(self) -> None:
        if self.max_tasks < 1 or self.max_concurrency < 1:
            raise ValueError("host task and concurrency limits MUST be positive")


class FdaiEvaluationHost:
    """Open only sessions whose complete requested envelope can be satisfied."""

    def __init__(
        self,
        *,
        processor: EventProcessor,
        artifact_broker: InMemoryArtifactBroker,
        validation_sink: ExternalValidationSink,
        policy: EvaluationHostPolicy,
        output_collector: EvaluationOutputCollector | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._processor = processor
        self._artifact_broker = artifact_broker
        self._validation_sink = validation_sink
        self._output_collector = output_collector or NoopEvaluationOutputCollector()
        self._policy = policy
        self._clock = clock or (lambda: datetime.now(UTC))
        self._session_registry_lock = asyncio.Lock()
        self._open_session_ids: set[str] = set()
        self._closed_session_tasks: dict[str, frozenset[str]] = {}
        self._validation_receipts: dict[tuple[str, str], ExternalValidationReceipt] = {}

    @property
    def api_version(self) -> str:
        return EVALUATION_API_VERSION

    async def open(self, request: EvaluationRequest) -> FdaiEvaluationSession:
        """Negotiate a complete session envelope or reject it without partial state."""

        now = self._clock()
        if request.deadline <= now:
            raise EvaluationHostError("evaluation request deadline has expired")
        if request.task_count_limit > self._policy.max_tasks:
            raise EvaluationHostError("evaluation task count exceeds the host limit")
        if request.concurrency_limit > self._policy.max_concurrency:
            raise EvaluationHostError("evaluation concurrency exceeds the host limit")
        capabilities = attenuate_capabilities(
            requested=request.requested_capabilities,
            catalog=self._policy.capability_catalog,
            axes=self._policy.capability_axes,
        )
        if capabilities.denied:
            raise EvaluationHostError(
                "evaluation capabilities cannot be satisfied: " + ", ".join(capabilities.denied)
            )
        authority = attenuate_authority(
            request.authority_ceiling,
            axes=self._policy.authority_axes,
        )
        async with self._session_registry_lock:
            if (
                request.session_id in self._open_session_ids
                or request.session_id in self._closed_session_tasks
            ):
                raise EvaluationHostError("evaluation session id has already been used")
            self._open_session_ids.add(request.session_id)
        return FdaiEvaluationSession(
            request=request,
            effective_capabilities=capabilities,
            effective_authority=authority,
            processor=self._processor,
            artifact_broker=self._artifact_broker,
            validation_sink=self._validation_sink,
            output_collector=self._output_collector,
            clock=self._clock,
            close_observer=self._record_closed_session,
        )

    async def record_external_validation(self, receipt: ExternalValidationReceipt) -> None:
        """Record post-session benchmark evidence without granting execution authority."""

        key = (receipt.session_id, receipt.task_id)
        async with self._session_registry_lock:
            tasks = self._closed_session_tasks.get(receipt.session_id)
            if tasks is None or receipt.task_id not in tasks:
                raise EvaluationHostError(
                    "external validation does not match a closed accepted task"
                )
            if any(
                stage.receipt_ref.session_id != receipt.session_id
                or stage.receipt_ref.task_id != receipt.task_id
                or stage.receipt_ref.expires_at <= self._clock()
                for stage in receipt.stages
            ):
                raise EvaluationHostError(
                    "external validation contains expired or cross-task evidence"
                )
            existing = self._validation_receipts.get(key)
            if existing is not None:
                if existing != receipt:
                    raise EvaluationHostError(
                        "external validation conflicts with the recorded receipt"
                    )
                return
            await self._validation_sink.append(receipt)
            self._validation_receipts[key] = receipt

    async def _record_closed_session(
        self,
        session_id: str,
        task_ids: frozenset[str],
    ) -> None:
        async with self._session_registry_lock:
            self._open_session_ids.discard(session_id)
            self._closed_session_tasks[session_id] = task_ids


class FdaiEvaluationSession:
    """Bounded session that exposes no FDAI runtime implementation object."""

    def __init__(
        self,
        *,
        request: EvaluationRequest,
        effective_capabilities: EffectiveCapabilities,
        effective_authority: AuthorityCeiling,
        processor: EventProcessor,
        artifact_broker: InMemoryArtifactBroker,
        validation_sink: ExternalValidationSink,
        output_collector: EvaluationOutputCollector,
        clock: Callable[[], datetime],
        close_observer: Callable[[str, frozenset[str]], Awaitable[None]],
    ) -> None:
        self._request = request
        self._effective_capabilities = effective_capabilities
        self._effective_authority = effective_authority
        self._processor = processor
        self._artifact_broker = artifact_broker
        self._validation_sink = validation_sink
        self._output_collector = output_collector
        self._clock = clock
        self._close_observer = close_observer
        self._results: dict[str, tuple[str, EvaluationResult]] = {}
        self._tasks: dict[str, EvaluationTask] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._closed = False
        self._inflight = 0
        self._state_lock = asyncio.Lock()
        self._idle = asyncio.Condition(self._state_lock)

    @property
    def session_id(self) -> str:
        return self._request.session_id

    async def execute(self, task: EvaluationTask) -> EvaluationResult:
        """Process one task through FDAI ingress and return a correlated terminal result."""

        fingerprint = _task_fingerprint(task)
        task_lock = self._locks.setdefault(task.task_id, asyncio.Lock())
        async with task_lock:
            cached = self._results.get(task.task_id)
            if cached is not None:
                if cached[0] != fingerprint:
                    raise EvaluationHostError("evaluation task id conflicts with prior content")
                return cached[1]
            async with self._state_lock:
                self._validate_task(task)
                if self._inflight >= self._request.concurrency_limit:
                    raise EvaluationHostError("evaluation session concurrency limit exceeded")
                self._inflight += 1
                self._tasks[task.task_id] = task
            try:
                event = self._event_for(task, fingerprint)
                loop_result = await self._processor.process(event)
                completed = loop_result.outcome is ControlLoopOutcome.EXECUTED
                outputs = await collect_verified_outputs(
                    task=task,
                    control_result=loop_result,
                    collector=self._output_collector,
                    artifact_broker=self._artifact_broker,
                    clock=self._clock,
                    require_all=completed,
                )
                result = _evaluation_result(
                    task,
                    event,
                    loop_result,
                    self._effective_authority,
                    output_artifacts=outputs,
                )
                self._results[task.task_id] = (fingerprint, result)
                return result
            finally:
                await self._leave_operation()

    async def publish_artifact(
        self,
        *,
        task_id: str,
        spec: ArtifactSpec,
        chunks: AsyncIterable[bytes],
    ) -> ArtifactRef:
        """Publish only an output declared by a task already accepted by the session."""

        await self._enter_operation()
        try:
            task = self._tasks.get(task_id)
            if task is None:
                raise EvaluationHostError("artifact task has not been accepted by the session")
            return await self._artifact_broker.publish(
                session_id=self.session_id,
                task_id=task_id,
                spec=spec,
                declared_outputs=task.expected_outputs,
                chunks=chunks,
                policy=self._request.artifact_policy,
                ttl_seconds=spec.ttl_seconds,
            )
        finally:
            await self._leave_operation()

    def read_artifact(self, artifact: ArtifactRef) -> AsyncIterator[bytes]:
        return self._read_artifact(artifact)

    async def record_external_validation(self, receipt: ExternalValidationReceipt) -> None:
        """Record validation as untrusted evidence without changing session authority."""

        await self._enter_operation()
        try:
            if receipt.session_id != self.session_id or receipt.task_id not in self._tasks:
                raise EvaluationHostError("external validation does not match an accepted task")
            if any(
                stage.receipt_ref.session_id != self.session_id
                or stage.receipt_ref.task_id != receipt.task_id
                or stage.receipt_ref.expires_at <= self._clock()
                for stage in receipt.stages
            ):
                raise EvaluationHostError(
                    "external validation contains expired or cross-task evidence"
                )
            await self._validation_sink.append(receipt)
        finally:
            await self._leave_operation()

    async def close(self) -> None:
        """Idempotently close the session and remove all task-scoped artifacts."""

        async with self._idle:
            if self._closed:
                return
            self._closed = True
            while self._inflight:
                await self._idle.wait()
        await self._artifact_broker.cleanup_session(self.session_id)
        await self._close_observer(self.session_id, frozenset(self._tasks))

    async def _read_artifact(self, artifact: ArtifactRef) -> AsyncIterator[bytes]:
        await self._enter_operation()
        try:
            async for chunk in self._artifact_broker.read(
                session_id=self.session_id,
                artifact=artifact,
            ):
                yield chunk
        finally:
            await self._leave_operation()

    async def _enter_operation(self) -> None:
        async with self._state_lock:
            self._ensure_open()
            self._inflight += 1

    async def _leave_operation(self) -> None:
        async with self._idle:
            self._inflight -= 1
            if self._inflight == 0:
                self._idle.notify_all()

    def _validate_task(self, task: EvaluationTask) -> None:
        self._ensure_open()
        now = self._clock()
        if task.session_id != self.session_id:
            raise EvaluationHostError("evaluation task belongs to another session")
        if len(self._tasks) >= self._request.task_count_limit:
            raise EvaluationHostError("evaluation session task count limit exceeded")
        if task.deadline > self._request.deadline or task.deadline <= now:
            raise EvaluationHostError("evaluation task deadline is outside the session envelope")
        requested = frozenset(item.capability_id for item in task.requested_capabilities)
        if not requested <= self._effective_capabilities.allowed_ids:
            raise EvaluationHostError("evaluation task requests unavailable capabilities")
        if any(item.expires_at <= now for item in task.input_artifacts):
            raise EvaluationHostError("evaluation task contains an expired input artifact")

    def _event_for(self, task: EvaluationTask, fingerprint: str) -> Event:
        observed_at = self._clock()
        event_id = uuid5(NAMESPACE_URL, f"fdai:evaluation:{self.session_id}:{fingerprint}")
        return Event(
            schema_version="1.0.0",
            event_id=event_id,
            idempotency_key=f"evaluation:{fingerprint}",
            correlation_id=task.correlation_key or self.session_id,
            source="evaluation.host",
            event_type="evaluation.task.requested",
            resource_ref=f"{task.target.kind}/{task.target.value}",
            payload={
                "session_id": self.session_id,
                "task_id": task.task_id,
                "phase": task.phase,
                "objective": task.objective,
                "input_artifact_refs": [item.artifact_id for item in task.input_artifacts],
                "expected_outputs": [
                    item.model_dump(mode="json") for item in task.expected_outputs
                ],
                "capabilities": sorted(item.capability_id for item in task.requested_capabilities),
                "metadata": {item.key: item.value for item in task.metadata},
            },
            detected_at=observed_at,
            ingested_at=observed_at,
            incident_correlation=IncidentCorrelation.NONE,
            mode=(
                Mode.ENFORCE
                if self._effective_authority is AuthorityCeiling.ENFORCE
                else Mode.SHADOW
            ),
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise EvaluationHostError("evaluation session is closed")


def _task_fingerprint(task: EvaluationTask) -> str:
    encoded = json.dumps(
        task.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _evaluation_result(
    task: EvaluationTask,
    event: Event,
    result: ControlLoopResult,
    authority: AuthorityCeiling,
    *,
    output_artifacts: tuple[ArtifactRef, ...],
) -> EvaluationResult:
    completed = result.outcome is ControlLoopOutcome.EXECUTED
    status = EvaluationStatus.COMPLETED if completed else EvaluationStatus.HELD
    action_refs = tuple(item.action_id for item in result.execution_results)
    rollback_refs = tuple(
        reference
        for item in result.execution_results
        if (reference := _rollback_reference(item)) is not None
    )
    quality_status, verifier_passed = _quality_status(result)
    return EvaluationResult(
        session_id=task.session_id,
        task_id=task.task_id,
        phase=task.phase,
        status=status,
        summary=_summary(result),
        output_artifacts=output_artifacts,
        evidence_refs=tuple(f"rule/{item}" for item in result.citing_rule_ids),
        terminal_audit_ref=f"event/{event.event_id}",
        decision_receipt=DecisionReceipt(
            selected_tier=result.tier,
            control_loop_outcome=result.outcome.value,
            decision=result.decision,
            autonomy_mode=authority,
            cited_rule_refs=tuple(f"rule/{item}" for item in result.citing_rule_ids),
            action_refs=action_refs,
            rollback_refs=rollback_refs,
            verifier_passed=verifier_passed,
            quality_gate_status=quality_status,
            authority_ceiling=authority,
        ),
        reason_code=None if completed else result.outcome.value,
    )


def _quality_status(result: ControlLoopResult) -> tuple[QualityGateStatus, bool]:
    if result.t2_decision is None:
        return QualityGateStatus.NOT_REQUIRED, result.tier != "t2"
    passed = result.t2_decision.outcome is T2Outcome.PROPOSED
    return (QualityGateStatus.PASSED if passed else QualityGateStatus.FAILED), passed


def _rollback_reference(item: object) -> str | None:
    value = getattr(item, "audit_context", {}).get("rollback_reference")
    return value if isinstance(value, str) and value else None


def _summary(result: ControlLoopResult) -> str:
    detail = result.reason or result.decision
    return (
        f"FDAI outcome={result.outcome.value}; tier={result.tier}; "
        f"decision={result.decision}; detail={detail}"
    )


__all__ = [
    "EvaluationHostError",
    "EvaluationHostPolicy",
    "ExternalValidationSink",
    "FdaiEvaluationHost",
    "FdaiEvaluationSession",
    "InMemoryExternalValidationSink",
]
