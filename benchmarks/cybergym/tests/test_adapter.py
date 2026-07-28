"""CyberGym e2e, patch-only, artifact, and hidden-oracle boundary tests."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from fdai_evaluation_sdk import (
    EVALUATION_API_VERSION,
    ArtifactRef,
    AuthorityCeiling,
    DecisionReceipt,
    EvaluationResult,
    EvaluationRunner,
    EvaluationStatus,
    QualityGateStatus,
)

from fdai_bench_cybergym import (
    CyberGymAdapter,
    CyberGymAdapterError,
    CyberGymMode,
    CyberGymTaskConfig,
    external_validation_receipt,
)

_NOW = datetime(2026, 7, 29, tzinfo=UTC)


def _artifact(
    name: str,
    media_type: str,
    *,
    size_bytes: int = 10,
    session_id: str = "session-1",
    task_id: str = "task-1",
) -> ArtifactRef:
    digest = sha256(name.encode()).hexdigest()
    return ArtifactRef(
        artifact_id=f"sha256:{digest}",
        session_id=session_id,
        task_id=task_id,
        name=name,
        media_type=media_type,
        size_bytes=size_bytes,
        sha256=digest,
        expires_at=_NOW + timedelta(hours=1),
        executable=name == "poc.bin",
    )


def _result(task, outputs: tuple[ArtifactRef, ...]) -> EvaluationResult:  # type: ignore[no-untyped-def]
    return EvaluationResult(
        session_id=task.session_id,
        task_id=task.task_id,
        phase=task.phase,
        status=EvaluationStatus.COMPLETED,
        summary="Bounded source repair artifacts were published.",
        output_artifacts=outputs,
        terminal_audit_ref="audit/result",
        decision_receipt=DecisionReceipt(
            selected_tier="t2",
            control_loop_outcome="executed",
            decision="patch",
            autonomy_mode=AuthorityCeiling.SHADOW,
            verifier_passed=True,
            quality_gate_status=QualityGateStatus.PASSED,
            authority_ceiling=AuthorityCeiling.SHADOW,
        ),
    )


async def test_e2e_declares_only_source_input_and_bounded_poc_and_patch_outputs() -> None:
    adapter = CyberGymAdapter(
        CyberGymTaskConfig(
            session_id="session-1",
            task_id="task-1",
            mode=CyberGymMode.E2E,
            source_workspace_ref="workspace-1",
            deadline=_NOW + timedelta(hours=1),
        )
    )

    request = await adapter.start()
    task = await adapter.next_task()
    assert task is not None
    assert task.input_artifacts == ()
    assert [(item.name, item.media_type) for item in task.expected_outputs] == [
        ("poc.bin", "application/octet-stream"),
        ("fix.patch", "text/x-diff"),
    ]
    assert request.workspace_policy.operations
    assert request.authority_ceiling is AuthorityCeiling.SHADOW

    outputs = (
        _artifact("poc.bin", "application/octet-stream"),
        _artifact("fix.patch", "text/x-diff"),
    )
    await adapter.submit(_result(task, outputs))
    assert await adapter.next_task() is None


async def test_patch_only_requires_public_crash_log_and_poc_and_outputs_patch() -> None:
    crash_log = _artifact("crash.log", "text/plain")
    supplied_poc = _artifact("input-poc.bin", "application/octet-stream")
    adapter = CyberGymAdapter(
        CyberGymTaskConfig(
            session_id="session-1",
            task_id="task-1",
            mode=CyberGymMode.PATCH_ONLY,
            source_workspace_ref="workspace-1",
            crash_log=crash_log,
            supplied_poc=supplied_poc,
            deadline=_NOW + timedelta(hours=1),
        )
    )

    await adapter.start()
    task = await adapter.next_task()
    assert task is not None
    assert task.input_artifacts == (crash_log, supplied_poc)
    assert tuple(item.name for item in task.expected_outputs) == ("fix.patch",)
    await adapter.submit(_result(task, (_artifact("fix.patch", "text/x-diff"),)))


def test_hidden_ground_truth_has_no_adapter_contract_field() -> None:
    names = {field.name for field in fields(CyberGymTaskConfig)}
    assert not names.intersection({"oracle", "grader", "ground_truth_poc", "hidden_tests"})


def test_e2e_rejects_benchmark_poc_input() -> None:
    with pytest.raises(ValueError, match="only the source workspace"):
        CyberGymTaskConfig(
            session_id="session-1",
            task_id="task-1",
            mode=CyberGymMode.E2E,
            source_workspace_ref="workspace-1",
            supplied_poc=_artifact("input-poc.bin", "application/octet-stream"),
            deadline=_NOW + timedelta(hours=1),
        )


async def test_rejects_missing_or_oversized_declared_output() -> None:
    adapter = CyberGymAdapter(
        CyberGymTaskConfig(
            session_id="session-1",
            task_id="task-1",
            mode=CyberGymMode.PATCH_ONLY,
            source_workspace_ref="workspace-1",
            crash_log=_artifact("crash.log", "text/plain"),
            supplied_poc=_artifact("input-poc.bin", "application/octet-stream"),
            deadline=_NOW + timedelta(hours=1),
            max_patch_bytes=16,
        )
    )
    await adapter.start()
    task = await adapter.next_task()
    assert task is not None
    with pytest.raises(CyberGymAdapterError, match="exactly declared"):
        await adapter.submit(_result(task, ()))
    with pytest.raises(CyberGymAdapterError, match="violates"):
        await adapter.submit(_result(task, (_artifact("fix.patch", "text/x-diff", size_bytes=17),)))


def test_four_stage_validation_receipt_is_untrusted_and_task_scoped() -> None:
    receipts = tuple(
        _artifact(f"validation-{index}.json", "application/json") for index in range(4)
    )

    receipt = external_validation_receipt(
        session_id="session-1",
        task_id="task-1",
        stage_receipts=receipts,
    )

    assert receipt.trusted_for_execution is False
    assert tuple(stage.stage_id for stage in receipt.stages) == (
        "agent_poc_crashes_unpatched",
        "agent_poc_stopped_by_patch",
        "project_tests_pass",
        "ground_truth_poc_stopped_by_patch",
    )
    with pytest.raises(CyberGymAdapterError, match="exactly four"):
        external_validation_receipt(
            session_id="session-1",
            task_id="task-1",
            stage_receipts=receipts[:3],
        )


@pytest.mark.parametrize("mode", (CyberGymMode.E2E, CyberGymMode.PATCH_ONLY))
async def test_mode_runs_one_task_through_generic_sdk_runner(mode: CyberGymMode) -> None:
    inputs = (
        {
            "crash_log": _artifact("crash.log", "text/plain"),
            "supplied_poc": _artifact("input-poc.bin", "application/octet-stream"),
        }
        if mode is CyberGymMode.PATCH_ONLY
        else {}
    )
    adapter = CyberGymAdapter(
        CyberGymTaskConfig(
            session_id="session-1",
            task_id="task-1",
            mode=mode,
            source_workspace_ref="workspace-1",
            deadline=_NOW + timedelta(hours=1),
            **inputs,
        )
    )

    class _Session:
        session_id = "session-1"

        async def execute(self, task):  # type: ignore[no-untyped-def]
            outputs = tuple(
                _artifact(spec.name, spec.media_type, size_bytes=min(10, spec.max_bytes))
                for spec in task.expected_outputs
            )
            return _result(task, outputs)

        async def close(self) -> None:
            return None

    class _Host:
        api_version = EVALUATION_API_VERSION

        async def open(self, request):  # type: ignore[no-untyped-def]
            assert request.session_id == "session-1"
            return _Session()

        async def record_external_validation(self, receipt) -> None:  # type: ignore[no-untyped-def]
            return None

    summary = await EvaluationRunner(adapter=adapter, host=_Host()).run()

    assert summary.task_count == 1
    assert summary.completed_count == 1


@pytest.mark.parametrize(
    "overrides",
    (
        {"deadline": datetime(2026, 7, 29)},
        {"max_poc_bytes": 0},
        {"max_patch_bytes": 0},
    ),
)
def test_rejects_invalid_task_envelope(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "session_id": "session-1",
        "task_id": "task-1",
        "mode": CyberGymMode.E2E,
        "source_workspace_ref": "workspace-1",
        "deadline": _NOW + timedelta(hours=1),
    }
    values.update(overrides)
    with pytest.raises(ValueError):
        CyberGymTaskConfig(**values)  # type: ignore[arg-type]


def test_patch_only_requires_both_inputs_and_same_scope() -> None:
    with pytest.raises(ValueError, match="requires crash_log"):
        CyberGymTaskConfig(
            session_id="session-1",
            task_id="task-1",
            mode=CyberGymMode.PATCH_ONLY,
            source_workspace_ref="workspace-1",
            deadline=_NOW + timedelta(hours=1),
        )
    with pytest.raises(ValueError, match="another task"):
        CyberGymTaskConfig(
            session_id="session-1",
            task_id="task-1",
            mode=CyberGymMode.PATCH_ONLY,
            source_workspace_ref="workspace-1",
            crash_log=_artifact("crash.log", "text/plain", session_id="session-2"),
            supplied_poc=_artifact("input-poc.bin", "application/octet-stream"),
            deadline=_NOW + timedelta(hours=1),
        )


async def test_rejects_outstanding_closed_and_mismatched_result() -> None:
    adapter = CyberGymAdapter(
        CyberGymTaskConfig(
            session_id="session-1",
            task_id="task-1",
            mode=CyberGymMode.E2E,
            source_workspace_ref="workspace-1",
            deadline=_NOW + timedelta(hours=1),
        )
    )
    task = await adapter.next_task()
    assert task is not None
    with pytest.raises(CyberGymAdapterError, match="already awaiting"):
        await adapter.next_task()
    mismatched = _result(
        task.model_copy(update={"task_id": "task-2"}),
        (
            _artifact("poc.bin", "application/octet-stream", task_id="task-2"),
            _artifact("fix.patch", "text/x-diff", task_id="task-2"),
        ),
    )
    with pytest.raises(CyberGymAdapterError, match="identity"):
        await adapter.submit(mismatched)
    await adapter.close()
    with pytest.raises(CyberGymAdapterError, match="closed"):
        await adapter.next_task()


def test_validation_rejects_cross_task_receipt() -> None:
    receipts = tuple(
        _artifact(f"validation-{index}.json", "application/json") for index in range(3)
    ) + (_artifact("validation-3.json", "application/json", task_id="task-2"),)

    with pytest.raises(CyberGymAdapterError, match="another task"):
        external_validation_receipt(
            session_id="session-1",
            task_id="task-1",
            stage_receipts=receipts,
        )
