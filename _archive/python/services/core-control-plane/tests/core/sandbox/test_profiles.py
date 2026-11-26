"""Sandbox profile validation and command enforcement tests."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest
from fdai.core.sandbox import (
    DocumentConverterSandboxCatalog,
    DocumentConverterSandboxProfile,
    ProfiledCommandRunner,
    ProfiledDocumentConverter,
    ProfiledToolExecutor,
    ProfiledVmTaskRunner,
    SandboxBackend,
    SandboxPolicyError,
    SandboxProfile,
    SandboxProfileCatalog,
    ToolSandboxCatalog,
    ToolSandboxProfile,
    VmTaskSandboxCatalog,
    VmTaskSandboxProfile,
    WorkspaceAccess,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.command_runner import (
    CommandExecutionClass,
    CommandNetworkProfile,
    CommandOutputFormat,
    CommandPlan,
    CommandReceipt,
    CommandStatus,
)
from fdai.shared.providers.document_converter import (
    DocumentConversionRequest,
    DocumentConversionResult,
)
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallReceipt,
    ToolCallRequest,
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


class _Runner:
    def __init__(self) -> None:
        self.plans: list[CommandPlan] = []

    async def execute(self, plan: CommandPlan) -> CommandReceipt:
        self.plans.append(plan)
        return CommandReceipt(status=CommandStatus.SUCCEEDED, receipt_ref="receipt-1")


def _profile(command_id: str = "code.search") -> SandboxProfile:
    return SandboxProfile(
        profile_id="local.read",
        backend=SandboxBackend.BUBBLEWRAP,
        command_ids=frozenset({command_id}),
        execution_classes=frozenset({CommandExecutionClass.LOCAL_READ}),
        network_profiles=frozenset({CommandNetworkProfile.NONE}),
        workspace_access=WorkspaceAccess.READ_ONLY,
        max_timeout_seconds=30,
        max_output_bytes=10_000,
    )


def _plan(**overrides: object) -> CommandPlan:
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


async def test_profile_wrapper_lowers_limits_before_runner() -> None:
    runner = _Runner()
    profiled = ProfiledCommandRunner(
        catalog=SandboxProfileCatalog().register(_profile()),
        runner=runner,
    )

    await profiled.execute(_plan())

    assert runner.plans[0].timeout_seconds == 30
    assert runner.plans[0].max_output_bytes == 10_000


async def test_unprofiled_command_is_default_deny() -> None:
    runner = _Runner()
    profiled = ProfiledCommandRunner(catalog=SandboxProfileCatalog(), runner=runner)

    with pytest.raises(SandboxPolicyError, match="no sandbox profile"):
        await profiled.execute(_plan())

    assert runner.plans == []


@pytest.mark.parametrize(
    "overrides",
    (
        {"network_profile": CommandNetworkProfile.AZURE_CONTROL_PLANE},
        {"execution_class": CommandExecutionClass.WORKSPACE_WRITE},
        {"credential_profile": "azure.operator"},
        {"workspace_ref": None},
    ),
)
def test_plan_outside_profile_is_rejected(overrides: dict[str, object]) -> None:
    catalog = SandboxProfileCatalog().register(_profile())
    with pytest.raises(SandboxPolicyError):
        catalog.constrain(_plan(**overrides))


def test_overlapping_command_ownership_is_rejected() -> None:
    first = _profile()
    second = SandboxProfile(
        profile_id="other.read",
        backend=SandboxBackend.BUBBLEWRAP,
        command_ids=frozenset({"code.search"}),
        execution_classes=frozenset({CommandExecutionClass.LOCAL_READ}),
        network_profiles=frozenset({CommandNetworkProfile.NONE}),
        workspace_access=WorkspaceAccess.READ_ONLY,
        max_timeout_seconds=10,
        max_output_bytes=1_000,
    )

    with pytest.raises(SandboxPolicyError, match="belongs to both"):
        SandboxProfileCatalog((first, second))


def test_bubblewrap_profile_cannot_enable_network_or_credentials() -> None:
    with pytest.raises(ValueError, match="disable network"):
        SandboxProfile(
            profile_id="unsafe.read",
            backend=SandboxBackend.BUBBLEWRAP,
            command_ids=frozenset({"code.search"}),
            execution_classes=frozenset({CommandExecutionClass.LOCAL_READ}),
            network_profiles=frozenset({CommandNetworkProfile.AZURE_CONTROL_PLANE}),
            workspace_access=WorkspaceAccess.READ_ONLY,
            max_timeout_seconds=10,
            max_output_bytes=1_000,
        )


class _VmRunner:
    def __init__(self) -> None:
        self.requests: list[VmTaskRequest] = []

    async def run(self, request: VmTaskRequest) -> VmTaskReceipt:
        self.requests.append(request)
        return _vm_receipt()

    async def status(self, run_ref: str) -> VmTaskReceipt:
        return _vm_receipt(run_ref)

    async def cancel(self, run_ref: str) -> VmTaskReceipt:
        return _vm_receipt(run_ref, status=VmTaskStatus.CANCELLED)


def _vm_receipt(
    run_ref: str = "vm-run-1",
    *,
    status: VmTaskStatus = VmTaskStatus.SUCCEEDED,
) -> VmTaskReceipt:
    return VmTaskReceipt(
        run_ref=run_ref,
        artifact_hash="a" * 64,
        status=status,
        detail="test",
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


def _vm_profile() -> VmTaskSandboxProfile:
    return VmTaskSandboxProfile(
        profile_id="vm.report",
        task_ids=frozenset({"report.render"}),
        allowed_capabilities=frozenset({PythonTaskCapability.FILESYSTEM_READ}),
        max_timeout_seconds=120,
        max_input_items=2,
        max_input_bytes=100,
    )


async def test_vm_task_profile_lowers_timeout_before_runner() -> None:
    runner = _VmRunner()
    profiled = ProfiledVmTaskRunner(
        catalog=VmTaskSandboxCatalog().register(_vm_profile()),
        runner=runner,
    )

    await profiled.run(_vm_request())

    assert runner.requests[0].task.timeout_seconds == 120


async def test_unprofiled_vm_task_is_default_deny() -> None:
    runner = _VmRunner()
    profiled = ProfiledVmTaskRunner(catalog=VmTaskSandboxCatalog(), runner=runner)

    with pytest.raises(SandboxPolicyError, match="no sandbox profile"):
        await profiled.run(_vm_request())

    assert runner.requests == []


def test_vm_task_profile_rejects_capabilities_outside_profile() -> None:
    catalog = VmTaskSandboxCatalog((_vm_profile(),))

    with pytest.raises(SandboxPolicyError, match="capabilities"):
        catalog.constrain(_vm_request(capabilities=frozenset({PythonTaskCapability.NETWORK})))


def test_vm_task_profile_rejects_input_outside_profile() -> None:
    profile = replace(_vm_profile(), max_input_items=0)
    catalog = VmTaskSandboxCatalog((profile,))

    with pytest.raises(SandboxPolicyError, match="input count"):
        catalog.constrain(_vm_request())


def test_vm_task_profile_cannot_allow_process_capability() -> None:
    with pytest.raises(ValueError, match="MUST NOT allow process"):
        replace(
            _vm_profile(),
            allowed_capabilities=frozenset({PythonTaskCapability.PROCESS}),
        )


class _ToolExecutor:
    def __init__(self) -> None:
        self.requests: list[ToolCallRequest] = []

    async def execute(self, request: ToolCallRequest) -> ToolCallReceipt:
        self.requests.append(request)
        return ToolCallReceipt(
            outcome=ToolCallOutcome.SUCCEEDED,
            receipt_ref="tool-receipt-1",
        )


def _tool_request(**overrides: object) -> ToolCallRequest:
    values: dict[str, object] = {
        "action_id": UUID(int=1),
        "idempotency_key": "tool-key-1",
        "action_type_name": "tool.ticket.create",
        "rule_ids": ("operator-request",),
        "tool_ref": "queue:operations",
        "arguments": {"title": "Investigate"},
        "mode": Mode.SHADOW,
    }
    values.update(overrides)
    return ToolCallRequest(**values)  # type: ignore[arg-type]


def _tool_profile() -> ToolSandboxProfile:
    return ToolSandboxProfile(
        profile_id="tool.ticket",
        action_type_names=frozenset({"tool.ticket.create"}),
        allowed_modes=frozenset({Mode.SHADOW}),
        max_argument_items=2,
        max_argument_bytes=100,
        max_tool_ref_bytes=100,
    )


async def test_tool_profile_is_enforced_before_executor() -> None:
    executor = _ToolExecutor()
    profiled = ProfiledToolExecutor(
        catalog=ToolSandboxCatalog((_tool_profile(),)),
        executor=executor,
    )

    await profiled.execute(_tool_request())

    assert len(executor.requests) == 1


@pytest.mark.parametrize(
    ("overrides", "match"),
    (
        ({"mode": Mode.ENFORCE}, "mode"),
        ({"arguments": {"a": 1, "b": 2, "c": 3}}, "count"),
        ({"arguments": {"title": "x" * 200}}, "bytes"),
        ({"tool_ref": "x" * 200}, "tool_ref"),
    ),
)
def test_tool_profile_rejects_requests_outside_ceiling(
    overrides: dict[str, object],
    match: str,
) -> None:
    catalog = ToolSandboxCatalog((_tool_profile(),))

    with pytest.raises(SandboxPolicyError, match=match):
        catalog.constrain(_tool_request(**overrides))


def test_unprofiled_tool_is_default_deny() -> None:
    with pytest.raises(SandboxPolicyError, match="no sandbox profile"):
        ToolSandboxCatalog().constrain(_tool_request())


class _DocumentConverter:
    def __init__(self, text: str = "converted text") -> None:
        self.text = text
        self.requests: list[DocumentConversionRequest] = []

    async def convert(
        self,
        request: DocumentConversionRequest,
    ) -> DocumentConversionResult:
        self.requests.append(request)
        return DocumentConversionResult(text=self.text)


def _document_profile() -> DocumentConverterSandboxProfile:
    return DocumentConverterSandboxProfile(
        profile_id="document.office",
        converter_ids=frozenset({"office.text"}),
        allowed_suffixes=frozenset({".pdf", ".docx"}),
        max_input_bytes=100,
        max_output_bytes=20,
    )


def _document_request(**overrides: object) -> DocumentConversionRequest:
    values: dict[str, object] = {
        "converter_id": "office.text",
        "source_ref": "docs/runbook.pdf",
        "source_suffix": ".pdf",
        "content": b"pdf-content",
        "max_output_bytes": 1_000,
    }
    values.update(overrides)
    return DocumentConversionRequest(**values)  # type: ignore[arg-type]


async def test_document_profile_lowers_output_ceiling_before_converter() -> None:
    converter = _DocumentConverter()
    profiled = ProfiledDocumentConverter(
        catalog=DocumentConverterSandboxCatalog((_document_profile(),)),
        converter=converter,
    )

    await profiled.convert(_document_request())

    assert converter.requests[0].max_output_bytes == 20


@pytest.mark.parametrize(
    ("conversion_request", "match"),
    (
        (_document_request(source_suffix=".pptx"), "suffix"),
        (_document_request(content=b"x" * 101), "input bytes"),
    ),
)
def test_document_profile_rejects_input_outside_ceiling(
    conversion_request: DocumentConversionRequest,
    match: str,
) -> None:
    catalog = DocumentConverterSandboxCatalog((_document_profile(),))

    with pytest.raises(SandboxPolicyError, match=match):
        catalog.constrain(conversion_request)


async def test_document_profile_rejects_oversized_converter_output() -> None:
    profiled = ProfiledDocumentConverter(
        catalog=DocumentConverterSandboxCatalog((_document_profile(),)),
        converter=_DocumentConverter("x" * 21),
    )

    with pytest.raises(SandboxPolicyError, match="output bytes"):
        await profiled.convert(_document_request())


def test_unprofiled_document_converter_is_default_deny() -> None:
    with pytest.raises(SandboxPolicyError, match="no sandbox profile"):
        DocumentConverterSandboxCatalog().constrain(_document_request())
