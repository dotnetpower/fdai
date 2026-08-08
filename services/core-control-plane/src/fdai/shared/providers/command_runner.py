"""Provider-neutral execution contract for catalog-resolved commands."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class CommandExecutionClass(StrEnum):
    LOCAL_READ = "local_read"
    WORKSPACE_WRITE = "workspace_write"
    CLOUD_READ = "cloud_read"


class CommandNetworkProfile(StrEnum):
    NONE = "none"
    AZURE_CONTROL_PLANE = "azure_control_plane"


class CommandOutputFormat(StrEnum):
    JSON = "json"
    TEXT = "text"


class CommandStatus(StrEnum):
    PLANNED = "planned"
    SUCCEEDED = "succeeded"
    ALREADY_APPLIED = "already_applied"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class CommandPlan:
    """One immutable argv plan produced by the trusted command catalog."""

    command_id: str
    command_version: int
    idempotency_key: str
    executable_ref: str
    argv: tuple[str, ...]
    execution_class: CommandExecutionClass
    network_profile: CommandNetworkProfile
    output_format: CommandOutputFormat
    timeout_seconds: int
    max_output_bytes: int
    dry_run: bool = True
    credential_profile: str | None = None
    workspace_ref: str | None = None

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.command_id):
            raise ValueError("command_id MUST be a lowercase dotted identifier")
        if self.command_version < 1:
            raise ValueError("command_version MUST be positive")
        if not self.idempotency_key or len(self.idempotency_key) > 200:
            raise ValueError("idempotency_key MUST be a bounded non-empty string")
        if not _IDENTIFIER.fullmatch(self.executable_ref):
            raise ValueError("executable_ref MUST be a lowercase dotted identifier")
        if any(not value or "\x00" in value for value in self.argv):
            raise ValueError("argv entries MUST be non-empty and NUL-free")
        if not 1 <= self.timeout_seconds <= 900:
            raise ValueError("timeout_seconds MUST be in [1, 900]")
        if not 1 <= self.max_output_bytes <= 5_000_000:
            raise ValueError("max_output_bytes MUST be in [1, 5000000]")
        if self.credential_profile is not None and not _IDENTIFIER.fullmatch(
            self.credential_profile
        ):
            raise ValueError("credential_profile MUST be a lowercase dotted identifier")
        if self.workspace_ref is not None and (
            not self.workspace_ref or len(self.workspace_ref) > 256
        ):
            raise ValueError("workspace_ref MUST be bounded when set")


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    """Terminal or planned result from a command runner."""

    status: CommandStatus
    receipt_ref: str
    exit_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_ms: int = 0
    already_existed: bool = False


@dataclass(frozen=True, slots=True)
class CommandOutput:
    """Ephemeral full output for a typed consumer; never persist or log it."""

    receipt: CommandReceipt
    stdout: str = field(default="", repr=False)


@runtime_checkable
class CommandRunner(Protocol):
    """Execute only a plan already resolved by the trusted catalog."""

    async def execute(self, plan: CommandPlan) -> CommandReceipt: ...


@runtime_checkable
class CommandOutputRunner(CommandRunner, Protocol):
    """Run a typed command and return its bounded full output separately."""

    async def execute_with_output(self, plan: CommandPlan) -> CommandOutput: ...


__all__ = [
    "CommandExecutionClass",
    "CommandNetworkProfile",
    "CommandOutput",
    "CommandOutputFormat",
    "CommandOutputRunner",
    "CommandPlan",
    "CommandReceipt",
    "CommandRunner",
    "CommandStatus",
]
