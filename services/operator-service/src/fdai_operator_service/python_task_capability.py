"""Composition-owned governed Python task capability report for the Operator workflow family.

Responsibility:
Serve ``python-task.capabilities`` from the Python task owners this Operator composition binds.

Boundary:
A pure projection over explicit owner bindings. It performs no I/O, loads no task code, and does
not observe the Core runtime's executor bindings.

Authority and state:
Reports availability only. It never grants execution: the Operator holds no VM Run Command
identity, and a bound VM task runner may only plan. An unbound validator or runner yields an
explicit unavailable report with every operation disabled.

Dependencies:
Workflow-family read contracts only.

Deployment:
Runs inside the independently deployed Operator Service; local and deployed composition bind the
same owners.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Final

from fdai_service_contracts import JsonObject, JsonValue

from fdai_operator_service.families.workflow.contracts import (
    ProjectionProvenance,
    WorkflowReadResult,
)

PYTHON_TASK_CAPABILITY_SCHEMA_VERSION: Final = "1.0.0"
PYTHON_TASK_CAPABILITY_SOURCE: Final = "operator-composition:python-task-owners"
VALIDATOR_NOT_BOUND: Final = "python_task_validator_not_bound"
VM_TASK_RUNNER_NOT_BOUND: Final = "python_task_vm_runner_not_bound"


@dataclass(frozen=True, slots=True)
class PythonTaskBindings:
    """Governed Python task owners bound into one Operator composition.

    Set a field only in the same change that binds that owner's route handler. The independent
    Operator Service currently binds none of them, so every field defaults to unbound.
    """

    validator: bool = False
    vm_task_runner: bool = False
    artifact_store: bool = False
    author: bool = False
    run_submitter: bool = False
    schedule_store: bool = False


UNBOUND_PYTHON_TASKS: Final = PythonTaskBindings()


def python_task_capability_payload(bindings: PythonTaskBindings) -> JsonObject:
    """Project the workbench capability for one set of owner bindings.

    The workbench is available only when static validation and a VM task runner are bound.
    Otherwise every operation is disabled and ``unavailable_reasons`` names each missing owner.
    """
    reasons: list[JsonValue] = []
    if not bindings.validator:
        reasons.append(VALIDATOR_NOT_BOUND)
    if not bindings.vm_task_runner:
        reasons.append(VM_TASK_RUNNER_NOT_BOUND)
    available = not reasons
    operations: dict[str, JsonValue] = {
        "generate": available and bindings.author,
        "validate": available,
        "stage": available and bindings.artifact_store,
        "test": available,
        "request_run": available and bindings.artifact_store and bindings.run_submitter,
        "schedule": available and bindings.artifact_store and bindings.schedule_store,
    }
    return {
        "schema_version": PYTHON_TASK_CAPABILITY_SCHEMA_VERSION,
        "available": available,
        "unavailable_reasons": reasons,
        "operations": operations,
        "vm_task_runner": {"bound": bindings.vm_task_runner},
        "execution_authority": False,
    }


def python_task_capability_result(bindings: PythonTaskBindings) -> WorkflowReadResult:
    """Return the capability report with a content-derived revision."""
    payload = python_task_capability_payload(bindings)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return WorkflowReadResult(
        payload=payload,
        provenance=ProjectionProvenance(
            source_ref=PYTHON_TASK_CAPABILITY_SOURCE,
            revision=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        ),
    )


__all__ = [
    "PYTHON_TASK_CAPABILITY_SCHEMA_VERSION",
    "PYTHON_TASK_CAPABILITY_SOURCE",
    "UNBOUND_PYTHON_TASKS",
    "VALIDATOR_NOT_BOUND",
    "VM_TASK_RUNNER_NOT_BOUND",
    "PythonTaskBindings",
    "python_task_capability_payload",
    "python_task_capability_result",
]
