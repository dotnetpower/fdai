"""Strict contract tests for the independently packaged evaluation SDK."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fdai_evaluation_sdk import (
    ArtifactPolicy,
    ArtifactRef,
    ArtifactSpec,
    AuthorityCeiling,
    Capability,
    EvaluationRequest,
    EvaluationStatus,
    EvaluationTask,
    MetadataEntry,
    NetworkPolicy,
    ResourceLimits,
    SideEffectClass,
    TargetRef,
    WorkspaceOperation,
    WorkspacePolicy,
)

_NOW = datetime(2026, 7, 29, tzinfo=UTC)
_DIGEST = "a" * 64


def _artifact(**overrides: object) -> ArtifactRef:
    values: dict[str, object] = {
        "artifact_id": "artifact-1",
        "session_id": "session-1",
        "task_id": "task-1",
        "name": "crash-log",
        "media_type": "text/plain",
        "size_bytes": 12,
        "sha256": _DIGEST,
        "expires_at": _NOW + timedelta(hours=1),
    }
    values.update(overrides)
    return ArtifactRef.model_validate(values)


def _request(**overrides: object) -> EvaluationRequest:
    values: dict[str, object] = {
        "session_id": "session-1",
        "requester_id": "driver-1",
        "purpose": "Evaluate a bounded source-repair task.",
        "requested_capabilities": (
            Capability(
                capability_id="workspace.read",
                side_effect_class=SideEffectClass.WORKSPACE,
            ),
        ),
        "authority_ceiling": AuthorityCeiling.SHADOW,
        "task_count_limit": 2,
        "concurrency_limit": 1,
        "deadline": _NOW + timedelta(hours=1),
        "workspace_policy": WorkspacePolicy(operations=(WorkspaceOperation.READ,)),
        "artifact_policy": ArtifactPolicy(
            allowed_media_types=("text/plain", "application/octet-stream"),
            max_artifact_bytes=1_024,
        ),
        "network_policy": NetworkPolicy(),
    }
    values.update(overrides)
    return EvaluationRequest.model_validate(values)


def _task(**overrides: object) -> EvaluationTask:
    values: dict[str, object] = {
        "session_id": "session-1",
        "task_id": "task-1",
        "phase": "patch",
        "objective": "Produce a bounded source patch.",
        "target": TargetRef(kind="workspace", value="source-1"),
        "input_artifacts": (_artifact(),),
        "expected_outputs": (
            ArtifactSpec(name="fix.patch", media_type="text/x-diff", max_bytes=4_096),
        ),
        "requested_capabilities": (
            Capability(
                capability_id="workspace.edit",
                side_effect_class=SideEffectClass.WORKSPACE,
            ),
        ),
        "deadline": _NOW + timedelta(minutes=30),
        "resource_limits": ResourceLimits(
            cpu_seconds=60,
            memory_bytes=268_435_456,
            process_count=16,
            output_bytes=1_048_576,
            wall_clock_seconds=120,
        ),
        "metadata": (MetadataEntry(key="mode", value="patch-only"),),
    }
    values.update(overrides)
    return EvaluationTask.model_validate(values)


def test_request_is_deeply_immutable_and_schema_serializable() -> None:
    request = _request()

    with pytest.raises(ValidationError, match="frozen"):
        request.task_count_limit = 3
    with pytest.raises(TypeError):
        request.requested_capabilities[0] = Capability(  # type: ignore[index]
            capability_id="workspace.edit",
            side_effect_class=SideEffectClass.WORKSPACE,
        )
    schema = EvaluationRequest.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["task_count_limit"]["maximum"] == 10_000


def test_contracts_reject_unknown_fields_and_coercion() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _request(executor_override="untrusted")
    with pytest.raises(ValidationError):
        _request(concurrency_limit="1")


def test_request_rejects_duplicate_capability_identity() -> None:
    capability = Capability(
        capability_id="workspace.read",
        side_effect_class=SideEffectClass.WORKSPACE,
    )
    with pytest.raises(ValidationError, match="capabilities MUST be unique"):
        _request(requested_capabilities=(capability, capability))


def test_network_policy_is_deny_by_default() -> None:
    with pytest.raises(ValidationError):
        NetworkPolicy(deny_by_default=False)


def test_task_rejects_cross_session_artifact() -> None:
    with pytest.raises(ValidationError, match="belong to the task session"):
        _task(input_artifacts=(_artifact(session_id="session-2"),))


def test_task_rejects_duplicate_declared_output() -> None:
    output = ArtifactSpec(name="fix.patch", media_type="text/x-diff", max_bytes=4_096)
    with pytest.raises(ValidationError, match="outputs MUST be unique"):
        _task(expected_outputs=(output, output))


@pytest.mark.parametrize(
    "overrides",
    (
        {"sha256": "not-a-digest"},
        {"media_type": "invalid"},
        {"expires_at": datetime(2026, 7, 29)},
        {"size_bytes": 1_073_741_825},
    ),
)
def test_artifact_reference_rejects_invalid_custody_fields(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _artifact(**overrides)


def test_objective_rejects_format_characters() -> None:
    with pytest.raises(ValidationError, match="control or format"):
        _task(objective="Repair spoof\u202etext")


def test_status_vocabulary_is_benchmark_neutral() -> None:
    assert tuple(status.value for status in EvaluationStatus) == ("completed", "held", "failed")
