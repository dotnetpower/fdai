"""Workflow trigger index - map a Signal (or a schedule tick) to the Workflows
it fires (see docs/roadmap/decisioning/process-automation.md 2).

The index is the event-driven entry to process automation, analogous to the
rule index: given a normalized ``signal_type`` it returns, in O(1), the
Workflows whose ``trigger.kind == signal`` and ``trigger.signal_type`` match.
Schedule-triggered Workflows are listed separately for a scheduler to poll.

Deterministic and read-only: the lookup order is stable (Workflow ``name``) so a
caller replaying the same event fires the same Workflows in the same order. The
index resolves *which* Workflows fire; running one is the
:class:`~fdai.core.workflow.orchestrator.WorkflowOrchestrator`'s job.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from fdai.shared.contracts.models import Workflow, WorkflowTriggerKind


@dataclass(frozen=True, slots=True)
class WorkflowTriggerIndex:
    """Immutable index of Workflows by trigger.

    Built once from the loaded catalog; a signal lookup is a dict hit and a
    scheduled-workflow scan is a precomputed tuple.
    """

    _by_signal: Mapping[str, tuple[Workflow, ...]]
    _scheduled: tuple[Workflow, ...]

    @classmethod
    def build(cls, workflows: Iterable[Workflow]) -> WorkflowTriggerIndex:
        """Build the index from a Workflow catalog."""
        by_signal: dict[str, list[Workflow]] = {}
        scheduled: list[Workflow] = []
        for wf in workflows:
            trigger = wf.trigger
            if trigger.kind is WorkflowTriggerKind.SIGNAL and trigger.signal_type:
                by_signal.setdefault(trigger.signal_type, []).append(wf)
            elif trigger.kind is WorkflowTriggerKind.SCHEDULE:
                scheduled.append(wf)
        frozen_by_signal = {
            signal_type: tuple(sorted(wfs, key=lambda w: w.name))
            for signal_type, wfs in by_signal.items()
        }
        return cls(
            _by_signal=frozen_by_signal,
            _scheduled=tuple(sorted(scheduled, key=lambda w: w.name)),
        )

    def for_signal(self, signal_type: str) -> tuple[Workflow, ...]:
        """Return the Workflows fired by ``signal_type`` (name-ordered, may be empty)."""
        return self._by_signal.get(signal_type, ())

    def scheduled(self) -> tuple[Workflow, ...]:
        """Return every schedule-triggered Workflow (name-ordered)."""
        return self._scheduled

    def for_schedule(self, workflow_name: str) -> tuple[Workflow, ...]:
        """Return one scheduled Workflow by name, or an empty tuple."""
        return tuple(workflow for workflow in self._scheduled if workflow.name == workflow_name)

    def signal_types(self) -> frozenset[str]:
        """Return every signal type that fires at least one Workflow."""
        return frozenset(self._by_signal)


__all__ = ["WorkflowTriggerIndex"]
