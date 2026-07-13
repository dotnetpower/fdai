"""Read-only Process and ontology instance projections for declarative reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.core.reporting.models import DataSet, QuerySpec
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyInstanceStore
from fdai.shared.providers.process_runtime import ProcessRuntimeStore


@dataclass(frozen=True, slots=True)
class OntologyDataSource:
    ontology: OntologyInstanceStore
    processes: ProcessRuntimeStore
    name: str = "ontology"

    async def query(
        self,
        spec: QuerySpec,
        *,
        since: datetime,
        until: datetime,
        variables: Mapping[str, str],
    ) -> DataSet:
        del since, until, variables
        projection = str(spec.parameters.get("projection", ""))
        process_id = str(spec.parameters.get("process_id", ""))
        if not process_id:
            raise ValueError("ontology datasource requires process_id")
        if projection == "process_property":
            return await self._process_property(process_id, spec.parameters)
        if projection == "process_events":
            return await self._process_events(process_id)
        graph = await self._graph(process_id, spec.parameters)
        if projection == "review_checks":
            return _review_checks(graph)
        if projection == "objects":
            return _objects(graph, object_type=str(spec.parameters.get("object_type", "")))
        if projection == "topology":
            return _topology(graph)
        raise ValueError(f"unknown ontology projection {projection!r}")

    async def _process_property(
        self,
        process_id: str,
        parameters: Mapping[str, Any],
    ) -> DataSet:
        field = str(parameters.get("field", ""))
        snapshot = await self.processes.get(process_id)
        if snapshot is None:
            return DataSet(scalar=None)
        values: Mapping[str, Any] = {
            "process_id": snapshot.process_id,
            "workflow_ref": snapshot.workflow_ref,
            "workflow_version": snapshot.workflow_version,
            "status": snapshot.status.value,
            "current_step": snapshot.current_step,
            "target_resource_id": snapshot.target_resource_id,
            "started_at": snapshot.started_at.isoformat(),
            "updated_at": snapshot.updated_at.isoformat(),
            "correlation_id": snapshot.correlation_id,
            "revision": snapshot.revision,
        }
        if field in values:
            return DataSet(scalar=values[field])
        graph = await self._graph(process_id, parameters)
        review = next((item for item in graph.objects if item.object_type == "ReviewCase"), None)
        return DataSet(scalar=review.properties.get(field) if review is not None else None)

    async def _process_events(self, process_id: str) -> DataSet:
        events = await self.processes.events(process_id)
        rows = tuple(
            {
                "id": event.event_id,
                "kind": event.kind.value,
                "step_id": event.step_id,
                "attempt": event.attempt,
                "at": event.recorded_at.isoformat(),
                "causation_id": event.causation_id,
                **dict(event.payload),
            }
            for event in events
        )
        return DataSet(rows=rows)

    async def _graph(
        self,
        process_id: str,
        parameters: Mapping[str, Any],
    ) -> OntologyGraphSnapshot:
        depth = int(parameters.get("depth", 4))
        limit = int(parameters.get("limit", 500))
        return await self.ontology.traverse(
            root_ids=(process_id,),
            direction="both",
            max_depth=depth,
            limit=limit,
        )


def _review_checks(graph: OntologyGraphSnapshot) -> DataSet:
    rows = []
    for item in graph.objects:
        if item.object_type != "ReviewCheck":
            continue
        status = str(item.properties.get("status", "unknown"))
        rows.append(
            {
                "name": item.properties.get("check_key"),
                "status": _check_status(status),
                "message": item.properties.get("description"),
                "at": item.properties.get("updated_at"),
                "category": item.properties.get("category"),
                "severity": item.properties.get("severity"),
                "raw_status": status,
            }
        )
    rows.sort(key=lambda row: (str(row["status"]), str(row["name"])))
    return DataSet(rows=tuple(rows))


def _objects(graph: OntologyGraphSnapshot, *, object_type: str) -> DataSet:
    rows = tuple(
        {"id": item.id, "object_type": item.object_type, **dict(item.properties)}
        for item in graph.objects
        if not object_type or item.object_type == object_type
    )
    return DataSet(rows=rows)


def _topology(graph: OntologyGraphSnapshot) -> DataSet:
    node_rows = [
        {
            "kind": "node",
            "id": item.id,
            "label": item.properties.get("title") or item.properties.get("check_key") or item.id,
            "group": item.object_type,
            "value": item.properties.get("status"),
        }
        for item in graph.objects
    ]
    edge_rows = [
        {
            "kind": "edge",
            "source": link.from_id,
            "target": link.to_id,
            "value": link.link_type,
        }
        for link in graph.links
    ]
    return DataSet(rows=tuple([*node_rows, *edge_rows]))


def _check_status(status: str) -> str:
    if status in {"ready", "resolved", "approved"}:
        return "ok"
    if status in {"conditional", "open", "pending", "in_review"}:
        return "warn"
    if status in {"blocked", "failed", "rejected"}:
        return "fail"
    return "unknown"


__all__ = ["OntologyDataSource"]
