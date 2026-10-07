"""Concrete multi-step paths read from one secured ontology instance path graph."""

from __future__ import annotations

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord

from .models import OntologyInstancePathDefinition
from .query_execution import QueryNodeHeldError
from .query_values import QueryRow


def instance_paths(
    graph: OntologyGraphSnapshot,
    *,
    definition: OntologyInstancePathDefinition,
) -> tuple[tuple[tuple[OntologyObjectRecord, ...], ...], int | None]:
    objects = {record.id: record for record in graph.objects}
    paths: tuple[tuple[OntologyObjectRecord, ...], ...] = tuple(
        (record,) for record in graph.objects if record.object_type == definition.root_selector.name
    )
    if not paths:
        return (), 0
    for index, step in enumerate(definition.steps, start=1):
        expanded: list[tuple[OntologyObjectRecord, ...]] = []
        for path in paths:
            root_id = path[-1].id
            for link in graph.links:
                target_id = None
                if (
                    link.link_type == step.link_type
                    and step.direction == "outgoing"
                    and link.from_id == root_id
                ):
                    target_id = link.to_id
                elif (
                    link.link_type == step.link_type
                    and step.direction == "incoming"
                    and link.to_id == root_id
                ):
                    target_id = link.from_id
                target = objects.get(target_id) if target_id is not None else None
                if target is None or target.object_type != step.selector.name:
                    continue
                expanded.append((*path, target))
                if len(expanded) > definition.limit:
                    raise QueryNodeHeldError("ontology_instance_path_limit_exceeded")
        paths = tuple(expanded)
        if not paths:
            return (), index
    if graph.source_generation is None:
        raise QueryNodeHeldError("ontology_instance_path_generation_unavailable")
    return paths, None


def instance_path_row(path: tuple[OntologyObjectRecord, ...]) -> QueryRow:
    values: dict[str, object] = {
        "root_id": path[0].id,
        "root_type": path[0].object_type,
        "target_id": path[-1].id,
        "target_type": path[-1].object_type,
        "execution_authority": False,
    }
    for index, record in enumerate(path[1:], start=1):
        values[f"step_{index}_id"] = record.id
        values[f"step_{index}_type"] = record.object_type
    return QueryRow.from_values(
        content_digest({"path": [record.id for record in path]}),
        values,
    )


__all__ = ["instance_path_row", "instance_paths"]
