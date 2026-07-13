"""Runbook value objects mirroring ``shared/contracts/runbook/schema.json``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from fdai.shared.contracts.models import CeilingRole, WorkflowStepKind


class RunbookRunError(RuntimeError):
    """Raised on any structural error the runner refuses to proceed on.

    Distinct from a step's own execution failure (which is captured
    in :class:`RunbookStepResult`) - a ``RunbookRunError`` means the
    runbook itself is malformed (missing ``on_failure`` target,
    duplicate step ids, etc.) and no step should have been attempted.
    """


class RunbookStepOutcome(StrEnum):
    """Terminal outcome for one :class:`RunbookStep`."""

    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    """Step never ran (short-circuited by a prior failure)."""
    WAITING = "waiting"
    """Step parked the Process until an external signal or decision resumes it."""


@dataclass(frozen=True, slots=True)
class RunbookStep:
    """One step in a runbook DAG."""

    id: str
    action_type: str
    params: Mapping[str, object] = field(default_factory=dict)
    on_failure: str | None = None
    kind: WorkflowStepKind = WorkflowStepKind.ACTION
    wait_for: str | None = None
    timeout_seconds: int | None = None
    approval_role: CeilingRole | None = None
    quorum: int = 1
    no_self_approval: bool = True
    outcomes: tuple[str, ...] = ()
    branches: tuple[str, ...] = ()
    guard_rule_ref: str | None = None


@dataclass(frozen=True, slots=True)
class Runbook:
    """Ordered list of :class:`RunbookStep`.

    Validation invariants (enforced at construction, not at
    ``run`` time so a fork's authoring tool catches errors early):

    - At least one step.
    - Step ids are unique within the runbook.
    - Every ``on_failure`` target refers to an existing step id.
    """

    id: str
    steps: tuple[RunbookStep, ...]
    description: str | None = None
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if not self.steps:
            raise RunbookRunError(f"runbook {self.id!r} has no steps")
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise RunbookRunError(f"runbook {self.id!r} has duplicate step id {step.id!r}")
            seen.add(step.id)
        for step in self.steps:
            if step.on_failure is not None and step.on_failure not in seen:
                raise RunbookRunError(
                    f"runbook {self.id!r} step {step.id!r} on_failure -> "
                    f"unknown step {step.on_failure!r}"
                )


@dataclass(frozen=True, slots=True)
class RunbookStepResult:
    """One step's terminal record."""

    step_id: str
    action_type: str
    outcome: RunbookStepOutcome
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RunbookResult:
    """Aggregate run record.

    ``terminal_outcome`` is:

    - ``SUCCESS`` when every executed step succeeded (skipped steps
      do NOT downgrade this).
    - ``FAILURE`` otherwise.
    """

    runbook_id: str
    step_results: tuple[RunbookStepResult, ...]
    terminal_outcome: RunbookStepOutcome


__all__ = [
    "Runbook",
    "RunbookResult",
    "RunbookRunError",
    "RunbookStep",
    "RunbookStepOutcome",
    "RunbookStepResult",
]
