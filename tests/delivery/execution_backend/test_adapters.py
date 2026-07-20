"""Legacy bubblewrap and VM task behavior is preserved behind ExecutionBackend."""

from __future__ import annotations

from fdai.core.execution_backend import (
    CancellationGuarantee,
    ExecutionBackendKind,
    ExecutionBackendProfile,
    ExecutionNetworkProfile,
    PersistenceMode,
    ResourceCeilings,
    WorkspaceMode,
)
from fdai.core.sandbox import (
    SandboxBackend,
    SandboxProfile,
    SandboxProfileCatalog,
    VmTaskSandboxCatalog,
    VmTaskSandboxProfile,
    WorkspaceAccess,
)
from fdai.delivery.execution_backend import (
    AdapterAuthority,
    BubblewrapExecutionBackend,
    VmTaskExecutionBackend,
    command_plan_digest,
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
    ExecutionBackendRequest,
    ExecutionOwnerTrace,
    ExecutionStatus,
)
from fdai.shared.providers.vm_task import (
    PythonTaskCapability,
    PythonTaskFile,
    PythonTaskSpec,
    VmTaskReceipt,
    VmTaskRequest,
    VmTaskStatus,
    VmTaskTarget,
)


class _CommandRunner:
    def __init__(self) -> None:
        self.plans: list[CommandPlan] = []

    async def execute(self, plan: CommandPlan) -> CommandReceipt:
        self.plans.append(plan)
        return CommandReceipt(
            status=CommandStatus.SUCCEEDED,
            receipt_ref="bubblewrap:run-1",
        )


class _VmRunner:
    def __init__(self) -> None:
        self.requests: list[VmTaskRequest] = []

    async def run(self, request: VmTaskRequest) -> VmTaskReceipt:
        self.requests.append(request)
        return _vm_receipt(VmTaskStatus.SUBMITTED)

    async def status(self, run_ref: str) -> VmTaskReceipt:
        return _vm_receipt(VmTaskStatus.RUNNING)

    async def cancel(self, run_ref: str) -> VmTaskReceipt:
        return _vm_receipt(VmTaskStatus.CANCELLED)


def _resources() -> ResourceCeilings:
    return ResourceCeilings(
        cpu_millis=1_000,
        memory_bytes=512_000_000,
        ephemeral_storage_bytes=1_000_000_000,
        max_concurrency=1,
    )


def _owner() -> ExecutionOwnerTrace:
    return ExecutionOwnerTrace(
        event_ref="event:1",
        action_ref="action:1",
        correlation_ref="trace:1",
    )


async def test_bubblewrap_adapter_preserves_catalog_and_backend_narrowing() -> None:
    command = CommandPlan(
        command_id="code.search",
        command_version=1,
        idempotency_key="event-1:search",
        executable_ref="ripgrep",
        argv=("needle", "."),
        execution_class=CommandExecutionClass.LOCAL_READ,
        network_profile=CommandNetworkProfile.NONE,
        output_format=CommandOutputFormat.TEXT,
        timeout_seconds=90,
        max_output_bytes=100_000,
        dry_run=False,
        workspace_ref="workspace:sha256:" + "a" * 64,
    )
    sandbox = SandboxProfile(
        profile_id="sandbox.local",
        backend=SandboxBackend.BUBBLEWRAP,
        command_ids=frozenset({"code.search"}),
        execution_classes=frozenset({CommandExecutionClass.LOCAL_READ}),
        network_profiles=frozenset({CommandNetworkProfile.NONE}),
        workspace_access=WorkspaceAccess.READ_ONLY,
        max_timeout_seconds=30,
        max_output_bytes=20_000,
    )
    profile = _profile(
        profile_id="backend.local",
        kind=ExecutionBackendKind.BUBBLEWRAP,
        workload_id="code.search",
        workspace=WorkspaceMode.READ_ONLY,
        network=ExecutionNetworkProfile.NONE,
        timeout=20,
        output=10_000,
        region="local",
        scope="workspace",
        credential_refs=frozenset(),
    )
    runner = _CommandRunner()
    backend = BubblewrapExecutionBackend(
        catalog=SandboxProfileCatalog((sandbox,)),
        runner=runner,
        authority=AdapterAuthority(
            resources=_resources(),
            regions=frozenset({"local"}),
            scope_refs=frozenset({"workspace"}),
        ),
    )
    request = ExecutionBackendRequest(
        workload_id="code.search",
        idempotency_key=command.idempotency_key,
        artifact_digest=command_plan_digest(command),
        profile_id=profile.profile_id,
        profile_version=profile.version,
        owner_trace=_owner(),
        stop_condition="stop on timeout or output cap",
        audit_ref="audit:action:1",
        scope_ref="workspace",
        region="local",
        payload=command,
    )

    plan = await backend.plan(request, profile=profile)
    receipt = await backend.submit(plan)

    assert receipt.status is ExecutionStatus.SUCCEEDED
    assert runner.plans[0].timeout_seconds == 20
    assert runner.plans[0].max_output_bytes == 10_000
    assert runner.plans[0].argv == command.argv


