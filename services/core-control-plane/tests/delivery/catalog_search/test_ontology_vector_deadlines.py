"""Non-yielding collaborators cannot turn an expired vector attempt into success."""

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest
from fdai.delivery.catalog_search import ontology_candidate_reader as candidate_module
from fdai.delivery.catalog_search.ontology_snapshot_store import OntologyGenerationSnapshotStore
from fdai.delivery.catalog_search.ontology_vector_store import OntologyVectorSnapshotStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.delivery.catalog_search.test_ontology_evaluation import _cases
from tests.delivery.catalog_search.test_ontology_evaluation_runner import _harness
from tests.delivery.catalog_search.test_ontology_vectors import (
    _build,
    _Embedder,
    _manifest,
    _vectors,
)


@pytest.mark.parametrize("elapsed", [10.0, 121.0])
async def test_late_document_embedding_stops_before_writing_or_next_call(
    monkeypatch: pytest.MonkeyPatch, elapsed: float
) -> None:
    state = InMemoryStateStore()
    snapshots = OntologyGenerationSnapshotStore(state)
    source = await snapshots.stage(
        build=_build(), manifest=_manifest(), source_generation="source-1"
    )
    embedder = _Embedder()
    vectors = _vectors(state, embedder)
    loop, offset = asyncio.get_running_loop(), 0.0
    original_time, original_embed = loop.time, embedder.embed

    async def late(text: str) -> tuple[float, ...]:
        nonlocal offset
        vector = await original_embed(text)
        offset = elapsed
        return vector

    monkeypatch.setattr(loop, "time", lambda: original_time() + offset)
    monkeypatch.setattr(embedder, "embed", late)
    with pytest.raises(ValueError, match="provider unavailable"):
        await vectors.stage(
            snapshots=snapshots,
            snapshot_digest=source,
            manifest=_manifest(),
            source_generation="source-1",
        )
    assert embedder.calls == 1
    assert not any(key.startswith("ontology-semantic-vectors:") for key in state._state)


async def test_late_query_embedding_is_not_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    embedder = _Embedder()
    vectors = _vectors(InMemoryStateStore(), embedder)
    loop, offset = asyncio.get_running_loop(), 0.0
    original_time, original_embed = loop.time, embedder.embed

    async def late(text: str) -> tuple[float, ...]:
        nonlocal offset
        vector = await original_embed(text)
        offset = 10.0
        return vector

    monkeypatch.setattr(loop, "time", lambda: original_time() + offset)
    monkeypatch.setattr(embedder, "embed", late)
    with pytest.raises(ValueError, match="provider unavailable"):
        await vectors.embed_query("example query", generation=_build().metadata)
    assert embedder.calls == 1


async def test_document_calls_share_the_remaining_build_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = InMemoryStateStore()
    snapshots = OntologyGenerationSnapshotStore(state)
    source = await snapshots.stage(
        build=_build(), manifest=_manifest(), source_generation="source-1"
    )
    embedder = _Embedder()
    vectors = OntologyVectorSnapshotStore(
        state,
        embedder=embedder,
        embedding_space_id="ontology-v1",
        embedding_model_version="lexical-only-v1",
        embedding_dimension=1,
        call_timeout_seconds=10,
        build_timeout_seconds=15,
    )
    loop, offset = asyncio.get_running_loop(), 0.0
    original_time, original_embed = loop.time, embedder.embed

    async def slow(text: str) -> tuple[float, ...]:
        nonlocal offset
        result = await original_embed(text)
        offset += 9.0
        return result

    monkeypatch.setattr(loop, "time", lambda: original_time() + offset)
    monkeypatch.setattr(embedder, "embed", slow)
    with pytest.raises(ValueError, match="provider unavailable"):
        await vectors.stage(
            snapshots=snapshots,
            snapshot_digest=source,
            manifest=_manifest(),
            source_generation="source-1",
        )
    assert embedder.calls == 2
    assert len([key for key in state._state if ":row:" in key]) == 1
    assert not any(
        key.startswith("ontology-semantic-vectors:") and key.endswith(":complete")
        for key in state._state
    )


