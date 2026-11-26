"""Bubblewrap and governed VM-task ExecutionBackend adapters."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.execution_backend.profiles import (
    CancellationGuarantee,
    ExecutionAuthority,
    ExecutionBackendKind,
    ExecutionBackendProfile,
    ExecutionNetworkProfile,
    ExecutionProfileError,
    PersistenceMode,
    ResourceCeilings,
    WorkspaceMode,
)
from fdai.core.sandbox import (
    SandboxBackend,
    SandboxPolicyError,
    SandboxProfile,
    SandboxProfileCatalog,
    VmTaskSandboxCatalog,
    VmTaskSandboxProfile,
    WorkspaceAccess,
)
from fdai.delivery.execution_backend import (
    BubblewrapExecutionBackend,
    VmTaskExecutionBackend,
)
from fdai.shared.providers.command_runner import (
    CommandExecutionClass,
    CommandNetworkProfile,
    CommandOutputFormat,
    CommandPlan,
    CommandReceipt,
    CommandStatus,
)
from fdai.shared.providers.execution_backend import (
    ExecutionBackend,
    ExecutionBackendError,
    ExecutionBackendRequest,
    ExecutionCleanupState,
    ExecutionOwnerTrace,
    ExecutionStatus,
)
from fdai.shared.providers.vm_task import (
    PythonTaskCapability,
    PythonTaskFile,
    PythonTaskSpec,
    VmTaskReceipt,
    VmTaskRequest,
    VmTaskRunnerError,
    VmTaskStatus,
    VmTaskTarget,
)

DIGEST = "a" * 64
CEILINGS = ResourceCeilings(
    cpu_millis=1_000,
    memory_bytes=256_000_000,
    ephemeral_storage_bytes=64_000_000,
    max_concurrency=1,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _authority(kind: ExecutionBackendKind, **overrides: object) -> ExecutionAuthority:
    values: dict[str, object] = {
        "backend_kind": kind,
        "workload_ids": frozenset({"code.search"}),
        "workspace_mode": WorkspaceMode.READ_ONLY,
        "network_profiles": frozenset({ExecutionNetworkProfile.NONE}),
        "credential_profile_refs": frozenset(),
        "max_timeout_seconds": 30,
        "max_output_bytes": 10_000,
        "resources": CEILINGS,
        "regions": frozenset({"koreacentral"}),
        "scope_refs": frozenset({"scope.default"}),
    }
    values.update(overrides)
    return ExecutionAuthority(**values)  # type: ignore[arg-type]


def _profile(kind: ExecutionBackendKind, **overrides: object) -> ExecutionBackendProfile:
    values: dict[str, object] = {
        "profile_id": "backend.local",
        "version": "1.0.0",
        "backend_kind": kind,
        "workload_ids": frozenset({"code.search"}),
        "workspace_mode": WorkspaceMode.READ_ONLY,
        "network_profiles": frozenset({ExecutionNetworkProfile.NONE}),
        "credential_profile_refs": frozenset(),
        "max_timeout_seconds": 10,
        "max_output_bytes": 1_000,
        "resources": CEILINGS,
        "persistence_mode": PersistenceMode.EPHEMERAL,
        "regions": frozenset({"koreacentral"}),
        "scope_refs": frozenset({"scope.default"}),
        "cancellation_guarantee": CancellationGuarantee.NONE,
    }
    values.update(overrides)
    return ExecutionBackendProfile(**values)  # type: ignore[arg-type]


def _request(payload: object, *, key: str = "submission-1") -> ExecutionBackendRequest:
    return ExecutionBackendRequest(
        workload_id="code.search",
        idempotency_key=key,
        artifact_digest=DIGEST,
        profile_id="backend.local",
        profile_version="1.0.0",
        owner_trace=ExecutionOwnerTrace(
            event_ref="event-1",
            action_ref="action-1",
            correlation_ref="correlation-1",
        ),
        stop_condition="operator halt",
        audit_ref="audit-1",
        scope_ref="scope.default",
        region="koreacentral",
        payload=payload,
    )


class _CommandRunner:
    def __init__(self, *, status: CommandStatus = CommandStatus.SUCCEEDED) -> None:
        self.plans: list[CommandPlan] = []
        self._status = status

    async def execute(self, plan: CommandPlan) -> CommandReceipt:
        self.plans.append(plan)
        return CommandReceipt(status=self._status, receipt_ref="receipt-1", exit_code=0)


def _sandbox_profile() -> SandboxProfile:
    return SandboxProfile(
        profile_id="local.read",
        backend=SandboxBackend.BUBBLEWRAP,
        command_ids=frozenset({"code.search"}),
        execution_classes=frozenset({CommandExecutionClass.LOCAL_READ}),
        network_profiles=frozenset({CommandNetworkProfile.NONE}),
        workspace_access=WorkspaceAccess.READ_ONLY,
        max_timeout_seconds=30,
        max_output_bytes=10_000,
    )


def _command_plan(**overrides: object) -> CommandPlan:
    values: dict[str, object] = {
        "command_id": "code.search",
        "command_version": 1,
        "idempotency_key": "key-1",
        "executable_ref": "ripgrep",
        "argv": ("pattern", "."),
        "execution_class": CommandExecutionClass.LOCAL_READ,
        "network_profile": CommandNetworkProfile.NONE,
        "output_format": CommandOutputFormat.TEXT,
        "timeout_seconds": 90,
        "max_output_bytes": 100_000,
        "dry_run": False,
        "workspace_ref": "workspace:sha256:" + "a" * 64,
    }
    values.update(overrides)
    return CommandPlan(**values)  # type: ignore[arg-type]


def _bubblewrap(runner: _CommandRunner | None = None) -> BubblewrapExecutionBackend:
    return BubblewrapExecutionBackend(
        catalog=SandboxProfileCatalog().register(_sandbox_profile()),
        runner=runner or _CommandRunner(),
        authority=_authority(ExecutionBackendKind.BUBBLEWRAP),
    )


class _VmRunner:
    def __init__(self, *, fail: bool = False) -> None:
        self.requests: list[VmTaskRequest] = []
        self.cancelled: list[str] = []
        self._fail = fail

    async def run(self, request: VmTaskRequest) -> VmTaskReceipt:
        if self._fail:
            raise VmTaskRunnerError("provider unavailable")
        self.requests.append(request)
        return VmTaskReceipt(
            run_ref="vm-run-1", artifact_hash=DIGEST, status=VmTaskStatus.SUCCEEDED, detail="ok"
        )

    async def status(self, run_ref: str) -> VmTaskReceipt:
        return VmTaskReceipt(
            run_ref=run_ref, artifact_hash=DIGEST, status=VmTaskStatus.RUNNING, detail="running"
        )

    async def cancel(self, run_ref: str) -> VmTaskReceipt:
        self.cancelled.append(run_ref)
        return VmTaskReceipt(
            run_ref=run_ref,
            artifact_hash=DIGEST,
            status=VmTaskStatus.CANCELLED,
            detail="cancelled",
        )


def _vm_request(**task_overrides: object) -> VmTaskRequest:
    task_values: dict[str, object] = {
        "task_id": "report.render",
        "version": "1",
        "entrypoint": "main.py",
        "files": (PythonTaskFile(path="main.py", content="print('ok')"),),
        "capabilities": frozenset({PythonTaskCapability.FILESYSTEM_READ}),
        "timeout_seconds": 900,
    }
    task_values.update(task_overrides)
    return VmTaskRequest(
        idempotency_key="vm-key-1",
        task=PythonTaskSpec(**task_values),  # type: ignore[arg-type]
        target=VmTaskTarget(
            resource_ref="resource:vm:test",
            capabilities=frozenset({PythonTaskCapability.FILESYSTEM_READ}),
        ),
        inputs={"report": "daily"},
    )


def _vm_backend(runner: _VmRunner | None = None) -> VmTaskExecutionBackend:
    catalog = VmTaskSandboxCatalog().register(
        VmTaskSandboxProfile(
            profile_id="vm.report",
            task_ids=frozenset({"report.render"}),
            allowed_capabilities=frozenset({PythonTaskCapability.FILESYSTEM_READ}),
            max_timeout_seconds=120,
            max_input_items=2,
            max_input_bytes=100,
        )
    )
    return VmTaskExecutionBackend(
        catalog=catalog,
        runner=runner or _VmRunner(),
        authority=_authority(
            ExecutionBackendKind.VM_TASK,
            workload_ids=frozenset({"code.search"}),
            max_timeout_seconds=60,
        ),
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_both_adapters_satisfy_the_execution_backend_protocol() -> None:
    assert isinstance(_bubblewrap(), ExecutionBackend)
    assert isinstance(_vm_backend(), ExecutionBackend)


def test_an_adapter_rejects_a_mismatched_authority() -> None:
    with pytest.raises(ValueError, match="bubblewrap backend"):
        BubblewrapExecutionBackend(
            catalog=SandboxProfileCatalog(),
            runner=_CommandRunner(),
            authority=_authority(ExecutionBackendKind.VM_TASK),
        )
    with pytest.raises(ValueError, match="vm_task backend"):
        VmTaskExecutionBackend(
            catalog=VmTaskSandboxCatalog(),
            runner=_VmRunner(),
            authority=_authority(ExecutionBackendKind.BUBBLEWRAP),
        )


# ---------------------------------------------------------------------------
# Bubblewrap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bubblewrap_lowers_limits_and_never_raises_them() -> None:
    runner = _CommandRunner()
    backend = _bubblewrap(runner)

    plan = await backend.plan(
        _request(_command_plan()), profile=_profile(ExecutionBackendKind.BUBBLEWRAP)
    )
    await backend.submit(plan)

    assert runner.plans[0].timeout_seconds == 10
    assert runner.plans[0].max_output_bytes == 1_000


@pytest.mark.asyncio
async def test_bubblewrap_rejects_a_widening_profile_before_provider_io() -> None:
    runner = _CommandRunner()
    backend = _bubblewrap(runner)
    widened = _profile(
        ExecutionBackendKind.BUBBLEWRAP,
        network_profiles=frozenset({ExecutionNetworkProfile.AZURE_CONTROL_PLANE}),
    )

    with pytest.raises(ExecutionProfileError, match="widen network"):
        await backend.plan(_request(_command_plan()), profile=widened)

    assert runner.plans == []


@pytest.mark.asyncio
async def test_bubblewrap_keeps_the_sandbox_catalog_default_deny() -> None:
    backend = BubblewrapExecutionBackend(
        catalog=SandboxProfileCatalog(),
        runner=_CommandRunner(),
        authority=_authority(ExecutionBackendKind.BUBBLEWRAP),
    )

    with pytest.raises(SandboxPolicyError, match="no sandbox profile"):
        await backend.plan(
            _request(_command_plan()), profile=_profile(ExecutionBackendKind.BUBBLEWRAP)
        )


@pytest.mark.asyncio
async def test_bubblewrap_requires_a_command_plan_payload() -> None:
    backend = _bubblewrap()
    with pytest.raises(ExecutionBackendError, match="CommandPlan payload"):
        await backend.plan(
            _request("not-a-plan"), profile=_profile(ExecutionBackendKind.BUBBLEWRAP)
        )


@pytest.mark.asyncio
async def test_bubblewrap_submit_is_terminal_and_duplicate_safe() -> None:
    runner = _CommandRunner()
    backend = _bubblewrap(runner)
    plan = await backend.plan(
        _request(_command_plan()), profile=_profile(ExecutionBackendKind.BUBBLEWRAP)
    )

    first = await backend.submit(plan)
    second = await backend.submit(plan)

    assert first.status is ExecutionStatus.SUCCEEDED
    assert second.already_existed
    assert len(runner.plans) == 1


@pytest.mark.asyncio
async def test_bubblewrap_declares_no_cancellation_and_refuses_to_fake_it() -> None:
    backend = _bubblewrap()
    capabilities = await backend.capabilities()

    assert capabilities.supports_cancel is False
    with pytest.raises(ExecutionBackendError, match="only cancellation mechanism"):
        await backend.cancel("submission-1")


@pytest.mark.asyncio
async def test_bubblewrap_status_of_an_unknown_submission_fails_closed() -> None:
    with pytest.raises(ExecutionBackendError, match="unknown to this process"):
        await _bubblewrap().status("absent")


@pytest.mark.asyncio
async def test_bubblewrap_cleanup_releases_the_local_workspace() -> None:
    backend = _bubblewrap()
    plan = await backend.plan(
        _request(_command_plan()), profile=_profile(ExecutionBackendKind.BUBBLEWRAP)
    )
    await backend.submit(plan)

    result = await backend.cleanup(plan.plan_ref)

    assert result.state is ExecutionCleanupState.COMPLETED
    with pytest.raises(ExecutionBackendError):
        await backend.status(plan.plan_ref)


# ---------------------------------------------------------------------------
# Governed VM task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vm_task_lowers_the_timeout_to_the_narrowest_bound() -> None:
    runner = _VmRunner()
    backend = _vm_backend(runner)

    plan = await backend.plan(
        _request(_vm_request()), profile=_profile(ExecutionBackendKind.VM_TASK)
    )
    await backend.submit(plan)

    assert runner.requests[0].task.timeout_seconds == 10


@pytest.mark.asyncio
async def test_vm_task_keeps_capability_checks_from_the_sandbox_catalog() -> None:
    runner = _VmRunner()
    backend = _vm_backend(runner)
    request = _vm_request(capabilities=frozenset({PythonTaskCapability.NETWORK}))

    with pytest.raises(SandboxPolicyError, match="outside its sandbox profile"):
        await backend.plan(_request(request), profile=_profile(ExecutionBackendKind.VM_TASK))

    assert runner.requests == []


@pytest.mark.asyncio
async def test_vm_task_rejects_a_widening_profile() -> None:
    backend = _vm_backend()
    widened = _profile(ExecutionBackendKind.VM_TASK, max_timeout_seconds=600)

    with pytest.raises(ExecutionProfileError, match="widen timeout"):
        await backend.plan(_request(_vm_request()), profile=widened)


@pytest.mark.asyncio
async def test_vm_task_requires_a_vm_request_payload() -> None:
    with pytest.raises(ExecutionBackendError, match="VmTaskRequest payload"):
        await _vm_backend().plan(
            _request(_command_plan()), profile=_profile(ExecutionBackendKind.VM_TASK)
        )


@pytest.mark.asyncio
async def test_vm_task_maps_status_and_cancel_through_the_run_reference() -> None:
    runner = _VmRunner()
    backend = _vm_backend(runner)
    plan = await backend.plan(
        _request(_vm_request()), profile=_profile(ExecutionBackendKind.VM_TASK)
    )
    submitted = await backend.submit(plan)

    status = await backend.status(plan.plan_ref)
    cancelled = await backend.cancel(plan.plan_ref)

    assert submitted.status is ExecutionStatus.SUCCEEDED
    assert status.status is ExecutionStatus.RUNNING
    assert cancelled.status is ExecutionStatus.CANCELLED
    assert runner.cancelled == ["vm-run-1"]


@pytest.mark.asyncio
async def test_vm_task_provider_failure_is_reported_as_a_backend_error() -> None:
    backend = _vm_backend(_VmRunner(fail=True))
    plan = await backend.plan(
        _request(_vm_request()), profile=_profile(ExecutionBackendKind.VM_TASK)
    )

    with pytest.raises(ExecutionBackendError, match="vm task provider failed"):
        await backend.submit(plan)


@pytest.mark.asyncio
async def test_vm_task_status_before_submit_fails_closed() -> None:
    with pytest.raises(ExecutionBackendError, match="unknown to this process"):
        await _vm_backend().status("absent")


@pytest.mark.asyncio
async def test_vm_task_cleanup_reports_provider_retention() -> None:
    backend = _vm_backend()
    plan = await backend.plan(
        _request(_vm_request()), profile=_profile(ExecutionBackendKind.VM_TASK)
    )
    await backend.submit(plan)

    retained = await backend.cleanup(plan.plan_ref)
    unsubmitted = await backend.cleanup("absent")

    assert retained.state is ExecutionCleanupState.PROVIDER_RETENTION
    assert unsubmitted.state is ExecutionCleanupState.COMPLETED


@pytest.mark.asyncio
async def test_vm_task_reports_its_declared_capabilities_and_health() -> None:
    backend = _vm_backend()

    capabilities = await backend.capabilities()
    health = await backend.health()

    assert capabilities.supports_cancel is True
    assert capabilities.durable_provider_state is True
    assert health.checked_at.tzinfo is not None


def test_narrowed_command_plan_never_widens_the_sandbox_result() -> None:
    catalog = SandboxProfileCatalog().register(_sandbox_profile())
    constrained = catalog.constrain(_command_plan())
    narrowed = replace(constrained, timeout_seconds=min(constrained.timeout_seconds, 10))

    assert narrowed.timeout_seconds <= constrained.timeout_seconds
    assert narrowed.network_profile is CommandNetworkProfile.NONE
    assert narrowed.credential_profile is None
