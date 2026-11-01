"""Public contracts for isolated task-scoped evaluation workspaces."""

from __future__ import annotations

from enum import StrEnum
from hashlib import sha256 as _sha256
from typing import Protocol, runtime_checkable

from pydantic import Field, model_validator

from fdai_evaluation_sdk._validation import Identifier, Sha256Digest
from fdai_evaluation_sdk.contracts import (
    ArtifactRef,
    ContractModel,
    ResourceLimits,
    _require_unique,
)


class WorkspaceCommandKind(StrEnum):
    """Reviewed command classes. Raw command strings are not part of the API."""

    BUILD = "build"
    TEST = "test"


class WorkspaceCommandStatus(StrEnum):
    """Terminal result of one reviewed workspace operation."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"


class WorkspaceIsolation(ContractModel):
    """Provider evidence required before FDAI exposes a task workspace."""

    isolated_task_root: bool
    path_escape_blocked: bool
    symlink_escape_blocked: bool
    credentials_absent: bool
    network_denied: bool
    ephemeral: bool

    @property
    def verified(self) -> bool:
        return all(
            (
                self.isolated_task_root,
                self.path_escape_blocked,
                self.symlink_escape_blocked,
                self.credentials_absent,
                self.network_denied,
                self.ephemeral,
            )
        )


class WorkspaceFile(ContractModel):
    """Digest-verified bounded file returned from a task workspace."""

    path: Identifier
    size_bytes: int = Field(ge=0, le=1_073_741_824)
    sha256: Sha256Digest
    content: bytes = Field(repr=False, max_length=1_073_741_824)

    @model_validator(mode="after")
    def _validate_content_integrity(self) -> WorkspaceFile:
        if self.size_bytes != len(self.content):
            raise ValueError("WorkspaceFile size_bytes MUST match content length")
        if self.sha256 != _sha256(self.content).hexdigest():
            raise ValueError("WorkspaceFile sha256 MUST match content digest")
        return self


class WorkspacePatchRequest(ContractModel):
    """Apply one declared patch artifact to a task-scoped workspace."""

    patch_artifact: ArtifactRef
    expected_workspace_digest: Sha256Digest


class WorkspaceCommandRequest(ContractModel):
    """Invoke one server-reviewed build or test profile."""

    kind: WorkspaceCommandKind
    profile_id: Identifier
    limits: ResourceLimits


class WorkspaceReceipt(ContractModel):
    """Auditable result of a patch, build, or test operation."""

    operation: Identifier
    status: WorkspaceCommandStatus
    workspace_digest: Sha256Digest
    output_artifacts: tuple[ArtifactRef, ...] = ()
    audit_ref: Identifier
    exit_code: int | None = Field(default=None, ge=0, le=255)

    @model_validator(mode="after")
    def _validate_output_artifacts(self) -> WorkspaceReceipt:
        _require_unique(
            self.output_artifacts, key=lambda item: item.artifact_id, label="output_artifacts"
        )
        return self


@runtime_checkable
class EvaluationWorkspace(Protocol):
    """Task-scoped workspace with no host path or raw shell surface."""

    async def read_file(self, path: str) -> WorkspaceFile: ...

    async def apply_patch(self, request: WorkspacePatchRequest) -> WorkspaceReceipt: ...

    async def run_build(self, request: WorkspaceCommandRequest) -> WorkspaceReceipt: ...

    async def run_tests(self, request: WorkspaceCommandRequest) -> WorkspaceReceipt: ...

    async def close(self) -> None: ...


__all__ = [
    "EvaluationWorkspace",
    "WorkspaceCommandKind",
    "WorkspaceCommandRequest",
    "WorkspaceCommandStatus",
    "WorkspaceFile",
    "WorkspaceIsolation",
    "WorkspacePatchRequest",
    "WorkspaceReceipt",
]
