"""Exact-release registration for authenticated ontology instance candidates."""

from __future__ import annotations

from dataclasses import replace

from fdai.core.ontology_platform.functions import OntologyFunctionRegistry
from fdai.core.ontology_platform.instance_candidate_queries import (
    INSTANCE_CANDIDATES_FUNCTION_NAME,
    InstanceCandidateQuery,
    instance_candidates_function,
    instance_candidates_function_type,
)
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog


def declare_instance_candidate_query(catalog: OntologyCatalog) -> OntologyCatalog:
    """Include the source-derived read contract without making an index available."""
    declaration = instance_candidates_function_type(
        object_type_names=tuple(item.name for item in catalog.object_types),
    )
    existing = next(
        (item for item in catalog.function_types if item.name == declaration.name), None
    )
    if existing is not None:
        if existing != declaration:
            raise ValueError("ontology candidate declaration conflicts with source contract")
        return catalog
    return replace(catalog, function_types=(*catalog.function_types, declaration))


def bind_instance_candidate_query(
    registry: OntologyFunctionRegistry,
    catalog: OntologyCatalog,
    query: InstanceCandidateQuery | None,
) -> None:
    """Register only an explicit source-derived declaration and trusted read callback."""
    if query is None:
        return
    declaration = next(
        (item for item in catalog.function_types if item.name == INSTANCE_CANDIDATES_FUNCTION_NAME),
        None,
    )
    expected = instance_candidates_function_type(
        object_type_names=tuple(item.name for item in catalog.object_types),
    )
    if declaration != expected:
        raise ValueError("ontology candidate binding requires its exact declared read sets")
    registry.register_contextual(
        declaration,
        instance_candidates_function(query, ontology_release_digest=registry.release_ref.digest),
    )
