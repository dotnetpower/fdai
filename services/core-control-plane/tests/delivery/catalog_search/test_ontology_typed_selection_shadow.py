"""Runtime typed selection shadow: gated evidence only, never an answer or authority."""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fdai.composition.semantic_query_instance_candidates import declare_instance_candidate_query
from fdai.core.conversation.model_observation import ConversationModelObservation
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.models import ObjectPredicate
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.delivery.azure.llm.semantic_planning_config import candidate_proposal_binding
from fdai.delivery.catalog_search.generation import SemanticGenerationBuild
from fdai.delivery.catalog_search.ontology_candidate_proposal import (
    OntologyCandidateProposal,
    OntologyCandidateProposalResult,
    candidate_proposal_payload,
)
from fdai.delivery.catalog_search.ontology_candidate_reader import (
    OntologyCandidateSearchResult,
)
from fdai.delivery.catalog_search.ontology_candidate_selection import (
    OntologyCandidateClause,
    OntologyCandidateSelection,
)
from fdai.delivery.catalog_search.ontology_index_lifecycle import (
    IndexGeneration,
    IndexPointer,
    IndexScope,
)
from fdai.delivery.catalog_search.ontology_index_workers import OntologyContextIndexWorkers
from fdai.delivery.catalog_search.ontology_snapshot_store import OntologyStagedProjection
from fdai.delivery.catalog_search.ontology_typed_selection_shadow import (
    RUNTIME_PROTOCOL_ID,
    SHADOW_INTENT_PREFIX,
    SHADOW_TERMINAL_PREFIX,
    ShadowInvocation,
    ShadowPrimaryAnswer,
    ShadowTarget,
    TypedSelectionShadowBudget,
    TypedSelectionShadowObserver,
)
from fdai.delivery.catalog_search.ontology_vector_store import OntologyVectorSnapshotStore
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.rule_catalog.schema.property_semantic import empty_property_semantic_registry
from fdai.runtime.ontology_index_runtime import (
    TypedSelectionShadowBinding,
    build_ontology_index_runtime,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.ontology_query import content_digest
from tests.delivery.azure.llm.test_ontology_candidate_proposal import _candidate_config
from tests.delivery.catalog_search.test_ontology_evaluation_runner import _Harness, _harness

_QUERY = "Which resources are affected by the open incident?"
_POLICY = "sha256:" + "d" * 64
_EMPTY = ("<empty>",)
_Step = tuple[str, ...] | None | BaseException | str


class _Proposer:
    """Scripted proposals; the gate and membership checks run on real reader state."""

    def __init__(self, script: Sequence[_Step]) -> None:
        self.script = list(script)
        self.calls = 0
        self.binding = candidate_proposal_binding(_candidate_config())

    def candidate_proposal_binding(self) -> object:
        return self.binding

    async def propose_candidate_selection(
        self,
        *,
        query: str,
        manifest: object,
        build: SemanticGenerationBuild,
        staged: OntologyStagedProjection,
    ) -> OntologyCandidateProposalResult:
        step = self.script[self.calls]
        self.calls += 1
        if isinstance(step, BaseException):
            raise step
        if step == "stall":
            await asyncio.Event().wait()
        payload = candidate_proposal_payload(
            query=query,
            manifest=manifest,  # type: ignore[arg-type]
            build=build,
            staged=staged,
        )
        observation = ConversationModelObservation(model="synthetic", usage=None, trace_call={})
        if step is None:
            proposal = OntologyCandidateProposal(
                status="clarify", reason="unresolved_reference", clauses=(), clause_quotes=()
            )
            return OntologyCandidateProposalResult(
                proposal, None, str(payload["input_digest"]), observation
            )
        assert isinstance(step, tuple)
        clause = (
            OntologyCandidateClause(
                object_type="Resource",
                predicates=(ObjectPredicate(property="id", equals="not-in-the-fixture"),),
            )
            if step == _EMPTY
            else OntologyCandidateClause(object_type="Resource", object_ids=step)
        )
        proposal = OntologyCandidateProposal(
            status="select",
            reason="conditions_proposed",
            clauses=(clause,),
            clause_quotes=(query,),
        )
        selection = OntologyCandidateSelection.bind(
            query=query,
            manifest=manifest,  # type: ignore[arg-type]
            staged=staged,
            clauses=proposal.clauses,
        )
        return OntologyCandidateProposalResult(
            proposal, selection, str(payload["input_digest"]), observation
        )


def _scope(harness: _Harness) -> IndexScope:
    return IndexScope(
        principal_scope_digest=harness.manifest.coverage_receipt.principal_scope_digest,
        role=CeilingRole(harness.manifest.principal_role.value),
        purpose="operations-review",
    )


def _target(harness: _Harness) -> ShadowTarget:
    scope = _scope(harness)
    digest = "sha256:" + "a" * 64
    generation = IndexGeneration(
        scope=scope,
        manifest_digest=harness.manifest.manifest_digest,
        ontology_release_digest=harness.manifest.release_digest,
        source_generation=harness.staged.source_generation,
        source_projection_digest=harness.staged.source_projection_digest,
        snapshot_digest=harness.staged.snapshot_digest,
        vector_digest=digest,
        generation_digest=harness.build.metadata.generation_digest,
        validation_receipt_digest=digest,
        embedding_space_id="test-space",
        embedding_model_version="test-model-v1",
        embedding_dimension=4,
    )
    return ShadowTarget(
        # The observer reads only revision and active identity; terminal sealing is the
        # workers' resolver responsibility and is covered by their own tests.
        pointer=IndexPointer.model_construct(scope=scope, revision=1, active=generation),
        staged=harness.staged,
        manifest=harness.manifest,
        gateway=harness.gateway,
    )


async def _observer(
    script: Sequence[_Step],
    *,
    budget: TypedSelectionShadowBudget | None = None,
    store: InMemoryStateStore | None = None,
    harness: _Harness | None = None,
) -> tuple[TypedSelectionShadowObserver, _Proposer, InMemoryStateStore, _Harness]:
    harness = harness or await _harness(semantic_available=False, typed_selection_shadow=True)
    proposer = _Proposer(script)
    store = store or InMemoryStateStore()
    observer = TypedSelectionShadowObserver(
        proposer=proposer,  # type: ignore[arg-type]
        reader=harness.reader,
        snapshots=harness.snapshots,
        store=store,
        clock=lambda: harness.clock.now,
        data_handling_policy_digest=_POLICY,
        expected_binding=proposer.binding,
        budget=budget,
    )
    return observer, proposer, store, harness


def _invocation(harness: _Harness, primary: ShadowPrimaryAnswer) -> ShadowInvocation:
    return ShadowInvocation(
        query=_QUERY,
        limit=20,
        scope=_scope(harness),
        primary=primary,
        request_ref="request-1",
    )


async def _observe(
    observer: TypedSelectionShadowObserver,
    harness: _Harness,
    *,
    primary: ShadowPrimaryAnswer | None = None,
    current: bool = True,
) -> dict[str, object] | None:
    target = _target(harness)

    async def resolve(_scope: IndexScope) -> ShadowTarget:
        return target

    async def still_current(_scope: IndexScope, _target: ShadowTarget) -> bool:
        return current

    return await observer.observe(
        _invocation(harness, primary or ShadowPrimaryAnswer.unavailable(ValueError())),
        resolve=resolve,
        current=still_current,
    )


def _rows(store: InMemoryStateStore, prefix: str) -> list[dict[str, object]]:
    return [dict(value) for key, value in store._state.items() if key.startswith(prefix)]


async def test_agreed_verified_membership_is_recorded_without_query_text() -> None:
    observer, proposer, store, harness = await _observer([("resource-1",), ("resource-1",)])
    harness.embedder.fail_on_call = 1
    record = await _observe(observer, harness)
    assert record is not None
    assert proposer.calls == 2
    assert harness.embedder.calls == 0
    assert record["gated_outcome"] == "selected"
    assert record["gated_document_ids"] == ["object:Resource:resource-1"]
    assert record["comparison"] == "primary_unavailable"
    assert record["protocol_id"] == RUNTIME_PROTOCOL_ID
    assert record["answer_changed"] is False
    assert record["execution_authority"] is False
    assert record["data_handling_policy_digest"] == _POLICY
    assert record["query_digest"] == content_digest({"query": _QUERY})
    assert record["record_digest"] == content_digest(
        {key: value for key, value in record.items() if key != "record_digest"}
    )
    passes = record["passes"]
    assert isinstance(passes, list)
    assert all(item["query_receipt_digests"] for item in passes)
    intents = _rows(store, SHADOW_INTENT_PREFIX)
    terminals = _rows(store, SHADOW_TERMINAL_PREFIX)
    assert [item["observation_id"] for item in intents] == [record["observation_id"]]
    assert terminals == [record]
    assert _QUERY not in json.dumps([intents, terminals])


async def test_same_membership_compares_against_returned_answer() -> None:
    observer, _proposer, _store, harness = await _observer([("resource-0",), ("resource-0",)])
    primary = ShadowPrimaryAnswer.returned(
        OntologyCandidateSearchResult(
            None, 1, 1, False, (("object:Resource:resource-0", 1.0),), "m", "r"
        ),
        result_digest="sha256:" + "e" * 64,
    )
    record = await _observe(observer, harness, primary=primary)
    assert record is not None
    assert record["comparison"] == "same_membership"


@pytest.mark.parametrize(
    ("script", "outcome", "status_agreement"),
    [
        ([("resource-0",), ("resource-1",)], "disagreed", True),
        ([None, None], "empty", True),
        ([None, _EMPTY], "empty", False),
        ([None, ("resource-0",)], "disagreed", False),
    ],
)
async def test_gate_uses_the_qualification_set_equality_rule(
    script: list[_Step], outcome: str, status_agreement: bool
) -> None:
    observer, _proposer, _store, harness = await _observer(script)
    record = await _observe(observer, harness)
    assert record is not None
    assert record["gated_outcome"] == outcome
    assert record["status_agreement"] is status_agreement
    if outcome != "empty":
        assert record["gated_document_ids"] == []


async def test_provider_failure_is_typed_and_never_retried() -> None:
    observer, proposer, store, harness = await _observer(
        [RuntimeError("private provider detail"), ("resource-0",)]
    )
    record = await _observe(observer, harness)
    assert record is not None
    assert proposer.calls == 2
    assert record["gated_outcome"] == "unavailable"
    assert record["unavailable_reason"] == "proposal_unavailable"
    assert record["comparison"] == "shadow_unavailable"
    assert "private provider detail" not in json.dumps(_rows(store, SHADOW_TERMINAL_PREFIX))


async def test_changed_proposer_binding_stops_before_any_call() -> None:
    observer, proposer, _store, harness = await _observer([("resource-0",), ("resource-0",)])
    observer._expected_binding = replace(proposer.binding, target_digest="sha256:" + "f" * 64)
    record = await _observe(observer, harness)
    assert record is not None
    assert proposer.calls == 0
    assert record["unavailable_reason"] == "proposal_binding_changed"


async def test_pointer_change_during_observation_is_not_counted_as_agreement() -> None:
    observer, _proposer, _store, harness = await _observer([("resource-0",), ("resource-0",)])
    record = await _observe(observer, harness, current=False)
    assert record is not None
    assert record["gated_outcome"] == "unavailable"
    assert record["unavailable_reason"] == "index_changed"


async def test_total_deadline_bounds_a_stalled_provider() -> None:
    observer, _proposer, _store, harness = await _observer(
        ["stall", "stall"], budget=TypedSelectionShadowBudget(total_timeout_seconds=0.05)
    )
    record = await _observe(observer, harness)
    assert record is not None
    assert record["unavailable_reason"] == "deadline_exceeded"


async def test_durable_quota_is_shared_across_observers() -> None:
    budget = TypedSelectionShadowBudget(
        max_observations_per_hour=1, max_principal_observations_per_hour=1
    )
    first, _proposer, store, harness = await _observer(
        [("resource-0",), ("resource-0",)], budget=budget
    )
    assert await _observe(first, harness) is not None
    second, proposer, _store, _harness_again = await _observer(
        [("resource-0",), ("resource-0",)], budget=budget, store=store, harness=harness
    )
    assert await _observe(second, harness) is None
    assert proposer.calls == 0
    assert second.skipped["shadow_budget_exhausted"] == 1
    assert len(_rows(store, SHADOW_TERMINAL_PREFIX)) == 1


async def test_principal_quota_is_separate_from_deployment_quota() -> None:
    budget = TypedSelectionShadowBudget(
        max_observations_per_hour=5, max_principal_observations_per_hour=1
    )
    observer, _proposer, _store, harness = await _observer([("resource-0",)] * 4, budget=budget)
    assert await _observe(observer, harness) is not None
    assert await _observe(observer, harness) is None
    assert observer.skipped["principal_budget_exhausted"] == 1


async def test_capacity_skips_are_reported_and_shutdown_records_cancellation() -> None:
    observer, proposer, store, harness = await _observer(["stall", "stall"])
    target = _target(harness)

    async def resolve(_scope: IndexScope) -> ShadowTarget:
        return target

    async def current(_scope: IndexScope, _target: ShadowTarget) -> bool:
        return True

    invocation = _invocation(harness, ShadowPrimaryAnswer.unavailable(ValueError()))
    first = observer.schedule(invocation, resolve=resolve, current=current)
    assert first is not None
    assert observer.schedule(invocation, resolve=resolve, current=current) is None
    assert observer.skipped["shadow_capacity"] == 1
    while proposer.calls < 2:
        await asyncio.sleep(0)
    await observer.aclose()
    assert observer.in_flight == 0
    terminals = _rows(store, SHADOW_TERMINAL_PREFIX)
    assert [item["unavailable_reason"] for item in terminals] == ["cancelled"]
    assert terminals[0]["skipped_before"] == {
        "shadow_capacity": 1,
        "shadow_budget_exhausted": 0,
        "principal_budget_exhausted": 0,
        "schedule_failed": 0,
        "observation_unrecorded": 0,
    }
    assert observer.skipped["shadow_capacity"] == 0


async def test_schedule_never_raises_into_the_answer_path() -> None:
    observer, _proposer, _store, harness = await _observer([])

    async def resolve(_scope: IndexScope) -> ShadowTarget:
        raise AssertionError("unreachable")

    async def current(_scope: IndexScope, _target: ShadowTarget) -> bool:
        raise AssertionError("unreachable")

    invocation = _invocation(harness, ShadowPrimaryAnswer.unavailable(ValueError()))
    result: list[object] = []

    def outside_loop() -> None:
        result.append(observer.schedule(invocation, resolve=resolve, current=current))

    await asyncio.to_thread(outside_loop)
    assert result == [None]
    assert observer.skipped["schedule_failed"] == 1


async def test_unavailable_index_is_a_typed_outcome() -> None:
    observer, proposer, _store, harness = await _observer([("resource-0",)])

    async def resolve(_scope: IndexScope) -> ShadowTarget:
        raise ValueError("ontology instance index has no current active generation")

    async def current(_scope: IndexScope, _target: ShadowTarget) -> bool:
        return True

    record = await observer.observe(
        _invocation(harness, ShadowPrimaryAnswer.unavailable(ValueError())),
        resolve=resolve,
        current=current,
    )
    assert record is not None
    assert record["unavailable_reason"] == "index_unavailable"
    assert proposer.calls == 0


async def test_shadow_capability_cannot_enable_answer_path_selection() -> None:
    harness = await _harness(semantic_available=False, typed_selection_shadow=True)
    selection = OntologyCandidateSelection.bind(
        query=_QUERY,
        manifest=harness.manifest,
        staged=harness.staged,
        clauses=(OntologyCandidateClause(object_type="Resource"),),
    )
    with pytest.raises(ValueError, match="not qualified"):
        await harness.reader.search(
            _QUERY,
            staged=harness.staged,
            manifest=harness.manifest,
            gateway=harness.gateway,
            as_of=harness.clock.now,
            selection=selection,
        )
    with pytest.raises(ValueError, match="semantic ranking is not qualified"):
        await harness.reader.search(
            _QUERY,
            staged=harness.staged,
            manifest=harness.manifest,
            gateway=harness.gateway,
            as_of=harness.clock.now,
        )
    plain = await _harness(semantic_available=False)
    with pytest.raises(ValueError, match="shadow is not enabled"):
        await plain.reader.shadow_select(
            _QUERY,
            staged=plain.staged,
            manifest=plain.manifest,
            gateway=plain.gateway,
            as_of=plain.clock.now,
            selection=selection,
        )


def test_budget_and_policy_must_stay_bounded() -> None:
    with pytest.raises(ValueError, match="bounded"):
        TypedSelectionShadowBudget(total_timeout_seconds=31)
    with pytest.raises(ValueError, match="bounded"):
        TypedSelectionShadowBudget(
            max_observations_per_hour=2, max_principal_observations_per_hour=3
        )


class _RecordingShadow:
    def __init__(self) -> None:
        self.invocations: list[ShadowInvocation] = []

    def schedule(self, invocation: ShadowInvocation, **_bindings: object) -> None:
        self.invocations.append(invocation)


def _workers(harness: _Harness, shadow: object) -> OntologyContextIndexWorkers:
    store = InMemoryStateStore()

    async def resolve_source(_scope: IndexScope) -> tuple[object, object]:
        return harness.manifest, harness.gateway

    return OntologyContextIndexWorkers(
        store=store,
        snapshots=harness.snapshots,
        vectors=OntologyVectorSnapshotStore(
            store,
            embedder=harness.embedder,
            embedding_space_id="test-space",
            embedding_model_version="test-model-v1",
            embedding_dimension=4,
        ),
        reader=harness.reader,
        resolve_source=resolve_source,  # type: ignore[arg-type]
        clock=lambda: harness.clock.now,
        embedding_space_id="test-space",
        embedding_model_version="test-model-v1",
        embedding_dimension=4,
        typed_selection_shadow=shadow,  # type: ignore[arg-type]
    )


def _context(harness: _Harness) -> FunctionInvocationContext:
    return FunctionInvocationContext(
        caller_agent="Bragi",
        principal_ref="example-reader",
        principal_scope_digest=harness.manifest.coverage_receipt.principal_scope_digest,
        purposes=("operations-review",),
        authentication_request_ref="request-1",
    )


async def test_workers_return_the_same_answer_and_exact_error_with_shadow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness(semantic_available=False, typed_selection_shadow=True)
    result = OntologyCandidateSearchResult(
        None,
        1,
        1,
        False,
        (("object:Resource:resource-0", 1.0),),
        harness.manifest.manifest_digest,
        harness.manifest.release_digest,
        score_kind="exact_identity",
    )
    recording = _RecordingShadow()
    plain, shadowed = _workers(harness, None), _workers(harness, recording)
    for workers in (plain, shadowed):

        async def search_current(*_args: object, **_kwargs: object) -> object:
            return result

        monkeypatch.setattr(workers, "search_current", search_current)
    expected = await plain.query_function(_QUERY, 20, _context(harness))
    observed = await shadowed.query_function(_QUERY, 20, _context(harness))
    assert observed == expected
    assert [item.primary.outcome for item in recording.invocations] == ["returned"]
    assert recording.invocations[0].primary.result_digest == expected["result_digest"]
    assert recording.invocations[0].request_ref == "request-1"
    failure = ValueError("ontology instance semantic ranking is not qualified")

    async def failing_search(*_args: object, **_kwargs: object) -> object:
        raise failure

    monkeypatch.setattr(shadowed, "search_current", failing_search)
    with pytest.raises(ValueError) as raised:
        await shadowed.query_function(_QUERY, 20, _context(harness))
    assert raised.value is failure
    assert recording.invocations[-1].primary == ShadowPrimaryAnswer(
        outcome="unavailable", failure_type="ValueError"
    )


async def test_workers_never_await_a_running_shadow_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer, proposer, store, harness = await _observer(["stall", "stall"])
    workers = _workers(harness, observer)
    failure = ValueError("ontology instance semantic ranking is not qualified")

    async def failing_search(*_args: object, **_kwargs: object) -> object:
        raise failure

    async def resolve(_scope: IndexScope) -> ShadowTarget:
        return _target(harness)

    monkeypatch.setattr(workers, "search_current", failing_search)
    monkeypatch.setattr(workers, "_current_target", resolve)
    with pytest.raises(ValueError) as raised:
        await asyncio.wait_for(workers.query_function(_QUERY, 20, _context(harness)), 1)
    assert raised.value is failure
    assert observer.in_flight == 1
    while proposer.calls < 2:
        await asyncio.sleep(0)
    await workers.aclose_shadow()
    assert observer.in_flight == 0
    assert [item["unavailable_reason"] for item in _rows(store, SHADOW_TERMINAL_PREFIX)] == [
        "cancelled"
    ]


class _GovernedEmbedder:
    embedding_space_id = "test-space"
    embedding_model_version = "test-model"
    dim = 4

    async def embed(self, text: str) -> tuple[float, ...]:
        raise AssertionError("factory binding never calls a provider")


async def test_runtime_factory_binds_only_shadow_and_cancels_it_on_stop() -> None:
    declaration = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    catalog = declare_instance_candidate_query(
        OntologyCatalog(
            object_types=(declaration,),
            link_types=(),
            interface_types=(),
            interface_implementations=(),
            action_types=(),
            property_semantics=empty_property_semantic_registry(),
        )
    )
    options = dict(
        store=InMemoryStateStore(),
        ontology_store=InMemoryOntologyInstanceStore(
            object_types=(declaration,), link_types=(), source_generation="source-1"
        ),
        catalog=catalog,
        release=build_ontology_release(
            object_types=catalog.object_types,
            function_types=operational_function_types(catalog.function_types),
        ),
        embedder=_GovernedEmbedder(),
        clock=lambda: datetime(2026, 10, 8, tzinfo=UTC),
    )
    plain = build_ontology_index_runtime(**options)  # type: ignore[arg-type]
    assert plain is not None and plain.workers is not None
    assert plain.workers._typed_selection_shadow is None
    assert plain.workers._reader._typed_selection_shadow is False
    proposer = _Proposer([])
    shadowed = build_ontology_index_runtime(
        **options,  # type: ignore[arg-type]
        typed_selection_shadow=TypedSelectionShadowBinding(
            proposer=proposer,  # type: ignore[arg-type]
            data_handling_policy_digest=_POLICY,
            expected_binding=proposer.binding,
        ),
    )
    assert shadowed is not None and shadowed.workers is not None
    reader = shadowed.workers._reader
    assert reader._typed_selection_shadow is True
    assert reader._semantic_search_available is False
    assert reader._typed_selection_available is False
    assert isinstance(shadowed.workers._typed_selection_shadow, TypedSelectionShadowObserver)
    close = AsyncMock()
    shadowed.workers.aclose_shadow = close  # type: ignore[method-assign]
    stop = asyncio.Event()
    stop.set()
    await shadowed.run(object(), stop)  # type: ignore[arg-type]
    close.assert_awaited_once()
    assert proposer.calls == 0


async def test_evidence_write_failure_is_counted_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer, proposer, store, harness = await _observer([("resource-0",), ("resource-0",)])

    async def unavailable(_key: str, _value: object) -> bool:
        raise RuntimeError("state store unavailable")

    monkeypatch.setattr(store, "write_state_if_absent", unavailable)

    async def resolve(_scope: IndexScope) -> ShadowTarget:
        return _target(harness)

    async def current(_scope: IndexScope, _target: ShadowTarget) -> bool:
        return True

    task = observer.schedule(
        _invocation(harness, ShadowPrimaryAnswer.unavailable(ValueError())),
        resolve=resolve,
        current=current,
    )
    assert task is not None
    await task
    assert proposer.calls == 0
    assert observer.skipped["observation_unrecorded"] == 1


async def test_membership_from_another_source_is_drift_not_disagreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer, _proposer, _store, harness = await _observer([("resource-0",), ("resource-0",)])
    original = harness.reader.shadow_select

    async def drifted(*args: object, **kwargs: object) -> OntologyCandidateSearchResult:
        result = await original(*args, **kwargs)  # type: ignore[arg-type]
        assert result.authorized is not None
        return replace(result, authorized=replace(result.authorized, source_generation="other"))

    monkeypatch.setattr(harness.reader, "shadow_select", drifted)
    record = await _observe(observer, harness)
    assert record is not None
    assert record["unavailable_reason"] == "source_drift"
