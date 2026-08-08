"""Workflow trigger coordinator - the event-driven bridge from a normalized
Event to a shadow Workflow run (see docs/roadmap/decisioning/process-automation.md 4).

This is the connective tissue between the control loop and process automation:
an :class:`Event` that clears ``event-ingest`` is matched against the
:class:`~fdai.core.workflow.trigger_index.WorkflowTriggerIndex` on its
``event_type``, and every matched Workflow is run in shadow through the
:class:`~fdai.core.workflow.orchestrator.WorkflowOrchestrator`.

Deterministic and shadow-only: matched Workflows run in the index's stable
name order, and the orchestrator's step executor structurally cannot mutate, so
firing a Workflow off an event only ever judges-and-logs. The coordinator adds
no new autonomy surface - it is the same declared-vs-live boundary the rest of
process automation holds.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.workflow.orchestrator import ProcessRun, WorkflowOrchestrator
from fdai.core.workflow.trigger_index import WorkflowTriggerIndex
from fdai.shared.contracts.models import Event


def _target_resource_id(event: Event) -> str:
    """Resolve the primary resource a Workflow run targets from an Event.

    Precedence: the explicit ``resource_ref``, then a ``resource.resource_id`` /
    ``resource.resource_ref`` in the payload, then a stable event-type sentinel
    so a resource-less signal (e.g. a schedule-style broadcast) still derives a
    deterministic Process id.
    """
    if event.resource_ref:
        return event.resource_ref
    payload_ref = _resource_ref_from_payload(event.payload)
    if payload_ref is not None:
        return payload_ref
    return f"event:{event.event_type}"


def _resource_ref_from_payload(payload: Mapping[str, Any]) -> str | None:
    resource = payload.get("resource")
    if isinstance(resource, Mapping):
        ref = resource.get("resource_id") or resource.get("resource_ref")
        if isinstance(ref, str) and ref:
            return ref
    return None


class WorkflowTriggerCoordinator:
    """Fire the Workflows matched by an Event, in shadow."""

    __slots__ = ("_index", "_orchestrator")

    def __init__(
        self,
        *,
        index: WorkflowTriggerIndex,
        orchestrator: WorkflowOrchestrator,
    ) -> None:
        self._index = index
        self._orchestrator = orchestrator

    async def on_event(self, event: Event) -> tuple[ProcessRun, ...]:
        """Run every Workflow triggered by ``event.event_type`` in shadow.

        Returns the :class:`ProcessRun` per matched Workflow, in the index's
        stable name order. An event that matches no Workflow returns an empty
        tuple and starts nothing.
        """
        matched = self._index.for_signal(event.event_type)
        scheduled_ref = _scheduled_workflow_ref(event)
        if not matched and scheduled_ref is not None:
            matched = self._index.for_schedule(scheduled_ref)
        if not matched:
            return ()
        target = _target_resource_id(event)
        runs: list[ProcessRun] = []
        for workflow in matched:
            run = await self._orchestrator.run(
                workflow,
                target_resource_id=target,
                trigger_ts=event.detected_at,
                context=_event_context(event),
                correlation_id=event.correlation_id or str(event.event_id),
            )
            runs.append(run)
        return tuple(runs)


def _scheduled_workflow_ref(event: Event) -> str | None:
    workflow_ref = event.payload.get("workflow_ref")
    if not isinstance(workflow_ref, str) or not workflow_ref:
        return None
    if event.event_type != f"workflow.schedule.{workflow_ref}":
        return None
    return workflow_ref


def _event_context(event: Event) -> dict[str, str]:
    context = {"event.event_type": event.event_type}
    if event.resource_ref:
        context["event.resource_ref"] = event.resource_ref
    _flatten_payload(event.payload, prefix="event.payload", target=context)
    return context


def _flatten_payload(
    value: Mapping[str, Any],
    *,
    prefix: str,
    target: dict[str, str],
    depth: int = 0,
) -> None:
    if depth >= 4 or len(target) >= 64:
        return
    for key in sorted(value):
        if len(target) >= 64:
            return
        item = value[key]
        path = f"{prefix}.{key}"
        if isinstance(item, Mapping):
            _flatten_payload(item, prefix=path, target=target, depth=depth + 1)
        elif isinstance(item, (str, int, float, bool)):
            rendered = str(item)
            if len(rendered) <= 2_000:
                target[path] = rendered


__all__ = ["WorkflowTriggerCoordinator"]
