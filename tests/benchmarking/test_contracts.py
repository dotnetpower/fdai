"""Tests for brand-neutral benchmark boundary values."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from fdai.benchmarking import BenchmarkStatus, BenchmarkSubmission, BenchmarkTask


def _task(**overrides: object) -> BenchmarkTask:
    values: dict[str, object] = {
        "run_id": "run-1",
        "task_id": "task-1",
        "stage": "diagnosis",
        "objective": "Identify the cause of the service failure.",
        "target_ref": "service/example",
        "metadata": {"suite": "example-lite"},
    }
    values.update(overrides)
    return BenchmarkTask(**values)  # type: ignore[arg-type]


def test_task_is_immutable_and_brand_neutral() -> None:
    source = {"suite": "example-lite"}
    task = _task(metadata=source)

    assert task.stage == "diagnosis"
    assert task.metadata == {"suite": "example-lite"}
    source["suite"] = "changed"
    assert task.metadata == {"suite": "example-lite"}
    with pytest.raises(FrozenInstanceError):
        task.stage = "mitigation"  # type: ignore[misc]
    with pytest.raises(TypeError):
        task.metadata["suite"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", "   "),
        ("task_id", "task\n2"),
        ("stage", "x" * 257),
        ("target_ref", ""),
        ("objective", "   "),
    ],
)
def test_task_rejects_invalid_boundary_text(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        _task(**{field: value})


def test_submission_preserves_task_identity_and_evidence() -> None:
    submission = BenchmarkSubmission(
        run_id="run-1",
        task_id="task-1",
        stage="diagnosis",
        status=BenchmarkStatus.COMPLETED,
        summary="The dependency endpoint is unavailable.",
        evidence_refs=("audit/example-1",),
        audit_ref="audit/example-1",
    )

    assert submission.status is BenchmarkStatus.COMPLETED
    assert submission.evidence_refs == ("audit/example-1",)


def test_metadata_is_bounded() -> None:
    with pytest.raises(ValueError, match="at most 64"):
        _task(metadata={f"key-{index}": "value" for index in range(65)})