async def test_vm_adapter_preserves_task_and_lifecycle_parity() -> None:
    task = PythonTaskSpec(
        task_id="report.render",
        version="1.0.0",
        entrypoint="main.py",
        files=(PythonTaskFile(path="main.py", content="print('ok')"),),
        capabilities=frozenset({PythonTaskCapability.FILESYSTEM_READ}),
        timeout_seconds=300,
    )
    vm_request = VmTaskRequest(
        idempotency_key="event-1:report",
        task=task,
        target=VmTaskTarget(
            resource_ref="resource:vm:example",
            capabilities=frozenset({PythonTaskCapability.FILESYSTEM_READ}),
            location="example-region",
        ),
    )
    profile = _profile(
        profile_id="backend.vm",
        kind=ExecutionBackendKind.VM_TASK,
        workload_id="report.render",
        workspace=WorkspaceMode.NONE,
        network=ExecutionNetworkProfile.AZURE_CONTROL_PLANE,
        timeout=60,
        output=10_000,
        region="example-region",
        scope="resource:vm:example",
        credential_refs=frozenset({"azure.executor"}),
    )
    runner = _VmRunner()
    backend = VmTaskExecutionBackend(
        catalog=VmTaskSandboxCatalog(
            (
                VmTaskSandboxProfile(
                    profile_id="sandbox.vm",
                    task_ids=frozenset({"report.render"}),
                    allowed_capabilities=frozenset({PythonTaskCapability.FILESYSTEM_READ}),
                    max_timeout_seconds=120,
                    max_input_items=10,
                    max_input_bytes=1_000,
                ),
            )
        ),
        runner=runner,
        authority=AdapterAuthority(
            resources=_resources(),
            regions=frozenset({"example-region"}),
            scope_refs=frozenset({"resource:vm:example"}),
            credential_profile_refs=frozenset({"azure.executor"}),
            max_output_bytes=20_000,
        ),
    )
    request = ExecutionBackendRequest(
        workload_id="report.render",
        idempotency_key=vm_request.idempotency_key,
        artifact_digest=task.artifact_hash,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        owner_trace=_owner(),
        stop_condition="stop when the task reaches its timeout",
        audit_ref="audit:action:1",
        scope_ref="resource:vm:example",
        region="example-region",
        payload=vm_request,
    )

    plan = await backend.plan(request, profile=profile)
    submitted = await backend.submit(plan)
    running = await backend.status(submitted.submission_ref)
    cancelled = await backend.cancel(submitted.submission_ref)

    assert runner.requests[0].task.timeout_seconds == 60
    assert submitted.status is ExecutionStatus.SUBMITTED
    assert running.status is ExecutionStatus.RUNNING
    assert cancelled.status is ExecutionStatus.CANCELLED


def _profile(
    *,
    profile_id: str,
    kind: ExecutionBackendKind,
    workload_id: str,
    workspace: WorkspaceMode,
    network: ExecutionNetworkProfile,
    timeout: int,
    output: int,
    region: str,
    scope: str,
    credential_refs: frozenset[str],
) -> ExecutionBackendProfile:
    return ExecutionBackendProfile(
        profile_id=profile_id,
        version="1.0.0",
        backend_kind=kind,
        workload_ids=frozenset({workload_id}),
        workspace_mode=workspace,
        network_profiles=frozenset({network}),
        credential_profile_refs=credential_refs,
        max_timeout_seconds=timeout,
        max_output_bytes=output,
        resources=_resources(),
        persistence_mode=PersistenceMode.DURABLE,
        regions=frozenset({region}),
        scope_refs=frozenset({scope}),
        cancellation_guarantee=CancellationGuarantee.BEST_EFFORT,
    )


def _vm_receipt(status: VmTaskStatus) -> VmTaskReceipt:
    return VmTaskReceipt(
        run_ref="vm:run-1",
        artifact_hash="a" * 64,
        status=status,
        detail=status.value,
    )
