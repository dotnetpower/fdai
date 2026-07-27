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
        ("task_id", "task\x7f2"),
        ("stage", "x" * 257),
        ("target_ref", ""),
        ("objective", "   "),
        ("objective", "spoof\u202etext"),
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


def test_submission_rejects_invalid_runtime_status() -> None:
    with pytest.raises(ValueError, match="status MUST be a BenchmarkStatus"):
        BenchmarkSubmission(
            run_id="run-1",
            task_id="task-1",
            stage="diagnosis",
            status="bogus",  # type: ignore[arg-type]
            summary="Evidence-backed result.",
        )


def test_metadata_is_bounded() -> None:
    with pytest.raises(ValueError, match="at most 64"):
        _task(metadata={f"key-{index}": "value" for index in range(65)})


def test_submission_evidence_refs_are_bounded() -> None:
    with pytest.raises(ValueError, match="at most 256"):
        BenchmarkSubmission(
            run_id="run-1",
            task_id="task-1",
            stage="diagnosis",
            status=BenchmarkStatus.COMPLETED,
            summary="Evidence-backed result.",
            evidence_refs=tuple(f"audit/{index}" for index in range(257)),
        )


def test_submission_accepts_evidence_ref_limit() -> None:
    submission = BenchmarkSubmission(
        run_id="run-1",
        task_id="task-1",
        stage="diagnosis",
        status=BenchmarkStatus.COMPLETED,
        summary="Evidence-backed result.",
        evidence_refs=tuple(f"audit/{index}" for index in range(256)),
    )

    assert len(submission.evidence_refs) == 256


def test_submission_freezes_evidence_refs() -> None:
    evidence_refs = ["audit/1"]

    submission = BenchmarkSubmission(
        run_id="run-1",
        task_id="task-1",
        stage="diagnosis",
        status=BenchmarkStatus.COMPLETED,
        summary="Evidence-backed result.",
        evidence_refs=evidence_refs,  # type: ignore[arg-type]
    )
    evidence_refs.extend(f"audit/{index}" for index in range(2, 300))

    assert submission.evidence_refs == ("audit/1",)