@pytest.mark.parametrize("phase", ["source-read", "row-write", "header-write", "completion-write"])
async def test_late_storage_stops_build_without_further_embedding(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    state = InMemoryStateStore()
    snapshots = OntologyGenerationSnapshotStore(state)
    source = await snapshots.stage(
        build=_build(), manifest=_manifest(), source_generation="source-1"
    )
    embedder = _Embedder()
    vectors = _vectors(state, embedder)
    loop, offset = asyncio.get_running_loop(), 0.0
    original_time = loop.time
    original_read, original_write = state.read_state, state.write_state_if_absent

    async def slow_read(key: str) -> Mapping[str, Any] | None:
        nonlocal offset
        value = await original_read(key)
        if phase == "source-read":
            offset = 121.0
        return value

    async def slow_write(key: str, value: Mapping[str, Any]) -> bool:
        nonlocal offset
        inserted = await original_write(key, value)
        if key.startswith("ontology-semantic-vectors:") and (
            (phase == "row-write" and ":row:" in key)
            or (phase == "header-write" and key.endswith(":header"))
            or (phase == "completion-write" and key.endswith(":complete"))
        ):
            offset = 121.0
        return inserted

    monkeypatch.setattr(loop, "time", lambda: original_time() + offset)
    monkeypatch.setattr(state, "read_state", slow_read)
    monkeypatch.setattr(state, "write_state_if_absent", slow_write)
    with pytest.raises(TimeoutError, match="deadline"):
        await vectors.stage(
            snapshots=snapshots,
            snapshot_digest=source,
            manifest=_manifest(),
            source_generation="source-1",
        )
    expected = {"source-read": 0, "row-write": 1}.get(phase, len(_build().documents))
    assert embedder.calls == expected
    if phase != "completion-write":
        assert not any(
            key.startswith("ontology-semantic-vectors:") and key.endswith(":complete")
            for key in state._state
        )


@pytest.mark.parametrize("operation", ["read", "reuse"])
async def test_late_cached_read_is_not_accepted(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    state = InMemoryStateStore()
    snapshots = OntologyGenerationSnapshotStore(state)
    source = await snapshots.stage(
        build=_build(), manifest=_manifest(), source_generation="source-1"
    )
    embedder = _Embedder()
    vectors = _vectors(state, embedder)
    digest = await vectors.stage(
        snapshots=snapshots,
        snapshot_digest=source,
        manifest=_manifest(),
        source_generation="source-1",
    )
    calls = embedder.calls
    loop, offset = asyncio.get_running_loop(), 0.0
    original_time, original_read = loop.time, state.read_state

    async def late(key: str) -> Mapping[str, Any] | None:
        nonlocal offset
        result = await original_read(key)
        if key.startswith("ontology-semantic-vectors:") and key.endswith(":header"):
            offset = 121.0 if operation == "reuse" else 10.0
        return result

    monkeypatch.setattr(loop, "time", lambda: original_time() + offset)
    monkeypatch.setattr(state, "read_state", late)
    with pytest.raises(TimeoutError, match="deadline"):
        if operation == "read":
            await vectors.read(
                digest,
                snapshot_digest=source,
                generation=_build().metadata,
                document_ids=(_build().documents[0].rule_id,),
            )
        else:
            await vectors.stage(
                snapshots=snapshots,
                snapshot_digest=source,
                manifest=_manifest(),
                source_generation="source-1",
            )
    assert embedder.calls == calls


@pytest.mark.parametrize("phase", ["embedding", "ranking", "authorization"])
async def test_candidate_query_enforces_its_shorter_deadline(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    harness = await _harness()
    loop, offset = asyncio.get_running_loop(), 0.0
    original_time = loop.time
    original_embed = harness.embedder.embed
    original_rank = candidate_module.rank_documents
    original_authorize = candidate_module.reauthorize_ontology_candidates
    authorization_calls = 0

    async def late_embed(text: str) -> tuple[float, ...]:
        nonlocal offset
        result = await original_embed(text)
        if phase == "embedding":
            offset = 6.0
        return result

    def late_rank(*args: Any, **kwargs: Any) -> Any:
        nonlocal offset
        result = original_rank(*args, **kwargs)
        if phase == "ranking":
            offset = 6.0
        return result

    async def late_authorize(**kwargs: Any) -> Any:
        nonlocal offset, authorization_calls
        authorization_calls += 1
        result = await original_authorize(**kwargs)
        if phase == "authorization":
            offset = 6.0
        return result

    monkeypatch.setattr(loop, "time", lambda: original_time() + offset)
    monkeypatch.setattr(harness.embedder, "embed", late_embed)
    monkeypatch.setattr(candidate_module, "rank_documents", late_rank)
    monkeypatch.setattr(candidate_module, "reauthorize_ontology_candidates", late_authorize)
    with pytest.raises(TimeoutError, match="deadline"):
        await harness.reader.search(
            next(case.query for case in _cases() if case.cohort.endswith("-positive")),
            staged=harness.staged,
            manifest=harness.manifest,
            gateway=harness.gateway,
            as_of=harness.clock.now,
        )
    assert harness.embedder.calls == 1
    assert authorization_calls == (1 if phase == "authorization" else 0)
