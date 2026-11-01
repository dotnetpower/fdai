"""Durable detached-session completion delivery adapter for bounded task workers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from fdai.core.task_worker.models import (
    TERMINAL_WORKER_STATUSES,
    TaskWorkerResult,
    TaskWorkerStatus,
)
from fdai.core.task_worker.store import TaskWorkerStore

COMPLETION_FAILURE_EVENT_KIND = "worker.completion_delivery_failed"


@dataclass(frozen=True, slots=True)
class DetachedWorkerCompletionEnvelope:
    """Bounded, untrusted completion record delivered to the detached-session reply path."""

    delivery_id: str
    idempotency_key: str
    worker_id: str
    parent_trace_ref: str
    status: str
    summary: str | None
    evidence_refs: tuple[str, ...]
    caveats: tuple[str, ...]
    usage: dict[str, int | bool]
    terminal_reason: str
    started_at: str
    finished_at: str
    trusted: Literal[False] = False
    execution_authority: Literal["none"] = "none"

    def __post_init__(self) -> None:
        if not self.delivery_id.strip() or not self.idempotency_key.strip():
            raise ValueError("delivery_id and idempotency_key MUST be non-empty")
        if (
            not self.worker_id.strip()
            or not self.parent_trace_ref.strip()
            or any(ord(ch) < 32 for ch in self.worker_id)
            or any(ord(ch) < 32 for ch in self.parent_trace_ref)
        ):
            raise ValueError("worker_id and parent_trace_ref MUST be non-empty printable strings")
        if self.trusted is not False:
            raise ValueError("detached worker completion envelope MUST remain untrusted")
        if self.execution_authority != "none":
            raise ValueError("detached worker completion envelope grants no execution authority")


@dataclass(frozen=True, slots=True)
class DetachedWorkerCompletionReceipt:
    """Outcome of one detached-session completion delivery attempt."""

    delivery_id: str
    worker_id: str
    parent_trace_ref: str
    delivered: bool
    duplicate: bool = False
    error_kind: str | None = None
    recorded_at: datetime | None = None


class DetachedSessionReplySink(Protocol):
    """Downstream detached-session reply ledger or channel sink."""

    async def deliver_worker_completion(
        self, envelope: DetachedWorkerCompletionEnvelope
    ) -> None: ...


class InMemoryDetachedSessionReplyLedger:
    """Idempotent detached-session reply ledger keyed by worker_id."""

    def __init__(self) -> None:
        self._delivered: dict[str, DetachedWorkerCompletionEnvelope] = {}

    async def deliver_worker_completion(self, envelope: DetachedWorkerCompletionEnvelope) -> None:
        existing = self._delivered.get(envelope.worker_id)
        if existing is not None and existing != envelope:
            raise ValueError("worker completion idempotency conflict")
        self._delivered[envelope.worker_id] = envelope

    def get(self, worker_id: str) -> DetachedWorkerCompletionEnvelope | None:
        return self._delivered.get(worker_id)

    def list_delivered(self) -> tuple[DetachedWorkerCompletionEnvelope, ...]:
        return tuple(self._delivered.values())


class DetachedSessionTaskWorkerCompletionSink:
    """Deliver terminal worker results once without rewriting or rerunning terminal state.

    When attached to ``TaskWorkerRuntime(completion_sink=...)`` without an explicit ``store``,
    ``publish()`` re-raises sink errors so ``TaskWorkerRuntime._finish`` appends the
    ``worker.completion_delivery_failed`` event to its own store. When ``store`` is provided
    directly to this adapter, ``deliver()`` and ``publish()`` append the failure event to
    ``store`` directly while preserving the terminal ``TaskWorkerResult`` unchanged.
    """

    def __init__(
        self,
        *,
        reply_sink: DetachedSessionReplySink,
        store: TaskWorkerStore | None = None,
    ) -> None:
        self._reply_sink = reply_sink
        self._store = store
        self._receipts: dict[str, DetachedWorkerCompletionReceipt] = {}

    @property
    def delivered_count(self) -> int:
        return sum(1 for item in self._receipts.values() if item.delivered)

    async def publish(self, result: TaskWorkerResult) -> None:
        """TaskWorkerCompletionSink entrypoint invoked after atomic terminal persistence."""
        receipt = await self.deliver(result, reraise_when_unmanaged=self._store is None)
        del receipt

    async def deliver(
        self,
        result: TaskWorkerResult,
        *,
        reraise_when_unmanaged: bool = False,
    ) -> DetachedWorkerCompletionReceipt:
        """Deliver one terminal worker result idempotently and record sink failures safely."""
        if result.status not in TERMINAL_WORKER_STATUSES:
            raise ValueError("only terminal TaskWorkerResult records can be delivered")
        if result.trusted:
            raise ValueError("task worker results MUST remain untrusted")

        prior = self._receipts.get(result.worker_id)
        envelope = _build_envelope(result)
        if prior is not None and prior.delivered:
            if prior.delivery_id != envelope.delivery_id:
                raise ValueError("conflicting terminal worker result replay for worker_id")
            return DetachedWorkerCompletionReceipt(
                delivery_id=prior.delivery_id,
                worker_id=prior.worker_id,
                parent_trace_ref=prior.parent_trace_ref,
                delivered=True,
                duplicate=True,
                recorded_at=prior.recorded_at,
            )
        try:
            await self._reply_sink.deliver_worker_completion(envelope)
        except Exception as exc:  # noqa: BLE001 - sink failure must never rewrite terminal state
            error_kind = type(exc).__name__[:128]
            if self._store is not None:
                await self._store.append_event(
                    result.worker_id,
                    kind=COMPLETION_FAILURE_EVENT_KIND,
                    at=result.finished_at,
                    details=(("error", error_kind),),
                )
            failed_receipt = DetachedWorkerCompletionReceipt(
                delivery_id=envelope.delivery_id,
                worker_id=result.worker_id,
                parent_trace_ref=result.parent_trace_ref,
                delivered=False,
                duplicate=False,
                error_kind=error_kind,
                recorded_at=result.finished_at,
            )
            self._receipts[result.worker_id] = failed_receipt
            if reraise_when_unmanaged:
                raise
            return failed_receipt

        receipt = DetachedWorkerCompletionReceipt(
            delivery_id=envelope.delivery_id,
            worker_id=result.worker_id,
            parent_trace_ref=result.parent_trace_ref,
            delivered=True,
            duplicate=False,
            recorded_at=result.finished_at,
        )
        self._receipts[result.worker_id] = receipt
        return receipt

    def get_receipt(self, worker_id: str) -> DetachedWorkerCompletionReceipt | None:
        return self._receipts.get(worker_id)


def _build_envelope(result: TaskWorkerResult) -> DetachedWorkerCompletionEnvelope:
    safe_summary = (
        result.summary
        if result.status in {TaskWorkerStatus.SUCCEEDED, TaskWorkerStatus.ABSTAINED}
        else None
    )
    delivery_id = f"worker-completion:{result.worker_id}"
    return DetachedWorkerCompletionEnvelope(
        delivery_id=delivery_id,
        idempotency_key=f"{delivery_id}:{result.status.value}:{result.terminal_reason}",
        worker_id=result.worker_id,
        parent_trace_ref=result.parent_trace_ref,
        status=result.status.value,
        summary=safe_summary,
        evidence_refs=result.evidence_refs,
        caveats=result.caveats,
        usage=result.usage.to_dict(),
        terminal_reason=result.terminal_reason,
        started_at=result.started_at.isoformat(),
        finished_at=result.finished_at.isoformat(),
    )


TaskWorkerCompletionSink = DetachedSessionTaskWorkerCompletionSink
CompletionSinkDeliveryReceipt = DetachedWorkerCompletionReceipt

__all__ = [
    "COMPLETION_FAILURE_EVENT_KIND",
    "CompletionSinkDeliveryReceipt",
    "DetachedSessionReplySink",
    "DetachedSessionTaskWorkerCompletionSink",
    "DetachedWorkerCompletionEnvelope",
    "DetachedWorkerCompletionReceipt",
    "InMemoryDetachedSessionReplyLedger",
    "TaskWorkerCompletionSink",
]
