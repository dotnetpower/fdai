"""Governed Python task capability report: explicit unavailable and available states."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
from fdai_operator_service.families.workflow import WorkflowOperation, WorkflowReadRequest
from fdai_operator_service.family_adapters import PostgresWorkflowAdapters
from fdai_operator_service.postgres_family_store import PostgresFamilyStoreUnavailable
from fdai_operator_service.python_task_capability import (
    PYTHON_TASK_CAPABILITY_SOURCE,
    UNBOUND_PYTHON_TASKS,
    VALIDATOR_NOT_BOUND,
    VM_TASK_RUNNER_NOT_BOUND,
    PythonTaskBindings,
    python_task_capability_payload,
    python_task_capability_result,
)
from starlette.exceptions import HTTPException

SERVICE_ROOT = Path(__file__).resolve().parents[1] / "src/fdai_operator_service"
ALL_DISABLED = {
    "generate": False,
    "validate": False,
    "stage": False,
    "test": False,
    "request_run": False,
    "schedule": False,
}


def _request(operation: WorkflowOperation) -> WorkflowReadRequest:
    return WorkflowReadRequest(
        operation=operation,
        principal_id="operator-a",
        query={},
        path_parameters={},
        body={},
    )


@pytest.mark.parametrize(
    ("bindings", "reasons"),
    [
        (PythonTaskBindings(), [VALIDATOR_NOT_BOUND, VM_TASK_RUNNER_NOT_BOUND]),
        (
            PythonTaskBindings(
                validator=True,
                artifact_store=True,
                author=True,
                run_submitter=True,
                schedule_store=True,
            ),
            [VM_TASK_RUNNER_NOT_BOUND],
        ),
        (PythonTaskBindings(vm_task_runner=True, artifact_store=True), [VALIDATOR_NOT_BOUND]),
    ],
)
def test_missing_validator_or_runner_disables_every_operation(
    bindings: PythonTaskBindings,
    reasons: list[str],
) -> None:
    payload = python_task_capability_payload(bindings)

    assert payload["available"] is False
    assert payload["unavailable_reasons"] == reasons
    assert payload["operations"] == ALL_DISABLED
    assert payload["vm_task_runner"] == {"bound": bindings.vm_task_runner}
    assert payload["execution_authority"] is False


def test_validator_and_runner_make_only_their_operations_available() -> None:
    payload = python_task_capability_payload(
        PythonTaskBindings(validator=True, vm_task_runner=True)
    )

    assert payload["available"] is True
    assert payload["unavailable_reasons"] == []
    assert payload["operations"] == {
        "generate": False,
        "validate": True,
        "stage": False,
        "test": True,
        "request_run": False,
        "schedule": False,
    }
    assert payload["vm_task_runner"] == {"bound": True}
    assert payload["execution_authority"] is False


@pytest.mark.parametrize(
    ("bindings", "enabled"),
    [
        (PythonTaskBindings(author=True), {"generate"}),
        (PythonTaskBindings(artifact_store=True), {"stage"}),
        (PythonTaskBindings(run_submitter=True), set()),
        (PythonTaskBindings(artifact_store=True, run_submitter=True), {"stage", "request_run"}),
        (PythonTaskBindings(schedule_store=True), set()),
        (PythonTaskBindings(artifact_store=True, schedule_store=True), {"stage", "schedule"}),
    ],
)
def test_optional_operations_require_every_owner_they_depend_on(
    bindings: PythonTaskBindings,
    enabled: set[str],
) -> None:
    complete = PythonTaskBindings(
        validator=True,
        vm_task_runner=True,
        artifact_store=bindings.artifact_store,
        author=bindings.author,
        run_submitter=bindings.run_submitter,
        schedule_store=bindings.schedule_store,
    )

    operations = cast(dict[str, bool], python_task_capability_payload(complete)["operations"])

    assert {name for name, value in operations.items() if value} == {"validate", "test"} | enabled


def test_report_revision_is_deterministic_and_state_bound() -> None:
    unbound = python_task_capability_result(UNBOUND_PYTHON_TASKS)
    repeated = python_task_capability_result(PythonTaskBindings())
    available = python_task_capability_result(
        PythonTaskBindings(validator=True, vm_task_runner=True)
    )

    assert unbound.provenance.source_ref == PYTHON_TASK_CAPABILITY_SOURCE
    assert unbound.provenance.revision == repeated.provenance.revision
    assert unbound.provenance.revision != available.provenance.revision
    assert unbound.provenance.synthetic is False


async def test_operator_adapter_reports_the_composition_bindings_without_store_reads() -> None:
    class NoStore:
        async def _fetch_all(self, statement: str, parameters: object) -> list[dict[str, Any]]:
            raise AssertionError("the capability report must not read PostgreSQL")

        async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
            raise AssertionError("the capability report has no projection")

    unbound = await PostgresWorkflowAdapters(cast(Any, NoStore())).read(
        _request(WorkflowOperation.PYTHON_CAPABILITIES)
    )
    bound = await PostgresWorkflowAdapters(
        cast(Any, NoStore()),
        python_tasks=PythonTaskBindings(validator=True, vm_task_runner=True),
    ).read(_request(WorkflowOperation.PYTHON_CAPABILITIES))

    assert unbound.payload["available"] is False
    assert bound.payload["available"] is True


@pytest.mark.parametrize(
    "operation",
    [
        WorkflowOperation.PYTHON_GENERATE,
        WorkflowOperation.PYTHON_VALIDATE,
        WorkflowOperation.PYTHON_TEST,
    ],
)
async def test_unbound_python_task_reads_stay_unavailable_as_reported(
    operation: WorkflowOperation,
) -> None:
    class ProjectionOnlyStore:
        async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
            raise PostgresFamilyStoreUnavailable(
                f"authoritative {family} projection is unavailable for {operation}"
            )

    with pytest.raises(HTTPException) as caught:
        await PostgresWorkflowAdapters(cast(Any, ProjectionOnlyStore())).read(_request(operation))

    assert caught.value.status_code == 503


def test_production_composition_binds_no_python_task_owner() -> None:
    """The capability stays honest only while no composition claims an unbound owner."""
    constructions = [
        match.group(0)
        for path in SERVICE_ROOT.rglob("*.py")
        for match in re.finditer(
            r"PostgresWorkflowAdapters\([^)]*\)",
            path.read_text(encoding="utf-8"),
        )
    ]

    assert constructions == ["PostgresWorkflowAdapters(store)"]
    assert "PythonTaskBindings(" not in "".join(
        path.read_text(encoding="utf-8")
        for path in SERVICE_ROOT.rglob("*.py")
        if path.name != "python_task_capability.py"
    )
