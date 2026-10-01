from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.conversation.semantic_successive_relations import (
    InMemorySuccessiveRelationContinuationStore,
    RelationEndpoint,
    SuccessiveRelationBinding,
    SuccessiveRelationContinuationInvalidError,
    SuccessiveRelationContinuationIssuer,
    SuccessiveRelationGenerationChangedError,
    relation_endpoints,
)
from fdai.core.ontology_platform.query_execution import QueryNodeResult, QueryPlanExecution
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable

from tests.conversation.test_semantic_reasoning_compiler import _compile, _relation_form

_DIGEST = "sha256:" + ("a" * 64)
_OTHER_DIGEST = "sha256:" + ("b" * 64)
_NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _binding(principal: str = _DIGEST) -> SuccessiveRelationBinding:
    return SuccessiveRelationBinding(
        deployment_scope_digest=_DIGEST,
        principal_digest=principal,
        conversation_id="conversation-a",
        purpose="operations-review",
        admitted_goal_digest=_DIGEST,
        plan_digest=_DIGEST,
        manifest_digest=_DIGEST,
        query_version_digest=_DIGEST,
    )


def _issuer(
    store: InMemorySuccessiveRelationContinuationStore,
    *,
    principal: str = _DIGEST,
) -> SuccessiveRelationContinuationIssuer:
    return SuccessiveRelationContinuationIssuer(
        store=store,
        binding=_binding(principal),
        clock=lambda: _NOW,
    )


async def _all_kinds_goal():
    utterance = "Show every relationship of anchor-resource"
    compilation = _compile(
        utterance,
        _relation_form(
            utterance,
            anchor="anchor-resource",
            sense="dependency",
            position="either",
            cue="every relationship",
            scope="all_kinds",
        ),
    )
    goal = compilation.goals[0]
    assert len(goal.batches) > 1
    return goal


@pytest.mark.asyncio
async def test_successive_relation_pages_list_every_endpoint_with_link_type() -> None:
    goal = await _all_kinds_goal()
    store = InMemorySuccessiveRelationContinuationStore()
    issuer = _issuer(store)
    first_execution = _execution(goal.batches[0])
    page = await issuer.start(goal=goal, first_execution=first_execution)
    listed = list(page.endpoints)
    remaining = len(goal.batches) - 1

    assert page.remaining_batches == remaining
    while page.continuation_ref is not None:
        batch = await issuer.next_batch(page.continuation_ref)
        page = await issuer.complete_batch(
            continuation_ref=page.continuation_ref,
            execution=_execution(batch),
        )
        remaining -= 1
        assert page.remaining_batches == remaining
        listed.extend(page.endpoints)

    expected = []
    for batch in goal.batches:
        expected.extend(relation_endpoints(batch, _execution(batch)))
    assert sorted(_tuples(listed)) == sorted(_tuples(expected))
    assert {"contains", "depends_on", "routes_to"} <= {item.link_type for item in listed}
    assert page.complete is True
    assert remaining == 0


@pytest.mark.asyncio
async def test_successive_relation_generation_change_ends_incomplete() -> None:
    goal = await _all_kinds_goal()
    store = InMemorySuccessiveRelationContinuationStore()
    issuer = _issuer(store)
    page = await issuer.start(goal=goal, first_execution=_execution(goal.batches[0]))
    assert page.continuation_ref is not None
    batch = await issuer.next_batch(page.continuation_ref)
    changed = _with_generation(_execution(batch), "changed-generation")

    with pytest.raises(SuccessiveRelationGenerationChangedError):
        await issuer.complete_batch(continuation_ref=page.continuation_ref, execution=changed)
    with pytest.raises(SuccessiveRelationContinuationInvalidError):
        await issuer.next_batch(page.continuation_ref)


@pytest.mark.asyncio
async def test_successive_relation_rejects_tampered_or_foreign_continuation() -> None:
    goal = await _all_kinds_goal()
    store = InMemorySuccessiveRelationContinuationStore()
    issuer = _issuer(store)
    page = await issuer.start(goal=goal, first_execution=_execution(goal.batches[0]))
    assert page.continuation_ref is not None

    with pytest.raises(SuccessiveRelationContinuationInvalidError):
        await issuer.next_batch("tampered-reference-that-is-not-issued")
    with pytest.raises(SuccessiveRelationContinuationInvalidError):
        await _issuer(store, principal=_OTHER_DIGEST).next_batch(page.continuation_ref)


def _pairs(endpoints: list[RelationEndpoint]) -> set[tuple[str, str]]:
    return {(item.endpoint_name, item.link_type) for item in endpoints}


def _tuples(endpoints: list[RelationEndpoint]) -> list[tuple[str, str, str]]:
    return [(item.endpoint_id, item.endpoint_name, item.link_type) for item in endpoints]


def _with_generation(execution, generation: str):
    results = {}
    for node_id, result in execution.results.items():
        value = result.value
        if isinstance(value, QueryTable):
            result = replace(result, value=replace(value, source_generation=generation))
        results[node_id] = result
    return replace(execution, results=results)


def _execution(batch) -> QueryPlanExecution:
    results = {}
    for node_id in batch.plan.output_node_ids:
        endpoint = f"{node_id}-endpoint"
        table = QueryTable(
            rows=(
                QueryRow.from_values(
                    endpoint,
                    {"properties": {"name": endpoint}},
                ),
            ),
            complete=True,
            source_generation="fixture-generation",
        )
        results[node_id] = QueryNodeResult(value=table)
    return QueryPlanExecution(
        plan_digest=batch.plan.plan_digest,
        status="completed",
        results=results,
        receipts=(),
        output_node_ids=batch.plan.output_node_ids,
    )
