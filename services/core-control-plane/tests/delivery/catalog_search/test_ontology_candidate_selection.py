"""Typed constraints establish membership, not cosine scores or query-word heuristics."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fdai.core.ontology_platform.models import ObjectPredicate, ObjectSetDefinition
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.delivery.catalog_search.ontology_candidate_reader import OntologyCandidateSearchResult
from fdai.delivery.catalog_search.ontology_candidate_selection import (
    SELECTION_STRATEGY,
    OntologyCandidateClause,
    OntologyCandidateSelection,
)
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai_service_contracts.ontology_query import content_digest
from pydantic import ValidationError
from tests.delivery.catalog_search.test_ontology_evaluation_runner import (
    _Harness,
)
from tests.delivery.catalog_search.test_ontology_evaluation_runner import (
    _harness as _evaluation_harness,
)

_QUERY = "Meaning has already been supplied as typed constraints."


async def _harness(*, semantic_available: bool = True) -> _Harness:
    return await _evaluation_harness(
        semantic_available=semantic_available, typed_selection_available=True
    )


def _bind(harness: _Harness, *clauses: OntologyCandidateClause) -> OntologyCandidateSelection:
    return OntologyCandidateSelection.bind(
        query=_QUERY, manifest=harness.manifest, staged=harness.staged, clauses=clauses
    )


async def _search(
    harness: _Harness, selection: OntologyCandidateSelection, *, limit: int = 20
) -> OntologyCandidateSearchResult:
    return await harness.reader.search(
        _QUERY,
        staged=harness.staged,
        manifest=harness.manifest,
        gateway=harness.gateway,
        as_of=harness.clock.now,
        limit=limit,
        selection=selection,
    )


async def test_typed_union_preserves_matches_without_embedding_or_floor_loss() -> None:
    harness = await _harness()
    harness.embedder.fail_on_call = 1
    selection = _bind(
        harness,
        OntologyCandidateClause(object_type="Incident"),
        OntologyCandidateClause(object_type="Resource", object_ids=("resource-1",)),
        OntologyCandidateClause(object_type="Incident", object_ids=("incident-1",)),
    )
    result = await _search(harness, selection, limit=2)
    assert result.matched_candidate_count == 3
    assert result.returned_candidate_count == 2
    assert result.truncated
    assert result.authorized is not None
    assert [(obj.object_type, obj.id) for obj in result.authorized.objects] == [
        ("Incident", "incident-0"),
        ("Incident", "incident-1"),
    ]
    assert 1 < len(result.authorized.query_receipt_digests) <= 16
    assert result.authority == "candidate_only"
    assert result.execution_authority is False
    assert result.score_kind == "predicate_membership"
    assert all(score == 1.0 for _, score in result.scores)
    assert result.selection_digest is not None
    assert harness.embedder.calls == 0


async def test_conjunctive_no_match_retains_current_scope_evidence() -> None:
    harness = await _harness()
    harness.embedder.fail_on_call = 1
    selection = _bind(
        harness,
        OntologyCandidateClause(
            object_type="Resource",
            predicates=(
                ObjectPredicate(property="id", equals="resource-0"),
                ObjectPredicate(property="id", equals="resource-1"),
            ),
        ),
    )
    result = await _search(harness, selection)
    assert result.matched_candidate_count == result.returned_candidate_count == 0
    assert not result.truncated
    assert result.authorized is not None
    assert result.authorized.objects == ()
    assert len(result.authorized.query_receipt_digests) == 1
    assert harness.embedder.calls == 0


@pytest.mark.parametrize("field", ["query_digest", "manifest_digest", "snapshot_digest"])
async def test_changed_selection_binding_stops_before_graph_access(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    harness = await _harness()
    selection = _bind(harness, OntologyCandidateClause(object_type="Resource"))
    selection = selection.model_copy(update={field: "sha256:" + "b" * 64})
    read = AsyncMock(wraps=harness.gateway.materialize)
    monkeypatch.setattr(harness.gateway, "materialize", read)
    with pytest.raises(ValueError, match="binding"):
        await _search(harness, selection)
    read.assert_not_called()
    assert harness.embedder.calls == 0


async def test_unknown_object_type_stops_before_graph_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness()
    selection = _bind(harness, OntologyCandidateClause(object_type="Undeclared"))
    read = AsyncMock(wraps=harness.gateway.materialize)
    monkeypatch.setattr(harness.gateway, "materialize", read)
    with pytest.raises(ValueError, match="ObjectType"):
        await _search(harness, selection)
    read.assert_not_called()


async def test_unreadable_predicate_uses_existing_gateway_acl_before_store_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness()
    selection = _bind(
        harness,
        OntologyCandidateClause(
            object_type="Resource",
            predicates=(ObjectPredicate(property="private_note", equals="restricted"),),
        ),
    )
    read = AsyncMock(wraps=harness.store.query_objects)
    monkeypatch.setattr(harness.store, "query_objects", read)
    with pytest.raises(PermissionError, match="not readable"):
        await _search(harness, selection)
    read.assert_not_called()


async def test_selection_cannot_enable_unqualified_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness(semantic_available=False)
    selection = _bind(harness, OntologyCandidateClause(object_type="Resource"))
    read = AsyncMock(wraps=harness.gateway.materialize)
    monkeypatch.setattr(harness.gateway, "materialize", read)
    with pytest.raises(ValueError, match="not qualified"):
        await _search(harness, selection)
    read.assert_not_called()
    assert harness.embedder.calls == 0


async def test_current_membership_cannot_introduce_an_unindexed_object() -> None:
    harness = await _harness()
    await harness.store.upsert_object(
        OntologyObjectRecord(
            id="resource-new", object_type="Resource", properties={"id": "resource-new"}
        )
    )
    with pytest.raises(ValueError, match="source content changed"):
        await _search(
            harness, _bind(harness, OntologyCandidateClause(object_type="Resource")), limit=1
        )
    assert harness.embedder.calls == 0


async def test_late_scope_read_cannot_start_another_clause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness()
    selection = _bind(
        harness,
        OntologyCandidateClause(object_type="Incident"),
        OntologyCandidateClause(object_type="Resource"),
    )
    loop, offset = asyncio.get_running_loop(), 0.0
    original_time, materialize = loop.time, harness.gateway.materialize

    async def late(
        definition: ObjectSetDefinition, *, projection_request: ProjectionRequest
    ) -> SecuredObjectSetQueryResult:
        nonlocal offset
        result = await materialize(definition, projection_request=projection_request)
        offset = 5.0
        return result

    read = AsyncMock(side_effect=late)
    monkeypatch.setattr(loop, "time", lambda: original_time() + offset)
    monkeypatch.setattr(harness.gateway, "materialize", read)
    with pytest.raises(TimeoutError, match="deadline"):
        await _search(harness, selection)
    assert read.call_count == 1
    assert harness.embedder.calls == 0


@pytest.mark.parametrize(
    "value",
    [
        {"object_type": ""},
        {"object_type": "Resource", "object_ids": []},
        {"object_type": "Resource", "object_ids": ["resource-0", "resource-0"]},
        {"object_type": "Resource", "purpose": "operations-review"},
        {"object_type": "Resource", "limit": 1},
        {"object_type": "Resource", "traversal": {}},
    ],
)
def test_model_cannot_supply_authority_or_silent_bounds(value: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        OntologyCandidateClause.model_validate(value)


async def test_complete_clause_bound_is_not_silently_truncated() -> None:
    harness = await _harness()
    with pytest.raises(ValidationError):
        _bind(harness, *(OntologyCandidateClause(object_type="Resource") for _ in range(9)))


async def test_raw_ranking_availability_does_not_qualify_the_new_strategy() -> None:
    harness = await _evaluation_harness()
    selection = _bind(harness, OntologyCandidateClause(object_type="Resource"))
    with pytest.raises(ValueError, match="typed selection is not qualified"):
        await _search(harness, selection)
    assert harness.embedder.calls == 0


async def test_exact_query_cannot_silently_ignore_a_mismatched_selection() -> None:
    harness = await _harness()
    with pytest.raises(ValueError, match="binding"):
        await harness.reader.search(
            "resource-0",
            staged=harness.staged,
            manifest=harness.manifest,
            gateway=harness.gateway,
            as_of=harness.clock.now,
            selection=_bind(harness, OntologyCandidateClause(object_type="Resource")),
        )
    assert harness.embedder.calls == 0


@pytest.mark.parametrize("source_state", ["incomplete", "truncated", "changed"])
async def test_unusable_current_scope_cannot_yield_candidates(
    monkeypatch: pytest.MonkeyPatch, source_state: str
) -> None:
    harness = await _harness()
    graph = await harness.store.query_objects(object_types=("Resource",), limit=1000)
    if source_state == "incomplete":
        graph = replace(graph, source_complete=False)
    elif source_state == "truncated":
        graph = replace(graph, truncated=True)
    else:
        graph = replace(graph, source_generation="changed")
    monkeypatch.setattr(harness.store, "query_objects", AsyncMock(return_value=graph))
    with pytest.raises(ValueError, match="complete current evidence"):
        await _search(harness, _bind(harness, OntologyCandidateClause(object_type="Resource")))
    assert harness.embedder.calls == 0


async def test_selection_and_its_digest_are_snapshotted_before_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness()
    selection = _bind(
        harness,
        OntologyCandidateClause(object_type="Incident"),
        OntologyCandidateClause(
            object_type="Resource",
            predicates=(ObjectPredicate(property="id", equals={"nested": [1]}),),
        ),
    )
    expected_digest = content_digest(
        {"strategy": SELECTION_STRATEGY, "selection": selection.model_dump(mode="json")}
    )
    operand = selection.clauses[1].predicates[0].equals
    assert isinstance(operand, dict)
    materialize = harness.gateway.materialize
    definitions: list[ObjectSetDefinition] = []

    async def mutate(
        definition: ObjectSetDefinition, *, projection_request: ProjectionRequest
    ) -> SecuredObjectSetQueryResult:
        definitions.append(definition)
        operand["nested"] = [2]
        await asyncio.sleep(0)
        return await materialize(definition, projection_request=projection_request)

    monkeypatch.setattr(harness.gateway, "materialize", mutate)
    result = await _search(harness, selection)
    assert definitions[1].predicates[0].equals == {"nested": [1]}
    assert result.selection_digest == expected_digest


async def test_invalidation_during_scope_read_holds_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness()
    materialize = harness.gateway.materialize

    async def invalidate(
        definition: ObjectSetDefinition, *, projection_request: ProjectionRequest
    ) -> SecuredObjectSetQueryResult:
        result = await materialize(definition, projection_request=projection_request)
        harness.reader.invalidate()
        return result

    monkeypatch.setattr(harness.gateway, "materialize", invalidate)
    with pytest.raises(ValueError, match="invalidated"):
        await _search(harness, _bind(harness, OntologyCandidateClause(object_type="Resource")))
