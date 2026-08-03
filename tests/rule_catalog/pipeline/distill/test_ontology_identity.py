"""Tests for bounded deterministic ontology entity resolution."""

from __future__ import annotations

import pytest

from fdai.rule_catalog.pipeline.distill.ontology_identity import (
    EntityAliasRecord,
    EntityRecord,
    EntityResolutionRequest,
    resolve_entity_identity,
)
from fdai.rule_catalog.pipeline.distill.ontology_models import OntologyOperation


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: EntityRecord("", "BusinessService"),
        lambda: EntityRecord("service:checkout", ""),
        lambda: EntityRecord("x" * 201, "BusinessService"),
        lambda: EntityAliasRecord("   ", "service:checkout"),
        lambda: EntityAliasRecord("checkout", ""),
        lambda: EntityAliasRecord("x" * 201, "service:checkout"),
        lambda: EntityResolutionRequest("", "BusinessService", OntologyOperation.UPDATE),
        lambda: EntityResolutionRequest("service:checkout", "", OntologyOperation.UPDATE),
    ],
)
def test_identity_inputs_reject_empty_and_oversized_values(constructor: object) -> None:
    with pytest.raises(ValueError):
        constructor()  # type: ignore[operator]


def test_exact_identity_precedes_alias_resolution() -> None:
    resolution = resolve_entity_identity(
        EntityResolutionRequest(
            "service:checkout",
            "BusinessService",
            OntologyOperation.UPDATE,
        ),
        entities=(
            EntityRecord("service:checkout", "BusinessService"),
            EntityRecord("service:other", "BusinessService"),
        ),
        aliases=(EntityAliasRecord("service:checkout", "service:other"),),
    )

    assert resolution.selected_identity == "service:checkout"
    assert resolution.candidates == ("service:checkout",)
    assert resolution.method == "exact"


def test_unique_alias_normalizes_case_and_whitespace() -> None:
    resolution = resolve_entity_identity(
        EntityResolutionRequest("  CHECKOUT   API ", "BusinessService", OntologyOperation.UPDATE),
        entities=(EntityRecord("service:checkout", "BusinessService"),),
        aliases=(EntityAliasRecord("checkout api", "service:checkout"),),
    )

    assert resolution.selected_identity == "service:checkout"
    assert resolution.candidates == ("service:checkout",)
    assert resolution.method == "alias"


def test_ambiguity_at_candidate_limit_is_not_reported_as_truncated() -> None:
    entities = tuple(EntityRecord(f"service:{index:02d}", "BusinessService") for index in range(32))
    aliases = tuple(EntityAliasRecord("checkout", entity.identity) for entity in entities)

    resolution = resolve_entity_identity(
        EntityResolutionRequest("checkout", "BusinessService", OntologyOperation.UPDATE),
        entities=entities,
        aliases=aliases,
    )

    assert resolution.method == "ambiguous_alias"
    assert resolution.candidates == tuple(f"service:{index:02d}" for index in range(32))


def test_alias_collection_rejects_more_than_the_hard_limit() -> None:
    alias = EntityAliasRecord("checkout", "service:checkout")

    with pytest.raises(ValueError, match="alias count exceeds"):
        resolve_entity_identity(
            EntityResolutionRequest("checkout", "BusinessService", OntologyOperation.UPDATE),
            entities=(EntityRecord("service:checkout", "BusinessService"),),
            aliases=(alias,) * 100_001,
        )


def test_alias_resolution_filters_type_and_bounds_ambiguity() -> None:
    entities = tuple(
        EntityRecord(f"service:{index:02d}", "BusinessService") for index in range(40)
    ) + (EntityRecord("workload:ignored", "Workload"),)
    aliases = tuple(EntityAliasRecord("Checkout", entity.identity) for entity in entities)

    resolution = resolve_entity_identity(
        EntityResolutionRequest(" checkout ", "BusinessService", OntologyOperation.UPDATE),
        entities=entities,
        aliases=aliases,
    )

    assert resolution.selected_identity is None
    assert resolution.method == "ambiguous_alias_truncated"
    assert len(resolution.candidates) == 32
    assert resolution.candidates == tuple(f"service:{index:02d}" for index in range(32))
    assert "workload:ignored" not in resolution.candidates


def test_unique_alias_requires_a_known_entity_of_the_target_type() -> None:
    request = EntityResolutionRequest("checkout", "BusinessService", OntologyOperation.UPDATE)
    aliases = (EntityAliasRecord("checkout", "service:missing"),)

    resolution = resolve_entity_identity(request, entities=(), aliases=aliases)

    assert resolution.selected_identity is None
    assert resolution.candidates == ()
    assert resolution.method == "unresolved"
