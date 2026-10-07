"""Canonical digests for secured ontology query results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot

from .functions import ontology_function_digest
from .models import (
    ObjectSetMaterialization,
    OntologyInstancePathDefinition,
)


def projected_result_digest(materialization: ObjectSetMaterialization) -> str:
    """Return the function-bound digest of a secured ObjectSet result."""

    graph = materialization.graph
    payload = {
        "definition": materialization.definition.model_dump(mode="json"),
        "objects": [
            {
                "id": record.id,
                "object_type": record.object_type,
                "properties": _mutable_json(record.properties),
                "revision": record.revision,
                "type_ref": (
                    record.type_ref.model_dump(mode="json") if record.type_ref is not None else None
                ),
            }
            for record in graph.objects
        ],
        "links": [
            {
                "link_type": link.link_type,
                "from_id": link.from_id,
                "to_id": link.to_id,
                "properties": _mutable_json(link.properties),
                "type_ref": (
                    link.type_ref.model_dump(mode="json") if link.type_ref is not None else None
                ),
            }
            for link in graph.links
        ],
        "graph_truncated": graph.truncated,
        "concrete_types": list(materialization.concrete_types),
        "truncated": materialization.truncated,
        "truncation_reason": (
            materialization.truncation_reason.value
            if materialization.truncation_reason is not None
            else None
        ),
    }
    if not graph.source_complete or graph.source_generation is not None:
        payload["source_complete"] = graph.source_complete
        payload["source_generation"] = graph.source_generation
    if graph.source_incomplete_reason is not None:
        payload["source_incomplete_reason"] = graph.source_incomplete_reason
    return ontology_function_digest(payload)


def instance_path_graph_digest(
    definition: OntologyInstancePathDefinition,
    graph: OntologyGraphSnapshot,
) -> str:
    """Return the content digest of one secured instance-path graph."""

    return content_digest(
        {
            "definition": definition.model_dump(mode="json"),
            "objects": [
                {
                    "id": record.id,
                    "object_type": record.object_type,
                    "properties": _mutable_json(record.properties),
                    "revision": record.revision,
                    "type_ref": (
                        record.type_ref.model_dump(mode="json")
                        if record.type_ref is not None
                        else None
                    ),
                }
                for record in graph.objects
            ],
            "links": [
                {
                    "link_type": link.link_type,
                    "from_id": link.from_id,
                    "to_id": link.to_id,
                    "properties": _mutable_json(link.properties),
                    "type_ref": (
                        link.type_ref.model_dump(mode="json") if link.type_ref is not None else None
                    ),
                }
                for link in graph.links
            ],
            "source_complete": graph.source_complete,
            "source_generation": graph.source_generation,
            "truncated": graph.truncated,
        }
    )


def _mutable_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _mutable_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_mutable_json(item) for item in value]
    return value


__all__ = ["instance_path_graph_digest", "projected_result_digest"]
