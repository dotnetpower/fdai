"""Attempt-aware retry admission for effect-free failed Workflow Processes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fdai.core.workflow.workflow_runtime import event_id
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.state_store import StateStore

_EFFECT_FREE_FAILURE_REASONS = frozenset(
    {
        "approval_provider_not_configured",
        "approval_rejected",
        "approval_requester_unavailable",
        "approval_timed_out",
        "enforce_action_dispatcher_not_configured",
        "gate_blocked",
        "guard_blocked_enforce",
        "invalid_decision_outcome",
        "parallel_branch_failed",
        "unknown_action_type",
        "unsupported_step_kind",
        "workflow_sensitive_params_unsupported",
    }
)


class WorkflowRetryError(RuntimeError):
    """A Process cannot start a new attempt from its durable evidence."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True, slots=True)
class WorkflowRetryRequest:
    snapshot: ProcessSnapshot
    attempt: int
    replayed: bool = False


class WorkflowRetryCoordinator:
    """Admit only a failed attempt that has no authority-bearing side effects."""

    def __init__(
        self,
        *,
        process_store: ProcessRuntimeStore,
        audit_store: StateStore,
    ) -> None:
        self._process_store = process_store
        self._audit_store = audit_store

    async def request(
        self,
        *,
        snapshot: ProcessSnapshot,
        actor_oid: str,
        requested_at: datetime,
        max_attempts: int = 3,
    ) -> WorkflowRetryRequest:
        if max_attempts < 1:
            raise ValueError("max_attempts MUST be >= 1")
        events = await self._process_store.events(snapshot.process_id)
        active_retry = _active_retry(events, snapshot)
        if active_retry is not None:
            return WorkflowRetryRequest(
                snapshot=snapshot,
                attempt=active_retry.attempt,
                replayed=True,
            )
        if snapshot.status not in {ProcessStatus.FAILED, ProcessStatus.TIMED_OUT}:
            raise WorkflowRetryError(
                "process_not_retryable",
                f"Process in {snapshot.status.value!r} state cannot start a retry",
            )
        terminal = next(
            (
                event
                for event in reversed(events)
                if event.kind
                in {ProcessEventKind.PROCESS_FAILED, ProcessEventKind.PROCESS_TIMED_OUT}
            ),
            None,
        )
        if terminal is None:
            raise WorkflowRetryError(
                "retry_evidence_unavailable",
                "Failed Process has no terminal failure evidence",
            )
        failed_attempt = terminal.attempt
        if failed_attempt >= max_attempts:
            raise WorkflowRetryError(
                "retry_attempt_limit",
                f"Process reached the retry attempt limit of {max_attempts}",
            )
        attempt_events = tuple(event for event in events if event.attempt == failed_attempt)
        blocked = {
            ProcessEventKind.ACTION_DISPATCHED,
            ProcessEventKind.COMPENSATION_STARTED,
            ProcessEventKind.COMPENSATION_DISPATCHED,
            ProcessEventKind.PROCESS_CANCELLATION_REQUESTED,
        }
        if any(event.kind in blocked for event in attempt_events):
            raise WorkflowRetryError(
                "retry_requires_recovery",
                "Failed attempt has dispatch, approval, cancellation, or compensation evidence",
            )
        failed_step = next(
            (
                event
                for event in reversed(attempt_events)
                if event.kind in {ProcessEventKind.STEP_FAILED, ProcessEventKind.PROCESS_TIMED_OUT}
                and event.step_id is not None
            ),
            None,
        )
        if failed_step is None:
            raise WorkflowRetryError(
                "retry_evidence_unavailable",
                "Failed Process has no retryable step failure evidence",
            )
        failure_reason = str(failed_step.payload.get("reason") or "")
        has_approval_request = any(
            event.kind is ProcessEventKind.APPROVAL_REQUESTED for event in attempt_events
        )
        if has_approval_request and failure_reason not in {
            "approval_rejected",
            "approval_timed_out",
        }:
            raise WorkflowRetryError(
                "retry_requires_recovery",
                "Approval evidence is not a terminal rejection or timeout",
            )
        if failure_reason not in _EFFECT_FREE_FAILURE_REASONS:
            raise WorkflowRetryError(
                "retry_requires_recovery",
                "Failed step does not prove an effect-free retry boundary",
            )
        actor = actor_oid.strip()
        if not actor:
            raise WorkflowRetryError(
                "retry_actor_unavailable",
                "Process retry requires an authenticated actor",
            )
        attempt = failed_attempt + 1
        await self._audit_store.append_audit_entry(
            {
                "event_id": event_id(
                    snapshot.process_id,
                    f"attempt:{attempt}:retry-requested:audit",
                ),
                "correlation_id": snapshot.correlation_id,
                "actor": actor,
                "action_kind": "workflow.process.retry-requested",
                "process_id": snapshot.process_id,
                "step_id": failed_step.step_id,
                "attempt": attempt,
                "causation_id": terminal.event_id,
                "recorded_at": requested_at.isoformat(),
            }
        )
        retried = await self._process_store.transition(
            process_id=snapshot.process_id,
            expected_revision=snapshot.revision,
            status=ProcessStatus.PENDING,
            current_step=failed_step.step_id or "",
            event=ProcessEvent(
                event_id=event_id(snapshot.process_id, f"attempt:{attempt}:retry-requested"),
                process_id=snapshot.process_id,
                kind=ProcessEventKind.PROCESS_RETRY_REQUESTED,
                idempotency_key=(
                    f"{snapshot.process_id}:retry:{terminal.event_id}:attempt:{attempt}"
                ),
                recorded_at=requested_at,
                correlation_id=snapshot.correlation_id,
                causation_id=terminal.event_id,
                step_id=failed_step.step_id,
                attempt=attempt,
                payload={"actor_oid": actor, "failed_attempt": failed_attempt},
            ),
        )
        return WorkflowRetryRequest(snapshot=retried, attempt=attempt)


def _active_retry(
    events: tuple[ProcessEvent, ...],
    snapshot: ProcessSnapshot,
) -> ProcessEvent | None:
    if snapshot.status not in {
        ProcessStatus.PENDING,
        ProcessStatus.RUNNING,
        ProcessStatus.WAITING,
        ProcessStatus.COMPENSATING,
    }:
        return None
    retry = next(
        (
            event
            for event in reversed(events)
            if event.kind is ProcessEventKind.PROCESS_RETRY_REQUESTED
        ),
        None,
    )
    if retry is None:
        return None
    terminal_attempts = {
        event.attempt
        for event in events
        if event.kind
        in {
            ProcessEventKind.PROCESS_COMPLETED,
            ProcessEventKind.PROCESS_FAILED,
            ProcessEventKind.PROCESS_CANCELLED,
            ProcessEventKind.PROCESS_TIMED_OUT,
            ProcessEventKind.COMPENSATION_COMPLETED,
        }
    }
    return None if retry.attempt in terminal_attempts else retry


__all__ = ["WorkflowRetryCoordinator", "WorkflowRetryError", "WorkflowRetryRequest"]
