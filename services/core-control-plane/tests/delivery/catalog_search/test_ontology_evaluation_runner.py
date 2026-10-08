"""Actual snapshot/vector/reader measurements with a deterministic test-only embedder."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.object_sets import ObjectSetService
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.delivery.catalog_search.generation import SemanticGenerationBuild
from fdai.delivery.catalog_search.ontology_candidate_reader import OntologyInstanceCandidateReader
from fdai.delivery.catalog_search.ontology_evaluation import (
    OntologyRetrievalEvaluationCase,
    prepare_ontology_retrieval_evaluation,
)
from fdai.delivery.catalog_search.ontology_evaluation_runner import (
    OntologyRetrievalEvaluationAbortedError,
    OntologyRetrievalEvaluationReport,
    run_ontology_retrieval_evaluation,
)
from fdai.delivery.catalog_search.ontology_snapshot_store import (
    OntologyGenerationSnapshotStore,
    OntologyStagedProjection,
)
from fdai.delivery.catalog_search.ontology_snapshot_validation import (
    validate_snapshot_against_current_graph,
)
from fdai.delivery.catalog_search.ontology_vector_store import OntologyVectorSnapshotStore
from fdai.delivery.catalog_search.ranking import CatalogRankingPolicy
from fdai.shared.contracts.models import OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.delivery.catalog_search.test_ontology_evaluation import (
    _POLICY,
    _TYPES,
    _cases,
    _manifest,
    _objects,
)

_NOW = datetime(2026, 10, 1, tzinfo=UTC)
_RANKING = CatalogRankingPolicy(minimum_score=0.5, lexical_weight=0, semantic_weight=1)


class _Embedder:
    calls = 0
    fail_on_call: int | None = None
    stall = False
    wrong = False

    def __init__(self, extra_cases: tuple[OntologyRetrievalEvaluationCase, ...] = ()) -> None:
        self.cases = (*_cases(), *extra_cases)

    async def embed(self, text: str) -> tuple[float, ...]:
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("private-provider-error")
        if self.stall:
            await asyncio.Event().wait()
        ids = tuple(f"object:{item.object_type}:{item.id}" for item in _objects())
        if text.startswith("{"):
            payload = json.loads(text)
            selected = (
                f"object:{payload['object_type']}:{payload['id']}"
                if "object_type" in payload
                else ids[0]
            )
        else:
            case = next(item for item in self.cases if item.query == text)
            selected = case.expected_document_ids[0] if case.expected_document_ids else None
            if self.wrong:
                selected = None
        if selected is None:
            return tuple(-1.0 for _item in ids)
        return tuple(1.0 if item == selected else 0.0 for item in ids)


@dataclass
class _Clock:
    now: datetime = _NOW


@dataclass
class _Harness:
    run: Callable[
        [str | None, float, datetime | None], Awaitable[OntologyRetrievalEvaluationReport]
    ]
    embedder: _Embedder
    store: InMemoryOntologyInstanceStore
    reader: OntologyInstanceCandidateReader
    clock: _Clock
    build: SemanticGenerationBuild
    manifest: QueryManifest
    gateway: SecuredObjectSetQueryGateway
    snapshots: OntologyGenerationSnapshotStore
    staged: OntologyStagedProjection


async def _harness(
    *,
    semantic_available: bool = True,
    typed_selection_available: bool = False,
    typed_selection_shadow: bool = False,
    empty_last: bool = False,
    extra_cases: tuple[OntologyRetrievalEvaluationCase, ...] = (),
) -> _Harness:
    manifest = _manifest()
    clock = _Clock()
    cases = _cases()
    if empty_last:
        cases = tuple(sorted(cases, key=lambda item: not bool(item.expected_document_ids)))
    declarations = tuple(
        OntologyObjectType(
            schema_version="1.0.0",
            name=name,
            version="1.0.0",
            key="id",
            properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
        )
        for name in _TYPES
    )
    store = InMemoryOntologyInstanceStore(
        object_types=declarations, link_types=(), source_generation="evaluation-source"
    )
    for record in _objects():
        await store.upsert_object(record)
    gateway = SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=store,
            interfaces=compile_interfaces(
                interfaces=(), implementations=(), object_types=declarations
            ),
            object_type_names=frozenset(_TYPES),
        ),
        object_types={item.name: item for item in declarations},
        ontology_release=build_ontology_release(object_types=declarations),
        evaluation_cutoff=lambda: clock.now,
        max_as_of_skew=timedelta(seconds=5),
    )
    state = InMemoryStateStore()
    snapshots = OntologyGenerationSnapshotStore(state)
    staged = await snapshots.stage_manifest_from_gateway(
        gateway=gateway,
        manifest=manifest,
        as_of=_NOW,
        expected_source_generation="evaluation-source",
        embedding_space_id="test-space",
        embedding_model_version="test-model-v1",
        embedding_dimension=4,
    )
    build = await snapshots.read(
        staged.snapshot_digest,
        manifest=manifest,
        source_generation=staged.source_generation,
        source_projection_digest=staged.source_projection_digest,
    )
    assert build is not None
    embedder = _Embedder(extra_cases)
    vectors = OntologyVectorSnapshotStore(
        state,
        embedder=embedder,
        embedding_space_id="test-space",
        embedding_model_version="test-model-v1",
        embedding_dimension=4,
    )
    vector_digest = await vectors.stage(
        snapshots=snapshots,
        snapshot_digest=staged.snapshot_digest,
        manifest=manifest,
        source_generation=staged.source_generation,
        source_projection_digest=staged.source_projection_digest,
    )
    validation = await validate_snapshot_against_current_graph(
        snapshots=snapshots,
        staged=staged,
        gateway=gateway,
        manifest=manifest,
        as_of=_NOW,
        embedding_space_id="test-space",
        embedding_model_version="test-model-v1",
        embedding_dimension=4,
        validator_id="Heimdall",
    )
    reader = OntologyInstanceCandidateReader(
        snapshots=snapshots,
        vectors=vectors,
        ranking_policy=_RANKING,
        semantic_search_available=semantic_available,
        typed_selection_available=typed_selection_available,
        typed_selection_shadow=typed_selection_shadow,
    )
    await reader.prepare(
        staged=staged, vector_digest=vector_digest, manifest=manifest, validation=validation
    )
    plan = prepare_ontology_retrieval_evaluation(
        build=build,
        manifest=manifest,
        cases=cases,
        calibration_queries=(),
        ranking_policy=_RANKING,
        evaluation_policy=_POLICY,
        required_object_types=_TYPES,
    )
    assert embedder.calls == plan.document_count
    embedder.calls = 0

    async def run(
        expected: str | None = None,
        timeout: float = 1,
        as_of: datetime | None = None,
    ) -> OntologyRetrievalEvaluationReport:
        return await run_ontology_retrieval_evaluation(
            expected_binding_digest=expected or plan.binding_digest,
            build=build,
            manifest=manifest,
            cases=cases,
            calibration_queries=(),
            ranking_policy=_RANKING,
            evaluation_policy=_POLICY,
            required_object_types=_TYPES,
            reader=reader,
            snapshots=snapshots,
            staged=staged,
            gateway=gateway,
            clock=lambda: as_of if as_of is not None else clock.now,
            total_timeout_seconds=timeout,
            query_timeout_seconds=timeout,
        )

    return _Harness(
        run, embedder, store, reader, clock, build, manifest, gateway, snapshots, staged
    )


async def test_measures_real_reader_without_qualifying_synthetic_vectors() -> None:
    harness = await _harness()
    report = await harness.run(None, 1, _NOW)
    assert report.passed
    assert len(report.measurements) == harness.embedder.calls == 20
    assert len(report.cohort_metrics) == 10
    assert all(item.value == 1 and item.sample_count >= 2 for item in report.cohort_metrics)
    assert report.production_qualification is False
    assert report.execution_authority is False
    assert len(report.source_validations) == 2
    assert all(item.checked_at == _NOW for item in report.source_validations)
    assert report.digest.startswith("sha256:")


async def test_wrong_predictions_cannot_pass_or_change_the_frozen_threshold() -> None:
    harness = await _harness()
    harness.embedder.wrong = True
    report = await harness.run(None, 1, _NOW)
    assert not report.passed
    assert report.failure_codes == (
        "en-positive-mean-reciprocal-rank-below-threshold",
        "en-positive-recall-at-5-below-threshold",
        "ko-positive-mean-reciprocal-rank-below-threshold",
        "ko-positive-recall-at-5-below-threshold",
    )


async def test_provider_failure_aborts_once_without_no_match_credit() -> None:
    harness = await _harness()
    harness.embedder.fail_on_call = 3
    with pytest.raises(OntologyRetrievalEvaluationAbortedError) as failure:
        await harness.run(None, 1, _NOW)
    assert len(failure.value.completed) == 2
    assert harness.embedder.calls == 3
    assert "private" not in str(failure.value)


@pytest.mark.parametrize("failure", ["disabled", "invalidated", "binding", "timeout"])
async def test_closed_reader_or_drift_cannot_be_bypassed(failure: str) -> None:
    harness = await _harness(semantic_available=failure != "disabled")
    if failure == "invalidated":
        harness.reader.invalidate()
    if failure == "timeout":
        harness.embedder.stall = True
    expected = "sha256:" + "b" * 64 if failure == "binding" else None
    exception = ValueError if failure == "binding" else OntologyRetrievalEvaluationAbortedError
    with pytest.raises(exception):
        await harness.run(expected, 0.01, _NOW)
    assert harness.embedder.calls == (1 if failure == "timeout" else 0)


async def test_current_graph_drift_aborts_instead_of_scoring_stored_facts() -> None:
    harness = await _harness()
    assert await harness.store.delete_object("incident-0")
    with pytest.raises(OntologyRetrievalEvaluationAbortedError) as failure:
        await harness.run(None, 1, _NOW)
    assert len(failure.value.completed) == 0
    assert harness.embedder.calls == 0


async def test_stale_cutoff_cannot_be_scored_as_current_evidence() -> None:
    harness = await _harness()
    with pytest.raises(OntologyRetrievalEvaluationAbortedError):
        await harness.run(None, 1, _NOW - timedelta(days=1))


async def test_parent_cancellation_propagates_without_another_model_call() -> None:
    harness = await _harness()
    harness.embedder.stall = True
    task = asyncio.create_task(harness.run(None, 1, _NOW))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert harness.embedder.calls == 1


async def test_each_query_rebinds_current_cutoff(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = await _harness()
    original = harness.embedder.embed

    async def advance(text: str) -> tuple[float, ...]:
        harness.clock.now += timedelta(seconds=1)
        return await original(text)

    monkeypatch.setattr(harness.embedder, "embed", advance)
    report = await harness.run(None, 1, None)
    assert report.passed
    assert harness.clock.now == _NOW + timedelta(seconds=20)
    assert report.source_validations[0].checked_at == _NOW
    assert report.source_validations[1].checked_at == harness.clock.now


async def test_runtime_ranking_policy_must_equal_frozen_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness()
    monkeypatch.setattr(harness.reader, "_policy", replace(_RANKING, minimum_score=0.6))
    with pytest.raises(OntologyRetrievalEvaluationAbortedError) as failure:
        await harness.run(None, 1, None)
    assert failure.value.completed == ()
    assert harness.embedder.calls == 0


async def test_final_empty_result_cannot_hide_source_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness(empty_last=True)
    original = harness.embedder.embed

    async def mutate_source(text: str) -> tuple[float, ...]:
        vector = await original(text)
        if harness.embedder.calls == 20:
            assert await harness.store.delete_object("incident-0")
        return vector

    monkeypatch.setattr(harness.embedder, "embed", mutate_source)
    with pytest.raises(OntologyRetrievalEvaluationAbortedError) as failure:
        await harness.run(None, 1, None)
    assert len(failure.value.completed) == 20
    assert harness.embedder.calls == 20
