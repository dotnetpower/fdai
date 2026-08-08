"""Validated sandbox profiles that constrain typed command plans."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.command_runner import (
    CommandExecutionClass,
    CommandNetworkProfile,
    CommandPlan,
    CommandReceipt,
    CommandRunner,
)
from fdai.shared.providers.document_converter import (
    DocumentConversionRequest,
    DocumentConversionResult,
    DocumentConverter,
)
from fdai.shared.providers.tool import (
    ToolCallReceipt,
    ToolCallRequest,
    ToolExecutor,
)
from fdai.shared.providers.vm_task import (
    PythonTaskCapability,
    VmTaskReceipt,
    VmTaskRequest,
    VmTaskRunner,
)

if TYPE_CHECKING:
    from fdai.core.programmatic_pipeline.models import ProgrammaticToolPipelineRequest

_PROFILE_ID = re.compile(r"^[a-z][a-z0-9.-]{2,127}$")


class SandboxBackend(StrEnum):
    BUBBLEWRAP = "bubblewrap"
    VM_TASK = "vm_task"


class WorkspaceAccess(StrEnum):
    NONE = "none"
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"


@dataclass(frozen=True, slots=True)
class SandboxProfile:
    """Server-owned execution envelope for one or more command ids."""

    profile_id: str
    backend: SandboxBackend
    command_ids: frozenset[str]
    execution_classes: frozenset[CommandExecutionClass]
    network_profiles: frozenset[CommandNetworkProfile]
    workspace_access: WorkspaceAccess
    max_timeout_seconds: int
    max_output_bytes: int
    allow_credentials: bool = False

    def __post_init__(self) -> None:
        if _PROFILE_ID.fullmatch(self.profile_id) is None:
            raise ValueError("sandbox profile_id MUST be lowercase ASCII")
        if not self.command_ids or not self.execution_classes or not self.network_profiles:
            raise ValueError("sandbox profile allowlists MUST be non-empty")
        if not 1 <= self.max_timeout_seconds <= 900:
            raise ValueError("sandbox max_timeout_seconds MUST be in [1, 900]")
        if not 1 <= self.max_output_bytes <= 5_000_000:
            raise ValueError("sandbox max_output_bytes MUST be in [1, 5000000]")
        if self.backend is SandboxBackend.BUBBLEWRAP:
            if self.workspace_access is not WorkspaceAccess.READ_ONLY:
                raise ValueError("bubblewrap command profiles MUST use read-only workspace access")
            if self.network_profiles != frozenset({CommandNetworkProfile.NONE}):
                raise ValueError("bubblewrap command profiles MUST disable network access")
            if self.allow_credentials:
                raise ValueError("bubblewrap command profiles MUST NOT allow credentials")


class SandboxPolicyError(ValueError):
    """A command plan does not fit its server-owned isolation profile."""


class SandboxProfileCatalog:
    """Immutable profile registry with one owner per command id."""

    __slots__ = ("_profiles", "_profiles_by_command")

    def __init__(self, profiles: tuple[SandboxProfile, ...] = ()) -> None:
        by_id: dict[str, SandboxProfile] = {}
        by_command: dict[str, SandboxProfile] = {}
        for profile in profiles:
            if profile.profile_id in by_id:
                raise SandboxPolicyError(f"duplicate sandbox profile {profile.profile_id!r}")
            by_id[profile.profile_id] = profile
            for command_id in profile.command_ids:
                prior = by_command.get(command_id)
                if prior is not None:
                    raise SandboxPolicyError(
                        f"command {command_id!r} belongs to both {prior.profile_id!r} "
                        f"and {profile.profile_id!r}"
                    )
                by_command[command_id] = profile
        self._profiles = MappingProxyType(by_id)
        self._profiles_by_command = MappingProxyType(by_command)

    def register(self, profile: SandboxProfile) -> SandboxProfileCatalog:
        return SandboxProfileCatalog((*self.list(), profile))

    def list(self) -> tuple[SandboxProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))

    def require(self, command_id: str) -> SandboxProfile:
        try:
            return self._profiles_by_command[command_id]
        except KeyError as exc:
            raise SandboxPolicyError(f"command {command_id!r} has no sandbox profile") from exc

    def constrain(self, plan: CommandPlan) -> CommandPlan:
        """Validate a plan and lower its limits to the owning profile ceilings."""
        profile = self.require(plan.command_id)
        if plan.execution_class not in profile.execution_classes:
            raise SandboxPolicyError("command execution class is outside its sandbox profile")
        if plan.network_profile not in profile.network_profiles:
            raise SandboxPolicyError("command network profile is outside its sandbox profile")
        if plan.credential_profile is not None and not profile.allow_credentials:
            raise SandboxPolicyError("command credentials are outside its sandbox profile")
        if profile.workspace_access is WorkspaceAccess.NONE and plan.workspace_ref is not None:
            raise SandboxPolicyError("command workspace is forbidden by its sandbox profile")
        if profile.workspace_access is not WorkspaceAccess.NONE and plan.workspace_ref is None:
            raise SandboxPolicyError("command requires a bounded workspace")
        return replace(
            plan,
            timeout_seconds=min(plan.timeout_seconds, profile.max_timeout_seconds),
            max_output_bytes=min(plan.max_output_bytes, profile.max_output_bytes),
        )


class ProfiledCommandRunner(CommandRunner):
    """Enforce a sandbox profile immediately before the concrete runner."""

    def __init__(self, *, catalog: SandboxProfileCatalog, runner: CommandRunner) -> None:
        self._catalog = catalog
        self._runner = runner

    async def execute(self, plan: CommandPlan) -> CommandReceipt:
        return await self._runner.execute(self._catalog.constrain(plan))


@dataclass(frozen=True, slots=True)
class VmTaskSandboxProfile:
    """Server-owned execution envelope for governed Python VM tasks."""

    profile_id: str
    task_ids: frozenset[str]
    allowed_capabilities: frozenset[PythonTaskCapability]
    max_timeout_seconds: int
    max_input_items: int
    max_input_bytes: int

    def __post_init__(self) -> None:
        if _PROFILE_ID.fullmatch(self.profile_id) is None:
            raise ValueError("VM task sandbox profile_id MUST be lowercase ASCII")
        if not self.task_ids:
            raise ValueError("VM task sandbox task_ids MUST be non-empty")
        if PythonTaskCapability.PROCESS in self.allowed_capabilities:
            raise ValueError("VM task sandbox profiles MUST NOT allow process capability")
        if not 1 <= self.max_timeout_seconds <= 86_400:
            raise ValueError("VM task sandbox max_timeout_seconds MUST be in [1, 86400]")
        if not 0 <= self.max_input_items <= 100:
            raise ValueError("VM task sandbox max_input_items MUST be in [0, 100]")
        if not 0 <= self.max_input_bytes <= 400_000:
            raise ValueError("VM task sandbox max_input_bytes MUST be in [0, 400000]")


class VmTaskSandboxCatalog:
    """Immutable VM-task registry with one profile owner per task id."""

    __slots__ = ("_profiles", "_profiles_by_task")

    def __init__(self, profiles: tuple[VmTaskSandboxProfile, ...] = ()) -> None:
        by_id: dict[str, VmTaskSandboxProfile] = {}
        by_task: dict[str, VmTaskSandboxProfile] = {}
        for profile in profiles:
            if profile.profile_id in by_id:
                raise SandboxPolicyError(
                    f"duplicate VM task sandbox profile {profile.profile_id!r}"
                )
            by_id[profile.profile_id] = profile
            for task_id in profile.task_ids:
                prior = by_task.get(task_id)
                if prior is not None:
                    raise SandboxPolicyError(
                        f"VM task {task_id!r} belongs to both {prior.profile_id!r} "
                        f"and {profile.profile_id!r}"
                    )
                by_task[task_id] = profile
        self._profiles = MappingProxyType(by_id)
        self._profiles_by_task = MappingProxyType(by_task)

    def register(self, profile: VmTaskSandboxProfile) -> VmTaskSandboxCatalog:
        return VmTaskSandboxCatalog((*self.list(), profile))

    def list(self) -> tuple[VmTaskSandboxProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))

    def require(self, task_id: str) -> VmTaskSandboxProfile:
        try:
            return self._profiles_by_task[task_id]
        except KeyError as exc:
            raise SandboxPolicyError(f"VM task {task_id!r} has no sandbox profile") from exc

    def constrain(self, request: VmTaskRequest) -> VmTaskRequest:
        profile = self.require(request.task.task_id)
        unsupported = request.task.capabilities - profile.allowed_capabilities
        if unsupported:
            names = ", ".join(sorted(capability.value for capability in unsupported))
            raise SandboxPolicyError(
                f"VM task capabilities are outside its sandbox profile: {names}"
            )
        if len(request.inputs) > profile.max_input_items:
            raise SandboxPolicyError("VM task input count is outside its sandbox profile")
        input_bytes = sum(
            len(key.encode("utf-8")) + len(value.encode("utf-8"))
            for key, value in request.inputs.items()
        )
        if input_bytes > profile.max_input_bytes:
            raise SandboxPolicyError("VM task input bytes are outside its sandbox profile")
        task = replace(
            request.task,
            timeout_seconds=min(request.task.timeout_seconds, profile.max_timeout_seconds),
        )
        return replace(request, task=task)


class ProfiledVmTaskRunner(VmTaskRunner):
    """Enforce a VM-task sandbox profile immediately before submission."""

    def __init__(self, *, catalog: VmTaskSandboxCatalog, runner: VmTaskRunner) -> None:
        self._catalog = catalog
        self._runner = runner

    async def run(self, request: VmTaskRequest) -> VmTaskReceipt:
        return await self._runner.run(self._catalog.constrain(request))

    async def status(self, run_ref: str) -> VmTaskReceipt:
        return await self._runner.status(run_ref)

    async def cancel(self, run_ref: str) -> VmTaskReceipt:
        return await self._runner.cancel(run_ref)


@dataclass(frozen=True, slots=True)
class ToolSandboxProfile:
    """Server-owned request envelope for external tool adapters such as MCP."""

    profile_id: str
    action_type_names: frozenset[str]
    allowed_modes: frozenset[Mode]
    max_argument_items: int
    max_argument_bytes: int
    max_tool_ref_bytes: int

    def __post_init__(self) -> None:
        if _PROFILE_ID.fullmatch(self.profile_id) is None:
            raise ValueError("tool sandbox profile_id MUST be lowercase ASCII")
        if not self.action_type_names or not self.allowed_modes:
            raise ValueError("tool sandbox allowlists MUST be non-empty")
        if not 0 <= self.max_argument_items <= 100:
            raise ValueError("tool sandbox max_argument_items MUST be in [0, 100]")
        if not 0 <= self.max_argument_bytes <= 5_000_000:
            raise ValueError("tool sandbox max_argument_bytes MUST be in [0, 5000000]")
        if not 1 <= self.max_tool_ref_bytes <= 8_192:
            raise ValueError("tool sandbox max_tool_ref_bytes MUST be in [1, 8192]")


class ToolSandboxCatalog:
    """Immutable tool registry with one profile owner per ActionType."""

    __slots__ = ("_profiles", "_profiles_by_action")

    def __init__(self, profiles: tuple[ToolSandboxProfile, ...] = ()) -> None:
        by_id: dict[str, ToolSandboxProfile] = {}
        by_action: dict[str, ToolSandboxProfile] = {}
        for profile in profiles:
            if profile.profile_id in by_id:
                raise SandboxPolicyError(f"duplicate tool sandbox profile {profile.profile_id!r}")
            by_id[profile.profile_id] = profile
            for action_type_name in profile.action_type_names:
                prior = by_action.get(action_type_name)
                if prior is not None:
                    raise SandboxPolicyError(
                        f"tool action {action_type_name!r} belongs to both "
                        f"{prior.profile_id!r} and {profile.profile_id!r}"
                    )
                by_action[action_type_name] = profile
        self._profiles = MappingProxyType(by_id)
        self._profiles_by_action = MappingProxyType(by_action)

    def register(self, profile: ToolSandboxProfile) -> ToolSandboxCatalog:
        return ToolSandboxCatalog((*self.list(), profile))

    def list(self) -> tuple[ToolSandboxProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))

    def require(self, action_type_name: str) -> ToolSandboxProfile:
        try:
            return self._profiles_by_action[action_type_name]
        except KeyError as exc:
            raise SandboxPolicyError(
                f"tool action {action_type_name!r} has no sandbox profile"
            ) from exc

    def constrain(self, request: ToolCallRequest) -> ToolCallRequest:
        profile = self.require(request.action_type_name)
        if request.mode not in profile.allowed_modes:
            raise SandboxPolicyError("tool mode is outside its sandbox profile")
        if len(request.arguments) > profile.max_argument_items:
            raise SandboxPolicyError("tool argument count is outside its sandbox profile")
        try:
            argument_bytes = len(
                json.dumps(
                    request.arguments,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            )
        except (TypeError, ValueError) as exc:
            raise SandboxPolicyError("tool arguments MUST be JSON serializable") from exc
        if argument_bytes > profile.max_argument_bytes:
            raise SandboxPolicyError("tool argument bytes are outside its sandbox profile")
        if len(request.tool_ref.encode("utf-8")) > profile.max_tool_ref_bytes:
            raise SandboxPolicyError("tool_ref bytes are outside its sandbox profile")
        return request


class ProfiledToolExecutor(ToolExecutor):
    """Enforce a tool sandbox profile immediately before adapter invocation."""

    def __init__(self, *, catalog: ToolSandboxCatalog, executor: ToolExecutor) -> None:
        self._catalog = catalog
        self._executor = executor

    async def execute(self, request: ToolCallRequest) -> ToolCallReceipt:
        return await self._executor.execute(self._catalog.constrain(request))


@dataclass(frozen=True, slots=True)
class ProgrammaticPipelineSandboxProfile:
    """Server-owned ceiling for reviewed read-only Python pipelines."""

    profile_id: str
    allowed_read_tools: frozenset[str]
    max_timeout_seconds: float
    max_input_items: int
    max_input_bytes: int
    max_tool_calls: int
    max_call_input_bytes: int
    max_call_output_bytes: int
    max_stdout_bytes: int
    max_stderr_bytes: int
    max_final_json_bytes: int

    def __post_init__(self) -> None:
        if _PROFILE_ID.fullmatch(self.profile_id) is None:
            raise ValueError("pipeline sandbox profile_id MUST be lowercase ASCII")
        if not self.allowed_read_tools:
            raise ValueError("pipeline sandbox allowed_read_tools MUST be non-empty")
        if not 0.1 <= self.max_timeout_seconds <= 300:
            raise ValueError("pipeline sandbox timeout MUST be in [0.1, 300]")
        if (
            min(
                self.max_input_items,
                self.max_input_bytes,
                self.max_tool_calls,
                self.max_call_input_bytes,
                self.max_call_output_bytes,
                self.max_stdout_bytes,
                self.max_stderr_bytes,
                self.max_final_json_bytes,
            )
            < 1
        ):
            raise ValueError("pipeline sandbox limits MUST be positive")


class ProgrammaticPipelineSandboxCatalog:
    """Immutable lookup and constraint surface for pipeline profiles."""

    def __init__(
        self,
        profiles: tuple[ProgrammaticPipelineSandboxProfile, ...] = (),
    ) -> None:
        by_id = {profile.profile_id: profile for profile in profiles}
        if len(by_id) != len(profiles):
            raise SandboxPolicyError("duplicate programmatic pipeline sandbox profile")
        self._profiles = MappingProxyType(by_id)

    def constrain(
        self,
        request: ProgrammaticToolPipelineRequest,
    ) -> ProgrammaticToolPipelineRequest:
        try:
            profile = self._profiles[request.sandbox_profile_id]
        except KeyError as exc:
            raise SandboxPolicyError("programmatic pipeline has no sandbox profile") from exc
        if not request.allowed_read_tools.issubset(profile.allowed_read_tools):
            raise SandboxPolicyError("pipeline tools are outside the sandbox profile")
        limits = request.limits
        checks = (
            (limits.timeout_seconds, profile.max_timeout_seconds, "timeout"),
            (limits.max_input_items, profile.max_input_items, "input count"),
            (limits.max_input_bytes, profile.max_input_bytes, "input bytes"),
            (limits.max_tool_calls, profile.max_tool_calls, "tool calls"),
            (limits.max_call_input_bytes, profile.max_call_input_bytes, "call input"),
            (limits.max_call_output_bytes, profile.max_call_output_bytes, "call output"),
            (limits.max_stdout_bytes, profile.max_stdout_bytes, "stdout"),
            (limits.max_stderr_bytes, profile.max_stderr_bytes, "stderr"),
            (limits.max_final_json_bytes, profile.max_final_json_bytes, "final JSON"),
        )
        for value, ceiling, label in checks:
            if value > ceiling:
                raise SandboxPolicyError(f"pipeline {label} exceeds its sandbox profile")
        return request


@dataclass(frozen=True, slots=True)
class DocumentConverterSandboxProfile:
    """Server-owned envelope for one or more binary document converters."""

    profile_id: str
    converter_ids: frozenset[str]
    allowed_suffixes: frozenset[str]
    max_input_bytes: int
    max_output_bytes: int

    def __post_init__(self) -> None:
        if _PROFILE_ID.fullmatch(self.profile_id) is None:
            raise ValueError("document converter sandbox profile_id MUST be lowercase ASCII")
        if not self.converter_ids or not self.allowed_suffixes:
            raise ValueError("document converter sandbox allowlists MUST be non-empty")
        if any(
            not suffix.startswith(".") or suffix != suffix.lower()
            for suffix in self.allowed_suffixes
        ):
            raise ValueError("document converter sandbox suffixes MUST be lowercase")
        if not 1 <= self.max_input_bytes <= 100_000_000:
            raise ValueError("document converter max_input_bytes MUST be in [1, 100000000]")
        if not 1 <= self.max_output_bytes <= 50_000_000:
            raise ValueError("document converter max_output_bytes MUST be in [1, 50000000]")


class DocumentConverterSandboxCatalog:
    """Immutable converter registry with one profile owner per converter id."""

    __slots__ = ("_profiles", "_profiles_by_converter")

    def __init__(self, profiles: tuple[DocumentConverterSandboxProfile, ...] = ()) -> None:
        by_id: dict[str, DocumentConverterSandboxProfile] = {}
        by_converter: dict[str, DocumentConverterSandboxProfile] = {}
        for profile in profiles:
            if profile.profile_id in by_id:
                raise SandboxPolicyError(
                    f"duplicate document converter sandbox profile {profile.profile_id!r}"
                )
            by_id[profile.profile_id] = profile
            for converter_id in profile.converter_ids:
                prior = by_converter.get(converter_id)
                if prior is not None:
                    raise SandboxPolicyError(
                        f"document converter {converter_id!r} belongs to both "
                        f"{prior.profile_id!r} and {profile.profile_id!r}"
                    )
                by_converter[converter_id] = profile
        self._profiles = MappingProxyType(by_id)
        self._profiles_by_converter = MappingProxyType(by_converter)

    def register(
        self,
        profile: DocumentConverterSandboxProfile,
    ) -> DocumentConverterSandboxCatalog:
        return DocumentConverterSandboxCatalog((*self.list(), profile))

    def list(self) -> tuple[DocumentConverterSandboxProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))

    def constrain(self, request: DocumentConversionRequest) -> DocumentConversionRequest:
        profile = self._profiles_by_converter.get(request.converter_id)
        if profile is None:
            raise SandboxPolicyError(
                f"document converter {request.converter_id!r} has no sandbox profile"
            )
        if request.source_suffix not in profile.allowed_suffixes:
            raise SandboxPolicyError("document suffix is outside its converter sandbox profile")
        if len(request.content) > profile.max_input_bytes:
            raise SandboxPolicyError("document input bytes are outside its sandbox profile")
        return replace(
            request,
            max_output_bytes=min(request.max_output_bytes, profile.max_output_bytes),
        )


class ProfiledDocumentConverter(DocumentConverter):
    """Enforce document conversion limits before and after adapter invocation."""

    def __init__(
        self,
        *,
        catalog: DocumentConverterSandboxCatalog,
        converter: DocumentConverter,
    ) -> None:
        self._catalog = catalog
        self._converter = converter

    async def convert(
        self,
        request: DocumentConversionRequest,
    ) -> DocumentConversionResult:
        constrained = self._catalog.constrain(request)
        result = await self._converter.convert(constrained)
        if len(result.text.encode("utf-8")) > constrained.max_output_bytes:
            raise SandboxPolicyError("document output bytes are outside its sandbox profile")
        return result


__all__ = [
    "DocumentConverterSandboxCatalog",
    "DocumentConverterSandboxProfile",
    "ProfiledCommandRunner",
    "ProfiledDocumentConverter",
    "ProfiledToolExecutor",
    "ProfiledVmTaskRunner",
    "ProgrammaticPipelineSandboxCatalog",
    "ProgrammaticPipelineSandboxProfile",
    "SandboxBackend",
    "SandboxPolicyError",
    "SandboxProfile",
    "SandboxProfileCatalog",
    "ToolSandboxCatalog",
    "ToolSandboxProfile",
    "VmTaskSandboxCatalog",
    "VmTaskSandboxProfile",
    "WorkspaceAccess",
]
