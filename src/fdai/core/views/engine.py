"""Render one Process through its workflow-selected ViewSpec."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fdai.core.operational_planning import project_planning_room
from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.models import RenderedReport
from fdai.core.views.models import ViewSpec
from fdai.shared.providers.process_runtime import (
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)


class ProcessViewLookupError(LookupError):
    """Base failure for a Process or its workflow-selected ViewSpec not existing."""


class ProcessNotFoundError(ProcessViewLookupError):
    """The requested Process snapshot does not exist."""


class ProcessViewNotFoundError(ProcessViewLookupError):
    """The Process workflow has no registered ViewSpec."""


@dataclass(frozen=True, slots=True)
class RenderedViewRegion:
    id: str
    column_span: int
    report: RenderedReport


@dataclass(frozen=True, slots=True)
class RenderedView:
    spec: ViewSpec
    process: ProcessSnapshot
    regions: tuple[RenderedViewRegion, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.spec.id,
            "version": self.spec.version,
            "name": self.spec.name,
            "description": self.spec.description,
            "route": self.spec.route,
            "process": {
                "id": self.process.process_id,
                "workflow_ref": self.process.workflow_ref,
                "workflow_version": self.process.workflow_version,
                "status": self.process.status.value,
                "current_step": self.process.current_step,
                "target_resource_id": self.process.target_resource_id,
                "started_at": self.process.started_at.isoformat(),
                "updated_at": self.process.updated_at.isoformat(),
                "correlation_id": self.process.correlation_id,
                "revision": self.process.revision,
            },
            "regions": [
                {
                    "id": region.id,
                    "column_span": region.column_span,
                    "report": region.report.to_dict(),
                }
                for region in self.regions
            ],
        }


class ViewEngine:
    def __init__(
        self,
        *,
        specs: tuple[ViewSpec, ...],
        reports: ReportEngine,
        processes: ProcessRuntimeStore,
    ) -> None:
        self._by_workflow = {spec.applies_to.workflow_ref: spec for spec in specs}
        self._reports = reports
        self._processes = processes

    async def render_process(self, process_id: str) -> RenderedView:
        process = await self._processes.get(process_id)
        if process is None:
            raise ProcessNotFoundError(f"unknown process {process_id!r}")
        spec = self._by_workflow.get(process.workflow_ref)
        if spec is None:
            raise ProcessViewNotFoundError(f"no ViewSpec for workflow {process.workflow_ref!r}")
        regions = []
        for region in spec.regions:
            report = await self._reports.render(
                region.report_ref,
                variables={"process_id": process.process_id},
            )
            regions.append(
                RenderedViewRegion(
                    id=region.id,
                    column_span=region.column_span,
                    report=report,
                )
            )
        return RenderedView(spec=spec, process=process, regions=tuple(regions))

    async def process_journal(self, process_id: str) -> dict[str, Any]:
        """Return the authoritative snapshot and append-only event journal."""
        process = await self._processes.get(process_id)
        if process is None:
            raise ProcessNotFoundError(f"unknown process {process_id!r}")
        events = await self._processes.events(process_id)
        planning = project_planning_room(events)
        return {
            "process": _process_dict(
                process,
                has_view=process.workflow_ref in self._by_workflow,
            ),
            "events": [
                {
                    "event_id": event.event_id,
                    "kind": event.kind.value,
                    "recorded_at": event.recorded_at.isoformat(),
                    "correlation_id": event.correlation_id,
                    "causation_id": event.causation_id,
                    "step_id": event.step_id,
                    "attempt": event.attempt,
                    "payload": dict(event.payload),
                }
                for event in events
            ],
            "count": len(events),
            "planning": planning,
        }

    async def list_processes(
        self,
        *,
        workflow_ref: str | None = None,
        status: ProcessStatus | None = None,
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        snapshots = await self._processes.list(
            workflow_ref=workflow_ref,
            status=status,
            limit=limit,
        )
        return tuple(
            _process_dict(
                snapshot,
                has_view=snapshot.workflow_ref in self._by_workflow,
                summary=True,
            )
            for snapshot in snapshots
        )


def _process_dict(
    snapshot: ProcessSnapshot,
    *,
    has_view: bool,
    summary: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": snapshot.process_id,
        "workflow_ref": snapshot.workflow_ref,
        "workflow_version": snapshot.workflow_version,
        "status": snapshot.status.value,
        "current_step": snapshot.current_step,
        "target_resource_id": snapshot.target_resource_id,
        "updated_at": snapshot.updated_at.isoformat(),
        "has_view": has_view,
    }
    if not summary:
        result.update(
            {
                "started_at": snapshot.started_at.isoformat(),
                "correlation_id": snapshot.correlation_id,
                "revision": snapshot.revision,
            }
        )
    return result


__all__ = [
    "ProcessNotFoundError",
    "ProcessViewLookupError",
    "ProcessViewNotFoundError",
    "RenderedView",
    "RenderedViewRegion",
    "ViewEngine",
]
