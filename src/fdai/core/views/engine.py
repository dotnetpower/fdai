"""Render one Process through its workflow-selected ViewSpec."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.models import RenderedReport
from fdai.core.views.models import ViewSpec
from fdai.shared.providers.process_runtime import (
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)


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
            raise KeyError(f"unknown process {process_id!r}")
        spec = self._by_workflow.get(process.workflow_ref)
        if spec is None:
            raise KeyError(f"no ViewSpec for workflow {process.workflow_ref!r}")
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
            {
                "id": snapshot.process_id,
                "workflow_ref": snapshot.workflow_ref,
                "workflow_version": snapshot.workflow_version,
                "status": snapshot.status.value,
                "current_step": snapshot.current_step,
                "target_resource_id": snapshot.target_resource_id,
                "updated_at": snapshot.updated_at.isoformat(),
                "has_view": snapshot.workflow_ref in self._by_workflow,
            }
            for snapshot in snapshots
        )


__all__ = ["RenderedView", "RenderedViewRegion", "ViewEngine"]
