"""Durable execution backend coordination remains idempotent and fail-closed."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.execution_backend import (
    CancellationGuarantee,
    ExecutionBackendCoordinator,
    ExecutionBackendKind,
    ExecutionBackendProfile,
    ExecutionBackendProfileRegistry,
    ExecutionNetworkProfile,
    ExecutionProfileError,
    InMemoryExecutionSubmissionLedger,
    PersistenceMode,
    ResourceCeilings,
    WorkspaceMode,
)
from fdai.shared.providers.execution_backend import (
    ExecutionAttemptOperation,
    ExecutionBackendCapabilities,
    ExecutionBackendError,
    ExecutionBackendHealth,
    ExecutionBackendPlan,
    ExecutionBackendReceipt,
    ExecutionBackendRequest,
    ExecutionCleanupResult,
    ExecutionCleanupState,
    ExecutionHealthState,
    ExecutionOwnerTrace,
    ExecutionStatus,
)


class _Backend:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.status_calls = 0
        self.cancel_calls = 0
        self.cleanup_calls = 0
        self.submit_error = False
        self.status_error = False
        self.cancel_error = False
        self.submit_status = ExecutionStatus.SUBMITTED
        self.status_result = ExecutionStatus.RUNNING

    async def plan(self, request, *, profile):  # type: ignore[no-untyped-def]
        return ExecutionBackendPlan(
            plan_ref=f"plan:{request.idempotency_key}",
            backend_kind=profile.backend_kind.value,
            request=request,
            created_at=datetime(2026, 7, 21, tzinfo=UTC),
        )

    async def submit(self, plan: ExecutionBackendPlan) -> ExecutionBackendReceipt:
        self.submit_calls += 1
        if self.submit_error:
            raise RuntimeError("connection reset after send")
        return _receipt(self.submit_status)

    async def status(self, submission_ref: str) -> ExecutionBackendReceipt:
        self.status_calls += 1
        if self.status_error:
            raise LookupError("provider lost execution")
        return _receipt(self.status_result)

    async def cancel(self, submission_ref: str) -> ExecutionBackendReceipt:
        self.cancel_calls += 1
        if self.cancel_error:
            raise RuntimeError("cancel raced with completion")
        return _receipt(ExecutionStatus.CANCELLED)

    async def collect_receipt(self, submission_ref: str) -> ExecutionBackendReceipt:
        return _receipt(self.status_result, receipt_ref="receipt:final")

    async def cleanup(self, submission_ref: str) -> ExecutionCleanupResult:
        self.cleanup_calls += 1
        return ExecutionCleanupResult(
            state=ExecutionCleanupState.COMPLETED,
            detail="execution artifacts removed",
        )

    async def capabilities(self) -> ExecutionBackendCapabilities:
        return ExecutionBackendCapabilities(
            backend_kind=ExecutionBackendKind.VM_TASK.value,
            supports_status=True,
            supports_cancel=True,
            supports_receipt=True,
            supports_cleanup=True,
            durable_provider_state=True,
        )

    async def health(self) -> ExecutionBackendHealth:
        return ExecutionBackendHealth(
            state=ExecutionHealthState.HEALTHY,
            checked_at=datetime(2026, 7, 21, tzinfo=UTC),
            detail="ready",
        )


def _receipt(
    status: ExecutionStatus,
    *,
    receipt_ref: str = "receipt:run-1",
) -> ExecutionBackendReceipt:
    return ExecutionBackendReceipt(
        status=status,
        submission_ref="provider:run-1",
        receipt_ref=receipt_ref,
        detail=f"provider state: {status.value}",
    )


def _profile() -> ExecutionBackendProfile:
    return ExecutionBackendProfile(
        profile_id="vm.report",
        version="1.0.0",
        backend_kind=ExecutionBackendKind.VM_TASK,
        workload_ids=frozenset({"report.render"}),
        workspace_mode=WorkspaceMode.NONE,
        network_profiles=frozenset({ExecutionNetworkProfile.AZURE_CONTROL_PLANE}),
        credential_profile_refs=frozenset({"azure.executor"}),
        max_timeout_seconds=30,
        max_output_bytes=10_000,
        resources=ResourceCeilings(
            cpu_millis=1_000,
            memory_bytes=512_000_000,
            ephemeral_storage_bytes=1_000_000_000,
            max_concurrency=1,
        ),
        persistence_mode=PersistenceMode.DURABLE,
        regions=frozenset({"example-region"}),
        scope_refs=frozenset({"resource:vm:example"}),
        cancellation_guarantee=CancellationGuarantee.BEST_EFFORT,
    )


def _request() -> ExecutionBackendRequest:
    return ExecutionBackendRequest(
        workload_id="report.render",
        idempotency_key="event-1:report",
        artifact_digest="a" * 64,
        profile_id="vm.report",
        profile_version="1.0.0",
        owner_trace=ExecutionOwnerTrace(
            event_ref="event:1",
            action_ref="action:1",
            correlation_ref="trace:1",
        ),
        stop_condition="stop after the bounded task reaches a terminal state",
        audit_ref="audit:action:1",
        scope_ref="resource:vm:example",
        region="example-region",
        payload={"server_owned": True},
    )


def test_submission_owner_trace_cannot_move_execution_to_narrator() -> None:
    with pytest.raises(ValueError, match="Thor"):
        ExecutionOwnerTrace(
            event_ref="event:1",
            action_ref="action:1",
            correlation_ref="trace:1",
            executor_role="Bragi",
        )


def _service(
    backend: _Backend,
    ledger: InMemoryExecutionSubmissionLedger,
    *,
    enabled: bool = True,
    clock: Callable[[], datetime] = lambda: datetime(2026, 7, 21, tzinfo=UTC),
) -> ExecutionBackendCoordinator:
    registry = ExecutionBackendProfileRegistry(
        (_profile(),),
        enabled_profile_ids=(frozenset({"vm.report"}) if enabled else frozenset()),
    )
    return ExecutionBackendCoordinator(
        profiles=registry,
        backends={ExecutionBackendKind.VM_TASK: backend},
        ledger=ledger,
        clock=clock,
    )


async def test_duplicate_submit_after_restart_returns_ledger_receipt() -> None:
    backend = _Backend()
    ledger = InMemoryExecutionSubmissionLedger()

    first = await _service(backend, ledger).start(_request())
    second = await _service(backend, ledger).start(_request())

    assert first.status is ExecutionStatus.SUBMITTED
    assert second.already_existed is True
    assert backend.submit_calls == 1
    assert [item.operation for item in await ledger.attempts("event-1:report")] == [
        ExecutionAttemptOperation.SUBMIT
    ]


async def test_submit_transport_loss_is_recorded_as_ambiguous() -> None:
    backend = _Backend()
    backend.submit_error = True
    ledger = InMemoryExecutionSubmissionLedger()

    with pytest.raises(ExecutionBackendError, match="ambiguous"):
        await _service(backend, ledger).start(_request())

    record = await ledger.get("event-1:report")
    assert record is not None
    assert record.status is ExecutionStatus.AMBIGUOUS


async def test_timeout_requests_backend_cancellation() -> None:
    backend = _Backend()
    ledger = InMemoryExecutionSubmissionLedger()
    current = [datetime(2026, 7, 21, tzinfo=UTC)]
    service = _service(backend, ledger, clock=lambda: current[0])
    await service.start(_request())
    current[0] += timedelta(seconds=31)

    receipt = await service.reconcile("event-1:report")

    assert receipt.status is ExecutionStatus.CANCELLED
    assert backend.cancel_calls == 1
    assert backend.status_calls == 0


async def test_lost_provider_status_fails_closed_as_ambiguous() -> None:
    backend = _Backend()
    backend.status_error = True
    ledger = InMemoryExecutionSubmissionLedger()
    service = _service(backend, ledger)
    await service.start(_request())

    receipt = await service.reconcile("event-1:report")

    assert receipt.status is ExecutionStatus.AMBIGUOUS
    assert "unavailable" in receipt.detail


async def test_cancel_race_preserves_observed_success() -> None:
    backend = _Backend()
    backend.cancel_error = True
    backend.status_result = ExecutionStatus.SUCCEEDED
    ledger = InMemoryExecutionSubmissionLedger()
    service = _service(backend, ledger)
    await service.start(_request())

    receipt = await service.cancel("event-1:report")

    assert receipt.status is ExecutionStatus.SUCCEEDED
    assert backend.cancel_calls == 1
    assert backend.status_calls == 1


async def test_collect_receipt_and_cleanup_terminal_submission() -> None:
    backend = _Backend()
    backend.submit_status = ExecutionStatus.SUCCEEDED
    backend.status_result = ExecutionStatus.SUCCEEDED
    ledger = InMemoryExecutionSubmissionLedger()
    service = _service(backend, ledger)
    await service.start(_request())

    receipt = await service.collect_receipt("event-1:report")
    record = await service.cleanup("event-1:report")

    assert receipt.receipt_ref == "receipt:final"
    assert record.cleanup_state is ExecutionCleanupState.COMPLETED
    assert backend.cleanup_calls == 1


async def test_disabled_profile_allows_shadow_probe_but_not_submit() -> None:
    backend = _Backend()
    ledger = InMemoryExecutionSubmissionLedger()
    service = _service(backend, ledger, enabled=False)

    plan, capabilities, health = await service.shadow_probe(_request())

    assert plan.request == _request()
    assert capabilities.supports_status is True
    assert health.state is ExecutionHealthState.HEALTHY
    assert backend.submit_calls == 0
    with pytest.raises(ExecutionProfileError, match="disabled"):
        await service.start(_request())
