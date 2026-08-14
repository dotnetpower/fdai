"""Canonical source-derived FunctionTypes for operational competencies."""

from __future__ import annotations

from collections.abc import Sequence

from fdai.shared.contracts.models import OntologyFunctionType

from .catalog_queries import catalog_search_rules_function_type
from .incident_queries import incident_evidence_function_type
from .network_path import network_path_function_type
from .pod_telemetry import pod_telemetry_function_type
from .relationship_queries import ontology_relationships_function_type


def operational_function_types(
    catalog_functions: Sequence[OntologyFunctionType],
) -> tuple[OntologyFunctionType, ...]:
    """Combine reviewed catalog functions with source-derived competency functions."""

    combined = tuple(catalog_functions) + (
        catalog_search_rules_function_type(),
        incident_evidence_function_type(),
        network_path_function_type(),
        ontology_relationships_function_type(),
        pod_telemetry_function_type(),
    )
    names = [item.name for item in combined]
    if len(names) != len(set(names)):
        raise ValueError("operational ontology FunctionType names MUST be unique")
    return tuple(sorted(combined, key=lambda item: item.name))


__all__ = ["operational_function_types"]
