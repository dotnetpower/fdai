"""Whole-population receipt fields for a cut relationship-free ObjectSet page."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from fdai.shared.contracts.models import OntologyObjectType
from fdai.shared.ontology.acl import ProjectionRequest, project_graph_snapshot
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot

from .models import ObjectSetPopulationStatus


def population_receipt_fields(
    population: OntologyGraphSnapshot | None,
    *,
    object_types: Mapping[str, OntologyObjectType],
    request: ProjectionRequest,
    page_size: int,
    source_complete: bool,
    source_generation: str | None,
) -> dict[str, Any]:
    """Return what a receipt may state about the whole set behind one cut page."""

    status = ObjectSetPopulationStatus.UNKNOWN
    fields: dict[str, Any] = {"schema_version": "1.3.0"}
    if (
        population is not None
        and source_complete
        and population.source_complete
        and population.source_generation == source_generation
    ):
        visible = project_graph_snapshot(population, object_types=object_types, request=request)
        hidden = _redacted_identity_count(visible, object_types)
        if hidden or [item.id for item in visible.objects] != [
            item.id for item in population.objects
        ]:
            status = ObjectSetPopulationStatus.VISIBILITY_INDETERMINATE
        elif len(population.objects) > page_size:
            status = ObjectSetPopulationStatus.COMPLETE
            fields["population_count"] = len(population.objects)
            fields["population_manifest_digest"] = _manifest_digest(
                tuple(item.id for item in population.objects)
            )
    fields["population_status"] = status
    return fields


def _redacted_identity_count(
    graph: OntologyGraphSnapshot,
    object_types: Mapping[str, OntologyObjectType],
) -> int:
    count = 0
    for record in graph.objects:
        raw_redactions = record.properties.get("__redactions__")
        if (
            isinstance(raw_redactions, Mapping)
            and object_types[record.object_type].key in raw_redactions
        ):
            count += 1
    return count


def _manifest_digest(member_ids: tuple[str, ...]) -> str:
    """Hash an ordered population beyond the canonical JSON document cap."""

    digest = hashlib.sha256(b"fdai.population-manifest.v1\n")
    for member_id in member_ids:
        encoded = member_id.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return "sha256:" + digest.hexdigest()


__all__ = ["population_receipt_fields"]
