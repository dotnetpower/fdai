"""Source-bound vector persistence, independent of Rule activation or live quality."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Mapping
from typing import Any

import pytest
from fdai.core.ontology_platform import QueryManifest, build_query_manifest
from fdai.delivery.catalog_search.generation import (
    SemanticGenerationBuild,
    build_ontology_semantic_generation,
)
from fdai.delivery.catalog_search.ontology_snapshot_store import OntologyGenerationSnapshotStore
from fdai.delivery.catalog_search.ontology_vector_store import OntologyVectorSnapshotStore
from fdai.shared.contracts.models import CeilingRole, OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

DIGEST = "sha256:" + "a" * 64


def _manifest() -> QueryManifest:
    objects = tuple(
        OntologyObjectType(
            schema_version="1.0.0",
            name=name,
            version="1.0.0",
            key="id",
            properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
        )
        for name in ("Resource", "Incident")
    )
    return build_query_manifest(
        release=build_ontology_release(object_types=objects),
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=objects,
    )


def _build() -> SemanticGenerationBuild:
    return build_ontology_semantic_generation(
        manifest=_manifest(),
        embedding_space_id="ontology-v1",
        embedding_model_version="lexical-only-v1",
        embedding_dimension=1,
    )


class _Embedder:
    def __init__(self, failure: str = "") -> None:
        self.calls = 0
        self.failure = failure

    async def embed(self, text: str) -> tuple[float, ...]:
        self.calls += 1
        if self.failure == "provider" or (self.failure == "interrupt" and self.calls == 2):
            raise RuntimeError("private provider message")
        return {
            "zero": (0.0,),
            "nan": (float("nan"),),
            "dimension": (1.0, 2.0),
        }.get(self.failure, (1.0,))


def _vectors(store: StateStore, embedder: _Embedder) -> OntologyVectorSnapshotStore:
    return OntologyVectorSnapshotStore(
        store,
        embedder=embedder,
        embedding_space_id="other-space" if embedder.failure == "identity" else "ontology-v1",
        embedding_model_version="lexical-only-v1",
        embedding_dimension=1,
    )


async def test_vector_snapshot_is_bound_to_exact_source_and_configured_embedder() -> None:
    state = InMemoryStateStore()
    snapshots = OntologyGenerationSnapshotStore(state)
    source = await snapshots.stage(
        build=_build(), manifest=_manifest(), source_generation="source-1"
    )
    vectors = _vectors(state, _Embedder())
    vector_digest = await vectors.stage(
        snapshots=snapshots,
        snapshot_digest=source,
        manifest=_manifest(),
        source_generation="source-1",
    )
    loaded = await vectors.read(
        vector_digest,
        snapshot_digest=source,
        generation=_build().metadata,
        document_ids=tuple(document.rule_id for document in _build().documents),
    )
    assert loaded == {document.rule_id: (1.0,) for document in _build().documents}
    with pytest.raises(ValueError, match="identity"):
        await vectors.read(
            vector_digest,
            snapshot_digest=DIGEST,
            generation=_build().metadata,
            document_ids=tuple(loaded),
        )
    assert not any(key.startswith("catalog-search:") for key in state._state)


@pytest.mark.parametrize("failure", ["tamper", "identity", "zero", "nan", "dimension", "provider"])
async def test_vector_snapshot_rejects_invalid_vectors_and_reblessing(failure: str) -> None:
    state = InMemoryStateStore()
    snapshots = OntologyGenerationSnapshotStore(state)
    source = await snapshots.stage(
        build=_build(), manifest=_manifest(), source_generation="source-1"
    )
    embedder = _Embedder(failure)
    vectors = _vectors(state, embedder)

    async def stage() -> str:
        return await vectors.stage(
            snapshots=snapshots,
            snapshot_digest=source,
            manifest=_manifest(),
            source_generation="source-1",
        )

    if failure == "tamper":
        await stage()
        key = next(key for key in state._state if ":row:" in key)
        row = dict(state._state[key])
        row["vector"] = [-1.0]
        await state.write_state(key, row)
    with pytest.raises(ValueError) as error:
        await stage()
    assert "private provider message" not in str(error.value)
    if failure == "identity":
        assert embedder.calls == 0
    if failure != "tamper":
        assert not any(
            key.startswith("ontology-semantic-vectors:") and key.endswith(":header")
            for key in state._state
        )


@pytest.mark.parametrize(
    "damage", ["row_value", "row_missing", "header_missing", "header_identity"]
)
async def test_completed_vector_point_read_rejects_durable_damage(damage: str) -> None:
    state = InMemoryStateStore()
    snapshots = OntologyGenerationSnapshotStore(state)
    build, manifest = _build(), _manifest()
    source = await snapshots.stage(build=build, manifest=manifest, source_generation="source-1")
    vectors = _vectors(state, _Embedder())
    digest = await vectors.stage(
        snapshots=snapshots, snapshot_digest=source, manifest=manifest, source_generation="source-1"
    )
    document = build.documents[0]
    row_key = next(
        key for key, value in state._state.items() if value.get("document_id") == document.rule_id
    )
    header_key = f"ontology-semantic-vectors:v1:{digest}:header"
    if damage == "row_value":
        await state.write_state(row_key, {**state._state[row_key], "vector": [-1.0]})
    elif damage == "row_missing":
        state._state.pop(row_key)
    elif damage == "header_missing":
        state._state.pop(header_key)
    else:
        await state.write_state(header_key, {**state._state[header_key], "snapshot_digest": DIGEST})
    with pytest.raises(ValueError, match="snapshot content or identity mismatch"):
        await vectors.read(
            digest,
            snapshot_digest=source,
            generation=build.metadata,
            document_ids=(document.rule_id,),
        )


async def test_vector_snapshot_resumes_and_point_reads_do_not_reload_other_rows() -> None:
    class CountingStore(InMemoryStateStore):
        reads: list[str]

        async def read_state(self, key: str) -> Mapping[str, Any] | None:
            self.reads.append(key)
            return await super().read_state(key)

    state = CountingStore()
    state.reads = []
    snapshots = OntologyGenerationSnapshotStore(state)
    source = await snapshots.stage(
        build=_build(), manifest=_manifest(), source_generation="source-1"
    )
    embedder = _Embedder("interrupt")

    async def stage() -> str:
        return await _vectors(state, embedder).stage(
            snapshots=snapshots,
            snapshot_digest=source,
            manifest=_manifest(),
            source_generation="source-1",
        )

    with pytest.raises(ValueError, match="provider unavailable"):
        await stage()
    assert not any(
        key.startswith("ontology-semantic-vectors:") and key.endswith(":header")
        for key in state._state
    )
    embedder.failure = ""
    digest = await stage()
    assert embedder.calls == len(_build().documents) + 1
    assert await stage() == digest
    assert embedder.calls == len(_build().documents) + 1
    state.reads.clear()
    identifier = _build().documents[0].rule_id
    assert await _vectors(state, embedder).read(
        digest,
        snapshot_digest=source,
        generation=_build().metadata,
        document_ids=(identifier,),
    ) == {identifier: (1.0,)}
    assert len(state.reads) == 2


async def test_cancelled_vector_build_cancels_provider_and_leaves_no_completion() -> None:
    started = asyncio.Event()
    finished = asyncio.Event()

    class WaitingEmbedder(_Embedder):
        async def embed(self, text: str) -> tuple[float, ...]:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
            return (1.0,)

    state = InMemoryStateStore()
    snapshots = OntologyGenerationSnapshotStore(state)
    source = await snapshots.stage(
        build=_build(), manifest=_manifest(), source_generation="source-1"
    )
    task = asyncio.create_task(
        _vectors(state, WaitingEmbedder()).stage(
            snapshots=snapshots,
            snapshot_digest=source,
            manifest=_manifest(),
            source_generation="source-1",
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
    assert not any(key.startswith("ontology-semantic-vectors:") for key in state._state)


@pytest.mark.integration
async def test_vector_snapshot_postgres_reconnection_and_tamper_rejection() -> None:
    import psycopg
    from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
    from psycopg.conninfo import conninfo_to_dict

    dsn = os.environ.get("FDAI_ONTOLOGY_SNAPSHOT_TEST_DSN")
    if not dsn:
        pytest.skip("FDAI_ONTOLOGY_SNAPSHOT_TEST_DSN is unset")
    options = conninfo_to_dict(dsn)
    assert options.get("host") in {"localhost", "127.0.0.1", "::1"}
    assert options.get("hostaddr", options["host"]) in {"localhost", "127.0.0.1", "::1"}
    owned_keys: list[str] = []

    class TrackedStore(PostgresStateStore):
        async def write_state_if_absent(self, key: str, value: Mapping[str, Any]) -> bool:
            owned_keys.append(key)
            return await super().write_state_if_absent(key, value)

    config = PostgresStateStoreConfig(dsn=dsn, connect_timeout_s=3, statement_timeout_ms=3000)
    store = TrackedStore(config=config)
    snapshots = OntologyGenerationSnapshotStore(store)
    source_generation = f"vector-integration-{uuid.uuid4().hex}"
    try:
        source = await snapshots.stage(
            build=_build(), manifest=_manifest(), source_generation=source_generation
        )
        vector_digest = await _vectors(store, _Embedder()).stage(
            snapshots=snapshots,
            snapshot_digest=source,
            manifest=_manifest(),
            source_generation=source_generation,
        )
        reader = _vectors(PostgresStateStore(config=config), _Embedder())
        identifiers = tuple(item.rule_id for item in _build().documents)
        assert await reader.read(
            vector_digest,
            snapshot_digest=source,
            generation=_build().metadata,
            document_ids=identifiers,
        ) == dict.fromkeys(identifiers, (1.0,))
        async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=3) as connection:
            await connection.execute(
                "UPDATE state_kv SET value=jsonb_set(value, '{vector}', '[-1.0]'::jsonb) "
                "WHERE key=%s",
                (next(key for key in owned_keys if ":row:" in key),),
            )
        with pytest.raises(ValueError, match="identity mismatch"):
            await reader.read(
                vector_digest,
                snapshot_digest=source,
                generation=_build().metadata,
                document_ids=identifiers,
            )
    finally:
        if owned_keys:
            async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=3) as connection:
                await connection.execute("DELETE FROM state_kv WHERE key=ANY(%s)", (owned_keys,))
