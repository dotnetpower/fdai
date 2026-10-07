"""P2: a traversal cut at its limit states its exact population only from complete reads."""

from __future__ import annotations

import pytest
from fdai.core.ontology_platform import query_traversal_population
from fdai.core.ontology_platform.models import (
    ObjectPredicate,
    ObjectSelector,
    ObjectSelectorKind,
    RelationshipTraversalDefinition,
)
from fdai.core.ontology_platform.query_traversal_population import traversal_population_count
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.acl import ProjectionRequest
from tests.conversation.semantic_reasoning_support import NOW, PURPOSE, fixture_gateway

_REQUEST = ProjectionRequest(caller_role=CeilingRole.READER, declared_purposes=frozenset({PURPOSE}))


def _traversal(**extra: object) -> RelationshipTraversalDefinition:
    return RelationshipTraversalDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        link_types=("contains",),
        direction="outgoing",
        max_depth=5,
        as_of=NOW,
        purpose=PURPOSE,
        limit=2,
        endpoint_predicates=(ObjectPredicate(property="type", equals="compute.vm"),),
        read_population=True,
        **extra,
    )


@pytest.mark.parametrize("batch", [32, 1])
async def test_a_scoped_population_counts_every_reached_member_of_the_kind(
    monkeypatch: pytest.MonkeyPatch, batch: int
) -> None:
    monkeypatch.setattr(query_traversal_population, "POPULATION_FRONTIER_BATCH", batch)

    count = await traversal_population_count(
        await fixture_gateway(),
        _traversal(),
        root_ids=("sub-1",),
        request=_REQUEST,
        expected_generation="fixture-generation",
    )

    assert count == 2


async def test_a_population_beyond_its_read_budget_or_of_another_generation_states_no_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = await fixture_gateway()

    changed = await traversal_population_count(
        gateway,
        _traversal(),
        root_ids=("sub-1",),
        request=_REQUEST,
        expected_generation="another-generation",
    )
    monkeypatch.setattr(query_traversal_population, "POPULATION_READ_BUDGET", 1)
    over_budget = await traversal_population_count(
        gateway,
        _traversal(),
        root_ids=("sub-1",),
        request=_REQUEST,
        expected_generation="fixture-generation",
    )

    assert changed is None
    assert over_budget is None


def test_a_population_read_never_emits_lineage() -> None:
    with pytest.raises(ValueError, match="population reads endpoints"):
        _traversal(emit_lineage=True)
