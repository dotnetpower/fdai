"""ExecutionBackend adapters over the existing bubblewrap and VM task runners."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from fdai.core.execution_backend import (
    ExecutionAuthority,
    ExecutionBackendKind,
    ExecutionBackendProfile,
    ExecutionNetworkProfile,
    ResourceCeilings,
    WorkspaceMode,
    intersect_execution_profile,
)
from fdai.core.sandbox import SandboxProfileCatalog, VmTaskSandboxCatalog
from fdai.shared.providers.command_runner import (
    CommandPlan,
    CommandReceipt,
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
    VmTaskStatus,
)


@dataclass(frozen=True, slots=True)
class AdapterAuthority:
    """Server-owned hard bounds not represented in legacy sandbox profiles."""

    resources: ResourceCeilings
    regions: frozenset[str]
    scope_refs: frozenset[str]
    credential_profile_refs: frozenset[str] = frozenset()
    max_output_bytes: int = 100_000_000

    def __post_init__(self) -> None:
        if not 1 <= self.max_output_bytes <= 100_000_000:
            raise ValueError("adapter max_output_bytes MUST be in [1, 100000000]")


class BubblewrapExecutionBackend:
    """Lifecycle adapter for catalog-validated credential-free local reads."""

    def __init__(
        self,
        *,
        catalog: SandboxProfileCatalog,
        runner: CommandRunner,
        authority: AdapterAuthority,
    ) -> None:
        self._catalog = catalog
        self._runner = runner
        self._authority = authority
        self._receipts: dict[str, ExecutionBackendReceipt] = {}

    async def plan(
        self,
        request: ExecutionBackendRequest,
        *,
        profile: ExecutionBackendProfile,
    ) -> ExecutionBackendPlan:
        if not isinstance(request.payload, CommandPlan):
            raise ExecutionBackendError("bubblewrap backend requires a CommandPlan payload")
        command_plan = self._catalog.constrain(request.payload)
        if request.workload_id != command_plan.command_id:
            raise ExecutionBackendError("request workload does not match command plan")
        if request.artifact_digest != command_plan_digest(command_plan):
            raise ExecutionBackendError("command plan artifact digest mismatch")
        sandbox = self._catalog.require(command_plan.command_id)
        credentials = (
            frozenset({command_plan.credential_profile})
            if command_plan.credential_profile is not None
            else frozenset()
        )
        authority = ExecutionAuthority(
            backend_kind=ExecutionBackendKind.BUBBLEWRAP,
            workload_ids=sandbox.command_ids,
            workspace_mode=WorkspaceMode(sandbox.workspace_access.value),
            network_profiles=frozenset(
                ExecutionNetworkProfile(value.value) for value in sandbox.network_profiles
            ),
            credential_profile_refs=credentials,
            max_timeout_seconds=sandbox.max_timeout_seconds,
            max_output_bytes=sandbox.max_output_bytes,
            resources=self._authority.resources,
            regions=self._authority.regions,
            scope_refs=self._authority.scope_refs,
        )
        effective = intersect_execution_profile(authority, profile)
        _validate_command_within_effective(command_plan, effective)
        command_plan = replace(
            command_plan,
            timeout_seconds=min(command_plan.timeout_seconds, effective.max_timeout_seconds),
            max_output_bytes=min(command_plan.max_output_bytes, effective.max_output_bytes),
        )
        return ExecutionBackendPlan(
            plan_ref=f"bubblewrap-plan:{request.artifact_digest[:24]}",
            backend_kind=ExecutionBackendKind.BUBBLEWRAP.value,
            request=ExecutionBackendRequest(
                workload_id=request.workload_id,
                idempotency_key=request.idempotency_key,
                artifact_digest=request.artifact_digest,
                profile_id=request.profile_id,
                profile_version=request.profile_version,
                owner_trace=request.owner_trace,
                stop_condition=request.stop_condition,
                audit_ref=request.audit_ref,
                scope_ref=request.scope_ref,
                region=request.region,
                payload=command_plan,
            ),
            created_at=datetime.now(tz=UTC),
        )

    async def submit(self, plan: ExecutionBackendPlan) -> ExecutionBackendReceipt:
        command_plan = _command_payload(plan)
        receipt = _command_receipt(await self._runner.execute(command_plan))
        self._receipts[receipt.submission_ref] = receipt
        return receipt

    async def status(self, submission_ref: str) -> ExecutionBackendReceipt:
        return self._require_receipt(submission_ref)

    async def cancel(self, submission_ref: str) -> ExecutionBackendReceipt:
        receipt = self._require_receipt(submission_ref)
        if receipt.status.terminal:
            return receipt
        raise ExecutionBackendError("bubblewrap cancellation is handled by process timeout")

    async def collect_receipt(self, submission_ref: str) -> ExecutionBackendReceipt:
        return self._require_receipt(submission_ref)

    async def cleanup(self, submission_ref: str) -> ExecutionCleanupResult:
        self._require_receipt(submission_ref)
        del self._receipts[submission_ref]
        return ExecutionCleanupResult(
            state=ExecutionCleanupState.COMPLETED,
            detail="local execution receipt released",
        )

    async def capabilities(self) -> ExecutionBackendCapabilities:
        return _capabilities(ExecutionBackendKind.BUBBLEWRAP, durable=False)

    async def health(self) -> ExecutionBackendHealth:
        return _healthy("bubblewrap runner is bound")

    def _require_receipt(self, submission_ref: str) -> ExecutionBackendReceipt:
        try:
            return self._receipts[submission_ref]
        except KeyError as exc:
            raise ExecutionBackendError("bubblewrap execution status is unavailable") from exc


class VmTaskExecutionBackend:
    """Lifecycle adapter for sandboxed governed VM tasks."""

    def __init__(
        self,
        *,
        catalog: VmTaskSandboxCatalog,
        runner: VmTaskRunner,
        authority: AdapterAuthority,
    ) -> None:
        self._catalog = catalog
        self._runner = runner
        self._authority = authority

    async def plan(
        self,
        request: ExecutionBackendRequest,
        *,
        profile: ExecutionBackendProfile,
    ) -> ExecutionBackendPlan:
        if not isinstance(request.payload, VmTaskRequest):
            raise ExecutionBackendError("VM task backend requires a VmTaskRequest payload")
        if request.artifact_digest != request.payload.task.artifact_hash:
            raise ExecutionBackendError("VM task artifact digest mismatch")
        vm_request = self._catalog.constrain(request.payload)
        if request.workload_id != vm_request.task.task_id:
            raise ExecutionBackendError("request workload does not match VM task")
        sandbox = self._catalog.require(vm_request.task.task_id)
        authority = ExecutionAuthority(
            backend_kind=ExecutionBackendKind.VM_TASK,
            workload_ids=sandbox.task_ids,
            workspace_mode=WorkspaceMode.NONE,
            network_profiles=frozenset({ExecutionNetworkProfile.AZURE_CONTROL_PLANE}),
            credential_profile_refs=self._authority.credential_profile_refs,
            max_timeout_seconds=sandbox.max_timeout_seconds,
            max_output_bytes=self._authority.max_output_bytes,
            resources=self._authority.resources,
            regions=self._authority.regions,
            scope_refs=self._authority.scope_refs,
        )
        effective = intersect_execution_profile(authority, profile)
        if request.region not in effective.regions or request.scope_ref not in effective.scope_refs:
            raise ExecutionBackendError("VM task target is outside the effective profile")
        vm_request = replace(
            vm_request,
            task=replace(
                vm_request.task,
                timeout_seconds=min(
                    vm_request.task.timeout_seconds,
                    effective.max_timeout_seconds,
                ),
            ),
        )
        return ExecutionBackendPlan(
            plan_ref=f"vm-task-plan:{request.artifact_digest[:24]}",
            backend_kind=ExecutionBackendKind.VM_TASK.value,
            request=ExecutionBackendRequest(
                workload_id=request.workload_id,
                idempotency_key=request.idempotency_key,
                artifact_digest=request.artifact_digest,
                profile_id=request.profile_id,
                profile_version=request.profile_version,
                owner_trace=request.owner_trace,
                stop_condition=request.stop_condition,
                audit_ref=request.audit_ref,
                scope_ref=request.scope_ref,
                region=request.region,
                payload=vm_request,
            ),
            created_at=datetime.now(tz=UTC),
        )

    async def submit(self, plan: ExecutionBackendPlan) -> ExecutionBackendReceipt:
        return _vm_receipt(await self._runner.run(_vm_payload(plan)))

    async def status(self, submission_ref: str) -> ExecutionBackendReceipt:
        return _vm_receipt(await self._runner.status(submission_ref))

    async def cancel(self, submission_ref: str) -> ExecutionBackendReceipt:
        return _vm_receipt(await self._runner.cancel(submission_ref))

    async def collect_receipt(self, submission_ref: str) -> ExecutionBackendReceipt:
        return await self.status(submission_ref)

    async def cleanup(self, submission_ref: str) -> ExecutionCleanupResult:
        await self._runner.cancel(submission_ref)
        return ExecutionCleanupResult(
            state=ExecutionCleanupState.COMPLETED,
            detail="VM task run-command resource removed",
        )

    async def capabilities(self) -> ExecutionBackendCapabilities:
        return _capabilities(ExecutionBackendKind.VM_TASK, durable=True)

    async def health(self) -> ExecutionBackendHealth:
        return _healthy("VM task runner is bound")


def command_plan_digest(plan: CommandPlan) -> str:
    payload = {
        "command_id": plan.command_id,
        "command_version": plan.command_version,
        "executable_ref": plan.executable_ref,
        "argv": list(plan.argv),
        "execution_class": plan.execution_class.value,
        "network_profile": plan.network_profile.value,
        "output_format": plan.output_format.value,
        "credential_profile": plan.credential_profile,
        "workspace_ref": plan.workspace_ref,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_command_within_effective(
    plan: CommandPlan,
    profile: ExecutionBackendProfile,
) -> None:
    if ExecutionNetworkProfile(plan.network_profile.value) not in profile.network_profiles:
        raise ExecutionBackendError("command network is outside the effective profile")
    if plan.credential_profile is not None and (
        plan.credential_profile not in profile.credential_profile_refs
    ):
        raise ExecutionBackendError("command credential is outside the effective profile")


def _command_payload(plan: ExecutionBackendPlan) -> CommandPlan:
    payload = plan.request.payload
    if not isinstance(payload, CommandPlan):
        raise ExecutionBackendError("bubblewrap plan payload was lost")
    return payload


def _vm_payload(plan: ExecutionBackendPlan) -> VmTaskRequest:
    payload = plan.request.payload
    if not isinstance(payload, VmTaskRequest):
        raise ExecutionBackendError("VM task plan payload was lost")
    return payload


def _command_receipt(receipt: CommandReceipt) -> ExecutionBackendReceipt:
    status = {
        CommandStatus.PLANNED: ExecutionStatus.PLANNED,
        CommandStatus.SUCCEEDED: ExecutionStatus.SUCCEEDED,
        CommandStatus.ALREADY_APPLIED: ExecutionStatus.SUCCEEDED,
        CommandStatus.FAILED: ExecutionStatus.FAILED,
        CommandStatus.STOPPED: ExecutionStatus.CANCELLED,
    }[receipt.status]
    return ExecutionBackendReceipt(
        status=status,
        submission_ref=receipt.receipt_ref,
        receipt_ref=receipt.receipt_ref,
        detail=receipt.stderr_tail or receipt.stdout_tail,
        already_existed=receipt.already_existed,
    )


def _vm_receipt(receipt: VmTaskReceipt) -> ExecutionBackendReceipt:
    status = {
        VmTaskStatus.PLANNED: ExecutionStatus.PLANNED,
        VmTaskStatus.SUBMITTED: ExecutionStatus.SUBMITTED,
        VmTaskStatus.RUNNING: ExecutionStatus.RUNNING,
        VmTaskStatus.SUCCEEDED: ExecutionStatus.SUCCEEDED,
        VmTaskStatus.FAILED: ExecutionStatus.FAILED,
        VmTaskStatus.CANCELLED: ExecutionStatus.CANCELLED,
    }[receipt.status]
    return ExecutionBackendReceipt(
        status=status,
        submission_ref=receipt.run_ref,
        receipt_ref=receipt.run_ref,
        detail=receipt.detail,
        already_existed=receipt.already_existed,
    )


def _capabilities(
    kind: ExecutionBackendKind,
    *,
    durable: bool,
) -> ExecutionBackendCapabilities:
    return ExecutionBackendCapabilities(
        backend_kind=kind.value,
        supports_status=True,
        supports_cancel=True,
        supports_receipt=True,
        supports_cleanup=True,
        durable_provider_state=durable,
    )


def _healthy(detail: str) -> ExecutionBackendHealth:
    return ExecutionBackendHealth(
        state=ExecutionHealthState.HEALTHY,
        checked_at=datetime.now(tz=UTC),
        detail=detail,
    )


__all__ = [
    "AdapterAuthority",
    "BubblewrapExecutionBackend",
    "VmTaskExecutionBackend",
    "command_plan_digest",
]
