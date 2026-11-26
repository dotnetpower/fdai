"""Orchestration origin and execution venue recorded with safeguard evidence.

FDAI-CONST-007 requires the same seven safeguards on every execution path.
Proving that across a fleet needs more than the path name: the same
``ExecutionPath`` can be reached from a Core-originated control-loop
decision or from a workflow-orchestrated step, and a ``direct_api``
dispatch can leave either the Core process or the isolated Executor
service.  Without both axes a cross-path evidence matrix cannot tell a
missing cell from a duplicated one.

Neither value grants authority.  They are descriptive provenance recorded
alongside the bundle so an auditor can attribute one durable record to
exactly one matrix cell.

``ExecutionVenue`` in ``fdai_service_contracts.venue`` answers a different
question - whether a *process* runs locally or deployed - and deliberately
may not change contracts or authority.  The venue below answers "which
service performed the provider dispatch", which is a control-plane
boundary, so it is a separate vocabulary rather than a reuse.
"""

from __future__ import annotations

from enum import StrEnum

from fdai.shared.contracts.models import Action


class SafeguardExecutionOrigin(StrEnum):
    """Which orchestration surface originated one safeguarded dispatch."""

    CORE = "core"
    """A Core control-loop decision dispatched the action directly."""

    WORKFLOW = "workflow"
    """A workflow step selected the executor and carried its own lineage."""


class SafeguardExecutionVenue(StrEnum):
    """Which service performed the provider dispatch for one action."""

    CORE = "core"
    """The Core control-plane process called the provider seam in-process."""

    ISOLATED_EXECUTOR = "isolated_executor"
    """The isolated Executor service revalidated and called the provider."""


def resolve_execution_origin(action: Action) -> SafeguardExecutionOrigin:
    """Return the orchestration origin implied by one action's lineage.

    Workflow orchestration is proven by the action's own
    ``workflow_action`` lineage, which the workflow runtime is the only
    writer of.  Absence of that lineage is Core origin; it is never
    inferred from the caller, so a mislabeled caller cannot relabel the
    matrix cell.
    """

    return (
        SafeguardExecutionOrigin.WORKFLOW
        if action.workflow_action is not None
        else SafeguardExecutionOrigin.CORE
    )


__all__ = [
    "SafeguardExecutionOrigin",
    "SafeguardExecutionVenue",
    "resolve_execution_origin",
]
