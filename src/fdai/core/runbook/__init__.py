"""Runbook DAG orchestrator - linear sequence + on-failure branch.

Design contract: ``docs/roadmap/fork-and-sequencing/scope-expansion.md § 3.4``.

The upstream MVP is intentionally minimal: an ordered list of
``RunbookStep`` entries where each step names one ActionType from the
ontology, plus an optional ``on_failure`` step id to run when this
step fails. A full DAG is deferred until two callers need it.

Every step runs through the same execution surface as a rule-fired
Action, so its executor must complete all seven safeguards
([architecture.instructions.md](../../../../.github/instructions/architecture.instructions.md#seven-autonomous-action-safeguards)).
The runner is a composer, not an escape hatch.
"""

from __future__ import annotations

from .models import (
    Runbook,
    RunbookResult,
    RunbookRunError,
    RunbookStep,
    RunbookStepOutcome,
    RunbookStepResult,
)
from .runner import RunbookRunner, StepExecutor

__all__ = [
    "Runbook",
    "RunbookResult",
    "RunbookRunError",
    "RunbookRunner",
    "RunbookStep",
    "RunbookStepOutcome",
    "RunbookStepResult",
    "StepExecutor",
]
