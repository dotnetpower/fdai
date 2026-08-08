"""Workflow compiler - turn a catalog :class:`Workflow` into an executable
:class:`Runbook` plus the saga-compensation map its steps declare.

The compiler is intentionally thin and pure: it does no I/O and no
dispatch. It maps each :class:`WorkflowStep` to a
:class:`~fdai.core.runbook.models.RunbookStep` (``action_type_ref`` ->
``action_type``) and collects the ``compensated_by`` declarations into a
``step_id -> ActionType`` map.

Execution stays with the existing
:class:`~fdai.core.runbook.runner.RunbookRunner`, which walks the compiled
Runbook one step at a time and honors ``on_failure``. Each step is
dispatched through the injected ``StepExecutor``, which re-enters the typed
pipeline (ActionType -> risk-gate -> executor -> audit); the compiler never
touches an executor.

The compensation map is validated and exposed here but is dispatched by the
process orchestrator that lands with the risk-gate integration - the same
declared-versus-live boundary the action ontology uses
(action-ontology.md 12.1). In P1 the runner runs the linear sequence plus
the single ``on_failure`` branch; compensation is inert by construction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from fdai.core.runbook.models import Runbook, RunbookStep
from fdai.shared.contracts.models import Mode, Workflow


@dataclass(frozen=True, slots=True)
class CompiledWorkflow:
    """A Workflow lowered to an executable form.

    - ``runbook`` - the linear step sequence the RunbookRunner executes.
    - ``compensations`` - ``step_id -> ActionType`` saga rollback map; read
      by the process orchestrator, inert in P1.
    - ``default_mode`` - the Workflow's mode; ``SHADOW`` means judge-and-log
      only, no mutation.
    """

    runbook: Runbook
    compensations: Mapping[str, str]
    default_mode: Mode

    @property
    def is_shadow(self) -> bool:
        """True when this Workflow runs judge-and-log only (no mutation)."""
        return self.default_mode is Mode.SHADOW


def compile_workflow(workflow: Workflow) -> CompiledWorkflow:
    """Lower ``workflow`` to a :class:`CompiledWorkflow`.

    The resulting :class:`Runbook` re-validates its own structural
    invariants (unique step ids, resolvable ``on_failure``) at
    construction; the :class:`Workflow` already guaranteed them, so this
    is a defense-in-depth no-op rather than a second source of truth.
    """
    steps = tuple(
        RunbookStep(
            id=step.id,
            action_type=step.action_type_ref or f"workflow.{step.kind.value}",
            params=dict(step.params),
            on_failure=step.on_failure,
            kind=step.kind,
            wait_for=step.wait_for,
            timeout_seconds=step.timeout_seconds,
            approval_role=step.approval_role,
            quorum=step.quorum,
            no_self_approval=step.no_self_approval,
            outcomes=tuple(step.outcomes),
            branches=tuple(step.branches),
            guard_rule_ref=step.gate_ref or step.guard_rule_ref,
        )
        for step in workflow.steps
    )
    runbook = Runbook(
        id=workflow.name,
        steps=steps,
        description=workflow.description,
        schema_version=workflow.schema_version,
    )
    compensations = {
        step.id: step.compensated_by for step in workflow.steps if step.compensated_by is not None
    }
    return CompiledWorkflow(
        runbook=runbook,
        compensations=MappingProxyType(compensations),
        default_mode=workflow.default_mode,
    )


__all__ = ["CompiledWorkflow", "compile_workflow"]
