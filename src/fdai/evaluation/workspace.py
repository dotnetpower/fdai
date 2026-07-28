"""Policy broker for isolated task-scoped evaluation workspaces."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol, runtime_checkable

from fdai_evaluation_sdk import (
    ArtifactRef,
    ResourceLimits,
    WorkspaceCommandKind,
    WorkspaceCommandRequest,
    WorkspaceFile,
    WorkspaceIsolation,
    WorkspaceOperation,
    WorkspacePatchRequest,
    WorkspacePolicy,
    WorkspaceReceipt,
)

_SAFE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,299}$")


class WorkspacePolicyError(RuntimeError):
    """Workspace request violates the server-owned task policy."""


@runtime_checkable
class WorkspaceProvider(Protocol):
    """Private provider seam implemented by reviewed isolated runtimes."""

    async def open_task(
        self,
        *,
        session_id: str,
        task_id: str,
        policy: WorkspacePolicy,
        limits: ResourceLimits,
    ) -> WorkspaceIsolation: ...

    async def read_file(
        self,
        *,
        session_id: str,
        task_id: str,
        path: str,
        max_bytes: int,
    ) -> WorkspaceFile: ...

    async def apply_patch(
        self,
        *,
        session_id: str,
        task_id: str,
        request: WorkspacePatchRequest,
    ) -> WorkspaceReceipt: ...

    async def run(
        self,
        *,
        session_id: str,
        task_id: str,
        request: WorkspaceCommandRequest,
    ) -> WorkspaceReceipt: ...

    async def close_task(self, *, session_id: str, task_id: str) -> None: ...


@runtime_checkable
class WorkspaceAuditSink(Protocol):
    async def append(self, record: Mapping[str, str]) -> None: ...


class InMemoryWorkspaceAuditSink:
    def __init__(self) -> None:
        self.records: list[Mapping[str, str]] = []
        self._lock = asyncio.Lock()

    async def append(self, record: Mapping[str, str]) -> None:
        async with self._lock:
            self.records.append(dict(record))


@dataclass(frozen=True, slots=True)
class WorkspaceBrokerPolicy:
    """Server-reviewed profiles and read bounds for one session."""

    workspace_policy: WorkspacePolicy
    resource_limits: ResourceLimits
    build_profiles: frozenset[str]
    test_profiles: frozenset[str]
    max_read_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_read_bytes < 1:
            raise ValueError("max_read_bytes MUST be positive")


class EvaluationWorkspaceBroker:
    """Expose a verified provider through the neutral EvaluationWorkspace API."""

    def __init__(
        self,
        *,
        session_id: str,
        task_id: str,
        provider: WorkspaceProvider,
        audit_sink: WorkspaceAuditSink,
        policy: WorkspaceBrokerPolicy,
    ) -> None:
        self._session_id = session_id
        self._task_id = task_id
        self._provider = provider
        self._audit_sink = audit_sink
        self._policy = policy
        self._opened = False
        self._closed = False
        self._operation_lock = asyncio.Lock()

    async def open(self) -> None:
        isolation = await self._provider.open_task(
            session_id=self._session_id,
            task_id=self._task_id,
            policy=self._policy.workspace_policy,
            limits=self._policy.resource_limits,
        )
        if not isolation.verified:
            await self._audit("open", "isolation_rejected")
            await self._provider.close_task(
                session_id=self._session_id,
                task_id=self._task_id,
            )
            raise WorkspacePolicyError("workspace provider isolation could not be verified")
        self._opened = True
        await self._audit("open", "accepted")

    async def read_file(self, path: str) -> WorkspaceFile:
        self._require_operation(WorkspaceOperation.READ)
        _validate_workspace_path(path)
        async with self._operation_lock:
            try:
                result = await self._provider.read_file(
                    session_id=self._session_id,
                    task_id=self._task_id,
                    path=path,
                    max_bytes=self._policy.max_read_bytes,
                )
            except BaseException:
                await self._audit("read", "failed")
                raise
        if result.path != path or len(result.content) != result.size_bytes:
            await self._audit("read", "invalid_receipt")
            raise WorkspacePolicyError("workspace provider returned an invalid file receipt")
        await self._audit("read", "completed")
        return result

    async def apply_patch(self, request: WorkspacePatchRequest) -> WorkspaceReceipt:
        self._require_operation(WorkspaceOperation.EDIT)
        self._require_patch_scope(request.patch_artifact)
        return await self._run_provider_operation(
            "apply_patch",
            self._provider.apply_patch(
                session_id=self._session_id,
                task_id=self._task_id,
                request=request,
            ),
        )

    async def run_build(self, request: WorkspaceCommandRequest) -> WorkspaceReceipt:
        self._require_operation(WorkspaceOperation.BUILD)
        self._require_command(request, WorkspaceCommandKind.BUILD, self._policy.build_profiles)
        return await self._run_provider_operation(
            "build",
            self._provider.run(
                session_id=self._session_id,
                task_id=self._task_id,
                request=request,
            ),
        )

    async def run_tests(self, request: WorkspaceCommandRequest) -> WorkspaceReceipt:
        self._require_operation(WorkspaceOperation.TEST)
        self._require_command(request, WorkspaceCommandKind.TEST, self._policy.test_profiles)
        return await self._run_provider_operation(
            "test",
            self._provider.run(
                session_id=self._session_id,
                task_id=self._task_id,
                request=request,
            ),
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._provider.close_task(
                session_id=self._session_id,
                task_id=self._task_id,
            )
        finally:
            await self._audit("close", "completed")

    async def _run_provider_operation(
        self,
        operation: str,
        awaitable: Awaitable[WorkspaceReceipt],
    ) -> WorkspaceReceipt:
        async with self._operation_lock:
            try:
                receipt = await awaitable
            except BaseException:
                await self._audit(operation, "failed")
                raise
        await self._audit(operation, "completed")
        return receipt

    def _require_operation(self, operation: WorkspaceOperation) -> None:
        if not self._opened or self._closed:
            raise WorkspacePolicyError("workspace is not open")
        if operation not in self._policy.workspace_policy.operations:
            raise WorkspacePolicyError(f"workspace operation {operation.value!r} is not allowed")

    def _require_patch_scope(self, artifact: ArtifactRef) -> None:
        if artifact.session_id != self._session_id or artifact.task_id != self._task_id:
            raise WorkspacePolicyError("patch artifact belongs to another task or session")
        if artifact.media_type != "text/x-diff":
            raise WorkspacePolicyError("patch artifact MUST use text/x-diff")

    def _require_command(
        self,
        request: WorkspaceCommandRequest,
        expected: WorkspaceCommandKind,
        profiles: frozenset[str],
    ) -> None:
        if request.kind is not expected or request.profile_id not in profiles:
            raise WorkspacePolicyError(
                "workspace command profile is not reviewed for this operation"
            )
        requested = request.limits
        ceiling = self._policy.resource_limits
        if any(
            requested_value > ceiling_value
            for requested_value, ceiling_value in (
                (requested.cpu_seconds, ceiling.cpu_seconds),
                (requested.memory_bytes, ceiling.memory_bytes),
                (requested.process_count, ceiling.process_count),
                (requested.output_bytes, ceiling.output_bytes),
                (requested.wall_clock_seconds, ceiling.wall_clock_seconds),
            )
        ):
            raise WorkspacePolicyError("workspace command exceeds its resource limits")

    async def _audit(self, operation: str, outcome: str) -> None:
        await self._audit_sink.append(
            {
                "session_id": self._session_id,
                "task_id": self._task_id,
                "side_effect_class": "workspace",
                "operation": operation,
                "outcome": outcome,
            }
        )


def _validate_workspace_path(value: str) -> None:
    path = PurePosixPath(value)
    raw_parts = value.split("/")
    if (
        _SAFE_PATH.fullmatch(value) is None
        or path.is_absolute()
        or ".." in raw_parts
        or "." in raw_parts
    ):
        raise WorkspacePolicyError("workspace path MUST be bounded and task-root relative")


__all__ = [
    "EvaluationWorkspaceBroker",
    "InMemoryWorkspaceAuditSink",
    "WorkspaceAuditSink",
    "WorkspaceBrokerPolicy",
    "WorkspacePolicyError",
    "WorkspaceProvider",
]
