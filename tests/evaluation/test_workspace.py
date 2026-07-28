"""Workspace policy, isolation, auditing, and cleanup tests."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fdai_evaluation_sdk import (
    ArtifactRef,
    ResourceLimits,
    WorkspaceCommandKind,
    WorkspaceCommandRequest,
    WorkspaceCommandStatus,
    WorkspaceFile,
    WorkspaceIsolation,
    WorkspaceOperation,
    WorkspacePatchRequest,
    WorkspacePolicy,
    WorkspaceReceipt,
)

from fdai.evaluation.workspace import (
    EvaluationWorkspaceBroker,
    InMemoryWorkspaceAuditSink,
    WorkspaceBrokerPolicy,
    WorkspacePolicyError,
)

_NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
_DIGEST = "a" * 64


def _limits(**overrides: int) -> ResourceLimits:
    values = {
        "cpu_seconds": 60,
        "memory_bytes": 268_435_456,
        "process_count": 16,
        "output_bytes": 1_048_576,
        "wall_clock_seconds": 120,
    }
    values.update(overrides)
    return ResourceLimits(**values)


class _Provider:
    def __init__(self, *, isolation: WorkspaceIsolation | None = None) -> None:
        self.isolation = isolation or WorkspaceIsolation(
            isolated_task_root=True,
            path_escape_blocked=True,
            symlink_escape_blocked=True,
            credentials_absent=True,
            network_denied=True,
            ephemeral=True,
        )
        self.closed = 0
        self.runs: list[WorkspaceCommandRequest] = []

    async def open_task(self, **_: object) -> WorkspaceIsolation:
        return self.isolation

    async def read_file(self, *, path: str, **_: object) -> WorkspaceFile:
        content = b"source"
        return WorkspaceFile(
            path=path,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            content=content,
        )

    async def apply_patch(self, **_: object) -> WorkspaceReceipt:
        return _receipt("apply_patch")

    async def run(self, *, request: WorkspaceCommandRequest, **_: object) -> WorkspaceReceipt:
        self.runs.append(request)
        return _receipt(request.kind.value)

    async def close_task(self, **_: object) -> None:
        self.closed += 1


def _receipt(operation: str) -> WorkspaceReceipt:
    return WorkspaceReceipt(
        operation=operation,
        status=WorkspaceCommandStatus.SUCCEEDED,
        workspace_digest=_DIGEST,
        audit_ref=f"workspace/{operation}",
        exit_code=0,
    )


def _broker(provider: _Provider | None = None):  # type: ignore[no-untyped-def]
    resolved = provider or _Provider()
    audit = InMemoryWorkspaceAuditSink()
    broker = EvaluationWorkspaceBroker(
        session_id="session-1",
        task_id="task-1",
        provider=resolved,
        audit_sink=audit,
        policy=WorkspaceBrokerPolicy(
            workspace_policy=WorkspacePolicy(
                operations=tuple(WorkspaceOperation),
            ),
            resource_limits=_limits(),
            build_profiles=frozenset({"build.default"}),
            test_profiles=frozenset({"test.default"}),
        ),
    )
    return broker, resolved, audit


async def test_rejects_unverified_isolation_and_cleans_provider() -> None:
    provider = _Provider(
        isolation=WorkspaceIsolation(
            isolated_task_root=True,
            path_escape_blocked=True,
            symlink_escape_blocked=False,
            credentials_absent=True,
            network_denied=True,
            ephemeral=True,
        )
    )
    broker, _, audit = _broker(provider)

    with pytest.raises(WorkspacePolicyError, match="isolation"):
        await broker.open()

    assert provider.closed == 1
    assert audit.records[-1]["outcome"] == "isolation_rejected"


@pytest.mark.parametrize("path", ("../secret", "/etc/passwd", "dir/./file", "dir\\file"))
async def test_rejects_path_escape_before_provider(path: str) -> None:
    broker, _, _ = _broker()
    await broker.open()

    with pytest.raises(WorkspacePolicyError, match="task-root relative"):
        await broker.read_file(path)


async def test_allows_only_reviewed_command_profiles_within_limits() -> None:
    broker, provider, audit = _broker()
    await broker.open()
    build = WorkspaceCommandRequest(
        kind=WorkspaceCommandKind.BUILD,
        profile_id="build.default",
        limits=_limits(),
    )

    receipt = await broker.run_build(build)

    assert receipt.status is WorkspaceCommandStatus.SUCCEEDED
    assert provider.runs == [build]
    assert audit.records[-1]["side_effect_class"] == "workspace"
    with pytest.raises(WorkspacePolicyError, match="not reviewed"):
        await broker.run_build(build.model_copy(update={"profile_id": "shell.raw"}))
    with pytest.raises(WorkspacePolicyError, match="resource limits"):
        await broker.run_build(build.model_copy(update={"limits": _limits(cpu_seconds=61)}))


async def test_patch_reference_must_be_task_scoped_diff() -> None:
    broker, _, _ = _broker()
    await broker.open()
    artifact = ArtifactRef(
        artifact_id=f"sha256:{_DIGEST}",
        session_id="session-2",
        task_id="task-1",
        name="fix.patch",
        media_type="text/x-diff",
        size_bytes=10,
        sha256=_DIGEST,
        expires_at=_NOW + timedelta(minutes=1),
    )

    with pytest.raises(WorkspacePolicyError, match="another task or session"):
        await broker.apply_patch(
            WorkspacePatchRequest(
                patch_artifact=artifact,
                expected_workspace_digest=_DIGEST,
            )
        )


async def test_cancellation_audits_failure_and_close_is_idempotent() -> None:
    class _CancellingProvider(_Provider):
        async def run(self, **_: object) -> WorkspaceReceipt:
            raise asyncio.CancelledError

    broker, provider, audit = _broker(_CancellingProvider())
    await broker.open()
    request = WorkspaceCommandRequest(
        kind=WorkspaceCommandKind.TEST,
        profile_id="test.default",
        limits=_limits(),
    )

    with pytest.raises(asyncio.CancelledError):
        await broker.run_tests(request)
    await broker.close()
    await broker.close()

    assert provider.closed == 1
    assert [record["outcome"] for record in audit.records[-2:]] == ["failed", "completed"]
