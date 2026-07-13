"""Runbook runner.

Composes an ordered sequence of :class:`RunbookStep` calls into a
single execution. The runner is intentionally thin: it walks the step
list, delegates each step to the injected :class:`StepExecutor`, and
follows the ``on_failure`` branch when a step fails.

Every terminal outcome writes an audit entry through the executor
(``StepExecutor.execute`` is responsible for the audit; the runner
does NOT double-write). The runner writes its own aggregate
``runbook.terminal`` audit row via the injected
:class:`~fdai.shared.providers.state_store.StateStore` so a reviewer
can find the whole run by ``runbook_id``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from fdai.shared.providers.state_store import StateStore

from .models import (
    Runbook,
    RunbookResult,
    RunbookStep,
    RunbookStepOutcome,
    RunbookStepResult,
)


class StepExecutor(Protocol):
    """Executes one runbook step.

    Concrete implementations map an ``action_type`` name to the
    appropriate executor (PR-native, direct-api, pr-manual) and honor
    the four safety invariants per the ontology. The runner never
    reaches into that logic - it is entirely up to the executor.
    """

    async def execute(
        self,
        *,
        runbook_id: str,
        step: RunbookStep,
    ) -> RunbookStepResult:
        """Return the step's terminal record. MUST NOT raise for a
        business-logic failure - convert it to
        :attr:`RunbookStepOutcome.FAILURE` with a ``reason`` string
        so the runner can decide whether to follow ``on_failure``."""
        ...


class RunbookRunner:
    """Walk the step list, honor ``on_failure`` on the first failure."""

    def __init__(
        self,
        *,
        executor: StepExecutor,
        audit_store: StateStore,
    ) -> None:
        self._executor = executor
        self._audit_store = audit_store

    async def run(
        self,
        runbook: Runbook,
        *,
        start_step_id: str | None = None,
        audit_context: Mapping[str, object] | None = None,
    ) -> RunbookResult:
        """Execute ``runbook``. Returns the aggregate :class:`RunbookResult`."""
        steps_by_id: Mapping[str, RunbookStep] = {s.id: s for s in runbook.steps}
        if start_step_id is not None and start_step_id not in steps_by_id:
            raise ValueError(f"runbook {runbook.id!r} has no start step {start_step_id!r}")
        start_index = (
            next(index for index, step in enumerate(runbook.steps) if step.id == start_step_id)
            if start_step_id is not None
            else 0
        )
        active_steps = runbook.steps[start_index:]
        results: list[RunbookStepResult] = []
        terminal = RunbookStepOutcome.SUCCESS

        for step in active_steps:
            outcome = await self._executor.execute(runbook_id=runbook.id, step=step)
            results.append(outcome)
            if outcome.outcome is RunbookStepOutcome.WAITING:
                terminal = RunbookStepOutcome.WAITING
                break
            if outcome.outcome is not RunbookStepOutcome.SUCCESS:
                terminal = RunbookStepOutcome.FAILURE
                # Follow on_failure if present; then short-circuit.
                if step.on_failure is not None:
                    fallback_step = steps_by_id[step.on_failure]
                    fallback_result = await self._executor.execute(
                        runbook_id=runbook.id, step=fallback_step
                    )
                    results.append(fallback_result)
                # Mark every subsequent authored step as SKIPPED so the
                # audit row shows the runner made a decision, not that
                # steps silently disappeared.
                for skipped in active_steps[active_steps.index(step) + 1 :]:
                    if step.on_failure is not None and skipped.id == step.on_failure:
                        continue
                    results.append(
                        RunbookStepResult(
                            step_id=skipped.id,
                            action_type=skipped.action_type,
                            outcome=RunbookStepOutcome.SKIPPED,
                            reason="short_circuited_after_failure",
                        )
                    )
                break

        terminal_audit: dict[str, object] = {
            "actor": "fdai.core.runbook",
            "action_kind": "runbook.terminal",
            "mode": "shadow",
            "runbook_id": runbook.id,
            "terminal_outcome": terminal.value,
            "step_outcomes": [
                {"step_id": r.step_id, "outcome": r.outcome.value, "reason": r.reason}
                for r in results
            ],
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
        if audit_context:
            terminal_audit.update(audit_context)
        await self._audit_store.append_audit_entry(terminal_audit)
        return RunbookResult(
            runbook_id=runbook.id,
            step_results=tuple(results),
            terminal_outcome=terminal,
        )


__all__ = ["RunbookRunner", "StepExecutor"]
