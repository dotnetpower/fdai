"""Runbook DAG orchestrator - linear sequence + on-failure branch.

Design contract: ``docs/roadmap/sre-agent-scope.md § 3.4``.

The upstream MVP is intentionally minimal: an ordered list of
``RunbookStep`` entries where each step names one ActionType from the
ontology, plus an optional ``on_failure`` step id to run when this
step fails. A full DAG is deferred until two callers need it.

Every step runs through the same execution surface as a rule-fired
Action, so the four safety invariants
([architecture.instructions.md](../../../../.github/instructions/architecture.instructions.md#safety-invariants))
still hold on every step - the runner is a composer, not an escape
hatch.
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
