"""Bubblewrap and governed VM-task adapters for the ExecutionBackend protocol.

Both adapters wrap an already-authoritative sandbox catalog. They call the
catalog's existing `constrain` first, then apply `intersect_execution_profile`,
so a backend profile can only narrow the validated authority. Neither adapter
can add a command, credential, network path, writable workspace, resource
allowance, region, or scope; a widening attempt fails before provider I/O
(``docs/roadmap/interfaces/execution-backends.md``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from fdai.core.execution_backend.profiles import (
    ExecutionAuthority,
    ExecutionBackendKind,
    ExecutionBackendProfile,
    intersect_execution_profile,
)
from fdai.core.sandbox.profiles import SandboxProfileCatalog, VmTaskSandboxCatalog
from fdai.shared.providers.command_runner import (
    CommandPlan,
    CommandRunner,
    CommandStatus,
)
from fdai.shared.providers.execution_backend import (
    ExecutionBackendCapabilities,
    ExecutionBackendError,
    ExecutionBackendHealth,
    ExecutionBackendPlan,
    ExecutionBackendReceipt,
    ExecutionBackendRequest,
    ExecutionCleanupResult,
    ExecutionCleanupState,
    ExecutionHealthState,
    ExecutionStatus,
)
from fdai.shared.providers.vm_task import (
    VmTaskReceipt,
    VmTaskRequest,
    VmTaskRunner,
    VmTaskRunnerError,
    VmTaskStatus,
)

_COMMAND_STATUS: dict[CommandStatus, ExecutionStatus] = {
    CommandStatus.PLANNED: ExecutionStatus.SUBMITTED,
    CommandStatus.SUCCEEDED: ExecutionStatus.SUCCEEDED,
    CommandStatus.ALREADY_APPLIED: ExecutionStatus.SUCCEEDED,
    CommandStatus.FAILED: ExecutionStatus.FAILED,
    CommandStatus.STOPPED: ExecutionStatus.CANCELLED,
}

_VM_STATUS: dict[VmTaskStatus, ExecutionStatus] = {
    VmTaskStatus.PLANNED: ExecutionStatus.SUBMITTED,
    VmTaskStatus.SUBMITTED: ExecutionStatus.SUBMITTED,
    VmTaskStatus.RUNNING: ExecutionStatus.RUNNING,
    VmTaskStatus.SUCCEEDED: ExecutionStatus.SUCCEEDED,
    VmTaskStatus.FAILED: ExecutionStatus.FAILED,
    VmTaskStatus.CANCELLED: ExecutionStatus.CANCELLED,
}


def _now() -> datetime:
    return datetime.now(tz=UTC)


class BubblewrapExecutionBackend:
    """Run one offline, credential-free, read-only command plan locally.

    Submit returns only after the local process is terminal, so the process
    timeout remains the cancellation mechanism: an explicit cancel is rejected
    rather than reported as a guarantee the adapter cannot make.
    """

    backend_kind = ExecutionBackendKind.BUBBLEWRAP

    def __init__(
        self,
        *,
        catalog: SandboxProfileCatalog,
        runner: CommandRunner,
        authority: ExecutionAuthority,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        if authority.backend_kind is not ExecutionBackendKind.BUBBLEWRAP:
            raise ValueError("bubblewrap authority MUST declare the bubblewrap backend")
        self._catalog = catalog
        self._runner = runner
        self._authority = authority
        self._clock = clock
        self._plans: dict[str, CommandPlan] = {}
        self._receipts: dict[str, ExecutionBackendReceipt] = {}

    async def plan(
        self,
        request: ExecutionBackendRequest,
        *,
        profile: ExecutionBackendProfile,
    ) -> ExecutionBackendPlan:
        narrowed = self._narrow(request, profile)
        self._plans[request.idempotency_key] = narrowed
        return ExecutionBackendPlan(
            plan_ref=request.idempotency_key,
            backend_kind=self.backend_kind.value,
            request=request,
            created_at=self._clock(),
        )

    async def submit(self, plan: ExecutionBackendPlan) -> ExecutionBackendReceipt:
        command = self._plans.get(plan.plan_ref)
        if command is None:
            raise ExecutionBackendError("bubblewrap submit requires a planned command")
        existing = self._receipts.get(plan.plan_ref)
        if existing is not None:
            return replace(existing, already_existed=True)
        receipt = await self._runner.execute(command)
        result = ExecutionBackendReceipt(
            status=_COMMAND_STATUS[receipt.status],
            submission_ref=plan.plan_ref,
            receipt_ref=receipt.receipt_ref,
            detail=f"exit_code={receipt.exit_code}",
        )
        self._receipts[plan.plan_ref] = result
        return result

    async def status(self, submission_ref: str) -> ExecutionBackendReceipt:
        return self._terminal(submission_ref)

    async def cancel(self, submission_ref: str) -> ExecutionBackendReceipt:
        raise ExecutionBackendError(
            "bubblewrap submissions are terminal on return; the process timeout "
            "is the only cancellation mechanism"
        )

    async def collect_receipt(self, submission_ref: str) -> ExecutionBackendReceipt:
        return self._terminal(submission_ref)

    async def cleanup(self, submission_ref: str) -> ExecutionCleanupResult:
        self._plans.pop(submission_ref, None)
        self._receipts.pop(submission_ref, None)
        return ExecutionCleanupResult(
            state=ExecutionCleanupState.COMPLETED,
            detail="local workspace released",
        )

    async def capabilities(self) -> ExecutionBackendCapabilities:
        return ExecutionBackendCapabilities(
            backend_kind=self.backend_kind.value,
            supports_status=True,
            supports_cancel=False,
            supports_receipt=True,
            supports_cleanup=True,
            durable_provider_state=False,
        )

    async def health(self) -> ExecutionBackendHealth:
        return ExecutionBackendHealth(
            state=ExecutionHealthState.HEALTHY,
            checked_at=self._clock(),
            detail="local sandbox runner bound",
        )

    def _narrow(
        self,
        request: ExecutionBackendRequest,
        profile: ExecutionBackendProfile,
    ) -> CommandPlan:
        if not isinstance(request.payload, CommandPlan):
            raise ExecutionBackendError("bubblewrap requests MUST carry a CommandPlan payload")
        constrained = self._catalog.constrain(request.payload)
        narrowed_profile = intersect_execution_profile(self._authority, profile)
        return replace(
            constrained,
            timeout_seconds=min(constrained.timeout_seconds, narrowed_profile.max_timeout_seconds),
            max_output_bytes=min(constrained.max_output_bytes, narrowed_profile.max_output_bytes),
        )

    def _terminal(self, submission_ref: str) -> ExecutionBackendReceipt:
        receipt = self._receipts.get(submission_ref)
        if receipt is None:
            raise ExecutionBackendError("bubblewrap submission is unknown to this process")
        return receipt


class VmTaskExecutionBackend:
    """Run one content-addressed Python task through the governed VM runner."""

    backend_kind = ExecutionBackendKind.VM_TASK

    def __init__(
        self,
        *,
        catalog: VmTaskSandboxCatalog,
        runner: VmTaskRunner,
        authority: ExecutionAuthority,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        if authority.backend_kind is not ExecutionBackendKind.VM_TASK:
            raise ValueError("vm-task authority MUST declare the vm_task backend")
        self._catalog = catalog
        self._runner = runner
        self._authority = authority
        self._clock = clock
        self._requests: dict[str, VmTaskRequest] = {}
        self._run_refs: dict[str, str] = {}

    async def plan(
        self,
        request: ExecutionBackendRequest,
        *,
        profile: ExecutionBackendProfile,
    ) -> ExecutionBackendPlan:
        self._requests[request.idempotency_key] = self._narrow(request, profile)
        return ExecutionBackendPlan(
            plan_ref=request.idempotency_key,
            backend_kind=self.backend_kind.value,
            request=request,
            created_at=self._clock(),
        )

    async def submit(self, plan: ExecutionBackendPlan) -> ExecutionBackendReceipt:
        task_request = self._requests.get(plan.plan_ref)
        if task_request is None:
            raise ExecutionBackendError("vm-task submit requires a planned request")
        receipt = await self._run(lambda: self._runner.run(task_request))
        self._run_refs[plan.plan_ref] = receipt.run_ref
        return _vm_receipt(receipt)

    async def status(self, submission_ref: str) -> ExecutionBackendReceipt:
        run_ref = self._run_ref(submission_ref)
        return _vm_receipt(await self._run(lambda: self._runner.status(run_ref)))

    async def cancel(self, submission_ref: str) -> ExecutionBackendReceipt:
        run_ref = self._run_ref(submission_ref)
        return _vm_receipt(await self._run(lambda: self._runner.cancel(run_ref)))

    async def collect_receipt(self, submission_ref: str) -> ExecutionBackendReceipt:
        return await self.status(submission_ref)

    async def cleanup(self, submission_ref: str) -> ExecutionCleanupResult:
        run_ref = self._run_refs.pop(submission_ref, None)
        self._requests.pop(submission_ref, None)
        if run_ref is None:
            return ExecutionCleanupResult(
                state=ExecutionCleanupState.COMPLETED,
                detail="no provider run was created",
            )
        return ExecutionCleanupResult(
            state=ExecutionCleanupState.PROVIDER_RETENTION,
            detail="provider retains the managed run record",
        )

    async def capabilities(self) -> ExecutionBackendCapabilities:
        return ExecutionBackendCapabilities(
            backend_kind=self.backend_kind.value,
            supports_status=True,
            supports_cancel=True,
            supports_receipt=True,
            supports_cleanup=True,
            durable_provider_state=True,
        )

    async def health(self) -> ExecutionBackendHealth:
        return ExecutionBackendHealth(
            state=ExecutionHealthState.HEALTHY,
            checked_at=self._clock(),
            detail="governed vm task runner bound",
        )

    def _narrow(
        self,
        request: ExecutionBackendRequest,
        profile: ExecutionBackendProfile,
    ) -> VmTaskRequest:
        if not isinstance(request.payload, VmTaskRequest):
            raise ExecutionBackendError("vm-task requests MUST carry a VmTaskRequest payload")
        constrained = self._catalog.constrain(request.payload)
        narrowed_profile = intersect_execution_profile(self._authority, profile)
        task = constrained.task
        timeout = min(int(task.timeout_seconds), narrowed_profile.max_timeout_seconds)
        return replace(constrained, task=replace(task, timeout_seconds=timeout))

    def _run_ref(self, submission_ref: str) -> str:
        run_ref = self._run_refs.get(submission_ref)
        if run_ref is None:
            raise ExecutionBackendError("vm-task submission is unknown to this process")
        return run_ref

    @staticmethod
    async def _run(operation: Callable[[], object]) -> VmTaskReceipt:
        try:
            receipt = await operation()  # type: ignore[misc]
        except VmTaskRunnerError as exc:
            raise ExecutionBackendError(f"vm task provider failed: {exc}") from exc
        if not isinstance(receipt, VmTaskReceipt):
            raise ExecutionBackendError("vm task provider returned an unexpected receipt")
        return receipt


def _vm_receipt(receipt: VmTaskReceipt) -> ExecutionBackendReceipt:
    return ExecutionBackendReceipt(
        status=_VM_STATUS[receipt.status],
        submission_ref=receipt.run_ref,
        receipt_ref=receipt.run_ref,
        detail=receipt.detail[:2_048],
        already_existed=receipt.already_existed,
    )


__all__ = ["BubblewrapExecutionBackend", "VmTaskExecutionBackend"]
