"""Full and incremental ontology semantic generation tests."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.ontology_platform import QueryManifest, build_query_manifest
from fdai.delivery.catalog_search import (
    InMemoryCatalogSemanticIndex,
    SemanticGenerationBuild,
    bind_semantic_generation_validation,
    build_ontology_semantic_generation,
    publish_ontology_semantic_generation,
    validate_ontology_semantic_generation,
)
from fdai.delivery.catalog_search.ontology_snapshot_store import (
    OntologyGenerationSnapshotStore,
    OntologySnapshotCorruptionError,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    LinkCardinality,
    OntologyInterfaceType,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.compatibility import OntologyGenerationCompatibilityReceipt
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogGenerationRollbackReceipt,
    CatalogGenerationStaleError,
    CatalogGenerationValidationSnapshot,
    CatalogSearchDocument,
    build_document_digest_manifest,
    catalog_generation_digest,
    catalog_search_document_digest,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing.state_store import InMemoryStateStore

DIGEST = "sha256:" + ("a" * 64)
NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _manifest(*, scope_digest: str = DIGEST) -> QueryManifest:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    interface = OntologyInterfaceType(
        name="Identifiable",
        version="1.0.0",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    link = OntologyLinkType(
        schema_version="1.0.0",
        name="contains",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.ONE_TO_MANY,
    )
    release = build_ontology_release(
        object_types=(resource,),
        link_types=(link,),
        interface_types=(interface,),
    )
    return build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=scope_digest,
        object_types=(resource,),
        link_types=(link,),
        interfaces=(interface,),
    )


def _build(
    *,
    objects: tuple[OntologyObjectRecord, ...] = (),
    previous: tuple[CatalogSearchDocument, ...] = (),
) -> SemanticGenerationBuild:
    return build_ontology_semantic_generation(
        manifest=_manifest(),
        embedding_space_id="ontology-v1",
        embedding_model_version="lexical-only-v1",
        embedding_dimension=1,
        runtime_objects=objects,
        previous_documents=previous,
    )


def test_full_generation_covers_every_manifest_descriptor_and_runtime_object() -> None:
    record = OntologyObjectRecord(
        id="resource-a",
        object_type="Resource",
        properties={"id": "resource-a"},
    )

    build = _build(objects=(record,))

    assert len(build.documents) == 4
    assert {item.document_kind for item in build.documents} == {
        "ontology_declaration",
        "ontology_object",
    }
    assert build.metadata.ontology_release_digest == _manifest().release_digest
    assert build.metadata.validation_receipt_digest is None
    assert build.reused_document_count == 0


async def test_isolated_snapshot_survives_reader_restart_and_preserves_rule_state() -> None:
    state = InMemoryStateStore()
    await state.write_state("catalog-search:active", {"generation": "rule-generation"})
    store = OntologyGenerationSnapshotStore(state)
    build = _build()
    snapshot = await store.stage(build=build, manifest=_manifest(), source_generation="source-1")

    restored = await OntologyGenerationSnapshotStore(state).read(
        snapshot, manifest=_manifest(), source_generation="source-1"
    )

    assert restored == build
    assert snapshot == await store.stage(
        build=build, manifest=_manifest(), source_generation="source-1"
    )
    assert await state.read_state("catalog-search:active") == {"generation": "rule-generation"}
    assert snapshot != await store.stage(
        build=build, manifest=_manifest(), source_generation="source-2"
    )


@pytest.mark.parametrize("drift", ["principal", "source", "chunk", "header", "missing"])
async def test_snapshot_rejects_identity_drift_and_corruption(drift: str) -> None:
    state = InMemoryStateStore()
    store = OntologyGenerationSnapshotStore(state)
    snapshot = await store.stage(build=_build(), manifest=_manifest(), source_generation="source-1")
    manifest = _manifest()
    source = "source-1"
    prefix = f"ontology-semantic-snapshot:v1:{snapshot}"
    if drift == "principal":
        manifest = _manifest(scope_digest="sha256:" + "b" * 64)
    elif drift == "source":
        source = "source-2"
    elif drift == "header":
        await state.write_state(f"{prefix}:header", {"schema_version": "invalid"})
    elif drift == "chunk":
        await state.write_state(f"{prefix}:chunk:0", {"documents": []})
    else:
        state._state.pop(f"{prefix}:chunk:0")

    with pytest.raises(OntologySnapshotCorruptionError, match="validation"):
        await store.read(snapshot, manifest=manifest, source_generation=source)


async def test_interrupted_snapshot_is_invisible_and_resumes_idempotently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = InMemoryStateStore()
    store = OntologyGenerationSnapshotStore(state)
    write = state.write_state_if_absent

    async def interrupt_header(key: str, value: Mapping[str, Any]) -> bool:
        if key.endswith(":header"):
            raise RuntimeError("interrupted")
        return await write(key, value)

    monkeypatch.setattr(state, "write_state_if_absent", interrupt_header)
    with pytest.raises(RuntimeError, match="interrupted"):
        await store.stage(build=_build(), manifest=_manifest(), source_generation="source-1")
    assert not any(key.endswith(":header") for key in state._state)
    monkeypatch.setattr(state, "write_state_if_absent", write)
    snapshot = await store.stage(build=_build(), manifest=_manifest(), source_generation="source-1")
    restored = await store.read(snapshot, manifest=_manifest(), source_generation="source-1")
    assert restored == _build()


async def test_snapshot_chunks_large_generations_without_partial_visibility() -> None:
    state = InMemoryStateStore()
    store = OntologyGenerationSnapshotStore(state)
    records = tuple(
        OntologyObjectRecord(id=f"resource-{index}", object_type="Resource", properties={})
        for index in range(300)
    )
    build = _build(objects=records)
    snapshot = await store.stage(build=build, manifest=_manifest(), source_generation="source-1")
    assert len([key for key in state._state if ":chunk:" in key]) == 3
    assert await store.read(snapshot, manifest=_manifest(), source_generation="source-1") == build


async def test_snapshot_concurrent_writers_reuse_exact_chunks() -> None:
    state = InMemoryStateStore()
    store = OntologyGenerationSnapshotStore(state)
    snapshots = await asyncio.gather(
        *(
            store.stage(build=_build(), manifest=_manifest(), source_generation="source-1")
            for _ in range(8)
        )
    )
    assert len(set(snapshots)) == 1
    assert len(state._state) == 2
    await state.write_state(
        f"ontology-semantic-snapshot:v1:{snapshots[0]}:chunk:0", {"documents": []}
    )
    with pytest.raises(OntologySnapshotCorruptionError, match="immutable write conflict"):
        await store.stage(build=_build(), manifest=_manifest(), source_generation="source-1")


@pytest.mark.parametrize("source", ["", "x" * 257])
async def test_snapshot_invalid_source_does_not_write(source: str) -> None:
    state = InMemoryStateStore()
    with pytest.raises(ValueError):
        await OntologyGenerationSnapshotStore(state).stage(
            build=_build(), manifest=_manifest(), source_generation=source
        )
    assert state._state == {}


@pytest.mark.parametrize("digest", ["", "sha256:" + "g" * 64, "sha256:" + "a" * 63])
async def test_snapshot_invalid_key_is_rejected_before_io(digest: str) -> None:
    from unittest.mock import AsyncMock

    state = AsyncMock(spec=InMemoryStateStore)
    with pytest.raises(ValueError, match="sha256"):
        await OntologyGenerationSnapshotStore(state).read(
            digest, manifest=_manifest(), source_generation="source-1"
        )
    state.read_state.assert_not_awaited()


async def test_snapshot_absent_header_is_not_a_complete_generation() -> None:
    assert (
        await OntologyGenerationSnapshotStore(InMemoryStateStore()).read(
            DIGEST, manifest=_manifest(), source_generation="source-1"
        )
        is None
    )


@pytest.mark.parametrize("limit", ["_MAX_CHUNK_BYTES", "_MAX_SNAPSHOT_BYTES", "_MAX_DOCUMENTS"])
async def test_snapshot_capacity_failure_has_no_partial_writes(
    limit: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.delivery.catalog_search import ontology_snapshot_store

    monkeypatch.setattr(ontology_snapshot_store, limit, 1)
    state = InMemoryStateStore()
    with pytest.raises(ValueError):
        await OntologyGenerationSnapshotStore(state).stage(
            build=_build(), manifest=_manifest(), source_generation="source-1"
        )
    assert state._state == {}


async def test_snapshot_cannot_stage_an_already_active_generation() -> None:
    build = _build()
    build = replace(
        build,
        metadata=replace(
            build.metadata, state="active", activated_at=NOW, validation_receipt_digest=DIGEST
        ),
    )
    state = InMemoryStateStore()
    with pytest.raises(ValueError, match="inactive staged"):
        await OntologyGenerationSnapshotStore(state).stage(
            build=build, manifest=_manifest(), source_generation="source-1"
        )
    assert state._state == {}


@pytest.mark.integration
async def test_snapshot_postgres_reconnection_round_trip() -> None:
    import psycopg
    from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
    from psycopg.conninfo import conninfo_to_dict

    dsn = os.environ.get("FDAI_ONTOLOGY_SNAPSHOT_TEST_DSN")
    if not dsn:
        pytest.skip("FDAI_ONTOLOGY_SNAPSHOT_TEST_DSN is unset")
    connection_options = conninfo_to_dict(dsn)
    assert connection_options.get("host") in {"localhost", "127.0.0.1", "::1"}
    assert connection_options.get("hostaddr", connection_options["host"]) in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    owned_keys: list[str] = []

    class TrackedStore(PostgresStateStore):
        async def write_state_if_absent(self, key: str, value: Mapping[str, Any]) -> bool:
            owned_keys.append(key)
            return await super().write_state_if_absent(key, value)

    config = PostgresStateStoreConfig(dsn=dsn, connect_timeout_s=3, statement_timeout_ms=3000)
    writer = OntologyGenerationSnapshotStore(TrackedStore(config=config))
    source = f"snapshot-integration-{uuid.uuid4().hex}"
    build = _build(
        objects=(
            OntologyObjectRecord(
                id="resource-integration",
                object_type="Resource",
                properties={"id": "resource-integration"},
            ),
        )
    )
    try:
        snapshot = await writer.stage(build=build, manifest=_manifest(), source_generation=source)
        reader = OntologyGenerationSnapshotStore(PostgresStateStore(config=config))
        assert await reader.read(snapshot, manifest=_manifest(), source_generation=source) == build
        async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=3) as connection:
            await connection.execute(
                "UPDATE state_kv SET value=%s::jsonb WHERE key=%s",
                ('{"documents": []}', owned_keys[0]),
            )
        with pytest.raises(OntologySnapshotCorruptionError):
            await reader.read(snapshot, manifest=_manifest(), source_generation=source)
    finally:
        if owned_keys:
            async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=3) as connection:
                await connection.execute("DELETE FROM state_kv WHERE key=ANY(%s)", (owned_keys,))


def test_generation_validation_rejects_another_principal_manifest() -> None:
    with pytest.raises(ValueError, match="manifest"):
        validate_ontology_semantic_generation(
            build=_build(),
            manifest=_manifest(scope_digest="sha256:" + "b" * 64),
            validator_id="validator",
        )


def test_generation_validation_rejects_rehashed_document_tampering() -> None:
    build = _build()
    documents = (replace(build.documents[0], text="tampered"), *build.documents[1:])
    tampered = replace(
        build,
        documents=documents,
        document_digests=tuple(catalog_search_document_digest(item) for item in documents),
    )

    with pytest.raises(ValueError, match="manifest|declaration"):
        validate_ontology_semantic_generation(
            build=tampered,
            manifest=_manifest(),
            validator_id="validator",
        )


def test_incremental_generation_reuses_unchanged_document_objects() -> None:
    first = _build()

    second = _build(previous=first.documents)

    assert second.metadata.generation_digest == first.metadata.generation_digest
    assert second.document_digests == first.document_digests
    assert second.reused_document_count == len(first.documents)
    assert all(left is right for left, right in zip(first.documents, second.documents, strict=True))


async def test_generation_rebuild_does_not_relabel_unbound_previous_embeddings() -> None:
    previous = tuple(replace(item, embedding=(-1.0,)) for item in _build().documents)
    build = build_ontology_semantic_generation(
        manifest=_manifest(),
        embedding_space_id="new-space",
        embedding_model_version="new-model",
        embedding_dimension=1,
        previous_documents=previous,
    )

    assert all(not document.embedding for document in build.documents)
    assert build.reused_document_count == 0

    class CurrentEmbedder:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def embed(self, text: str) -> tuple[float, ...]:
            self.calls.append(text)
            return (1.0,)

    embedder = CurrentEmbedder()
    index = InMemoryCatalogSemanticIndex(embedder=embedder)
    await index.stage_generation(build.metadata, build.documents)
    assert len(embedder.calls) == len(build.documents)
    snapshot = await index.generation_validation_snapshot(build.metadata.generation_id)
    assert snapshot is not None
    assert all(document.embedding == (1.0,) for document in snapshot.documents)


def test_generation_identity_changes_with_principal_scope() -> None:
    first = _build()
    second = build_ontology_semantic_generation(
        manifest=_manifest(scope_digest="sha256:" + "b" * 64),
        embedding_space_id=first.metadata.embedding_space_id,
        embedding_model_version=first.metadata.embedding_model_version,
        embedding_dimension=first.metadata.embedding_dimension,
    )

    assert first.document_digests == second.document_digests
    assert first.metadata.generation_digest != second.metadata.generation_digest
    assert first.metadata.generation_id != second.metadata.generation_id


def test_validator_reconstructs_declarations_even_with_rehashed_generation() -> None:
    build = _build()
    documents = (replace(build.documents[0], text="tampered"), *build.documents[1:])
    digests = tuple(catalog_search_document_digest(item) for item in documents)
    manifest = build_document_digest_manifest(digests)
    metadata = replace(
        build.metadata,
        document_digest_manifest=manifest,
        generation_digest=catalog_generation_digest(
            corpus=build.metadata.corpus,
            catalog_digest=build.metadata.catalog_digest,
            semantic_schema_digest=build.metadata.semantic_schema_digest,
            ontology_release_digest=build.metadata.ontology_release_digest,
            embedding_space_id=build.metadata.embedding_space_id,
            embedding_model_version=build.metadata.embedding_model_version,
            embedding_dimension=build.metadata.embedding_dimension,
            document_digest_manifest=manifest,
        ),
    )

    with pytest.raises(ValueError, match="declaration content"):
        validate_ontology_semantic_generation(
            build=replace(build, documents=documents, document_digests=digests, metadata=metadata),
            manifest=_manifest(),
            validator_id="validator",
        )


def test_generation_metadata_rejects_noncanonical_generation_digest() -> None:
    build = _build()

    with pytest.raises(ValueError, match="generation digest mismatch"):
        replace(build.metadata, generation_digest="sha256:" + ("f" * 64))


def test_validation_snapshot_rejects_lifecycle_and_document_identity_drift() -> None:
    build = _build()
    documents = tuple(
        replace(document, generation_id=build.metadata.generation_id)
        for document in build.documents
    )

    with pytest.raises(ValueError, match="requires a staged"):
        CatalogGenerationValidationSnapshot(
            metadata=replace(
                build.metadata,
                state="active",
                validation_receipt_digest=DIGEST,
                activated_at=NOW,
            ),
            documents=documents,
        )
    with pytest.raises(ValueError, match="document identity mismatch"):
        CatalogGenerationValidationSnapshot(
            metadata=build.metadata,
            documents=(replace(documents[0], generation_id="other-generation"), *documents[1:]),
        )
    with pytest.raises(ValueError, match="manifest"):
        CatalogGenerationValidationSnapshot(
            metadata=build.metadata,
            documents=(replace(documents[0], text="tampered"), *documents[1:]),
        )


def test_full_generation_accepts_8500_incremental_projection_rows() -> None:
    records = tuple(
        OntologyObjectRecord(
            id=f"resource-{index:05d}",
            object_type="Resource",
            properties={"id": f"resource-{index:05d}"},
        )
        for index in range(8_500)
    )

    build = _build(objects=records)
    receipt = validate_ontology_semantic_generation(
        build=build,
        manifest=_manifest(),
        validator_id="ontology-generation-validator-v1",
    )

    assert len(build.documents) == 8_503
    assert receipt.document_count == 8_503


async def test_staging_is_invisible_until_atomic_activation_and_search_is_typed() -> None:
    build = _build()
    index = InMemoryCatalogSemanticIndex()

    with pytest.raises(ValueError, match="validation receipt"):
        await publish_ontology_semantic_generation(
            index=index,
            build=build,
            activated_at=NOW,
        )

    receipt = validate_ontology_semantic_generation(
        build=build,
        manifest=_manifest(),
        validator_id="ontology-generation-validator-v1",
    )
    build = bind_semantic_generation_validation(build, receipt)
    staged = await index.stage_generation(build.metadata, build.documents)
    assert staged == len(build.documents)
    assert await index.active_generation() is None
    snapshot = await index.generation_validation_snapshot(build.metadata.generation_id)
    assert snapshot is not None
    assert snapshot.metadata == build.metadata
    assert tuple(document.rule_id for document in snapshot.documents) == tuple(
        document.rule_id for document in build.documents
    )
    assert all(
        document.generation_id == build.metadata.generation_id for document in snapshot.documents
    )
    assert await index.generation_validation_snapshot("missing-generation") is None

    active = await publish_ontology_semantic_generation(
        index=index,
        build=build,
        activated_at=NOW,
    )
    results = await index.search(
        "Resource",
        expected_catalog_digest=active.catalog_digest,
    )

    assert active.state == "active"
    assert active.validation_receipt_digest == receipt.receipt_digest
    assert results
    assert all(item.document_kind == "ontology_declaration" for item in results)
    assert all(item.generation_digest == active.generation_digest for item in results)


async def test_delayed_publisher_cannot_replace_newer_active_generation() -> None:
    class DelayedStageIndex(InMemoryCatalogSemanticIndex):
        def __init__(self, delayed_generation_id: str) -> None:
            super().__init__()
            self.delayed_generation_id = delayed_generation_id
            self.stage_started = asyncio.Event()
            self.release_stage = asyncio.Event()

        async def stage_generation(
            self,
            metadata: CatalogGenerationMetadata,
            documents: tuple[CatalogSearchDocument, ...],
        ) -> int:
            if metadata.generation_id == self.delayed_generation_id:
                self.stage_started.set()
                await self.release_stage.wait()
            return await super().stage_generation(metadata, documents)

    def validated(build: SemanticGenerationBuild) -> SemanticGenerationBuild:
        receipt = validate_ontology_semantic_generation(
            build=build,
            manifest=_manifest(),
            validator_id="ontology-generation-validator-v1",
        )
        return bind_semantic_generation_validation(build, receipt)

    first = validated(_build())
    delayed = validated(
        _build(
            objects=(
                OntologyObjectRecord(
                    id="resource-delayed",
                    object_type="Resource",
                    properties={"id": "resource-delayed"},
                ),
            ),
        )
    )
    newer = validated(
        _build(
            objects=(
                OntologyObjectRecord(
                    id="resource-newer",
                    object_type="Resource",
                    properties={"id": "resource-newer"},
                ),
            ),
        )
    )
    index = DelayedStageIndex(delayed.metadata.generation_id)
    await publish_ontology_semantic_generation(index=index, build=first, activated_at=NOW)

    delayed_publish = asyncio.create_task(
        publish_ontology_semantic_generation(
            index=index,
            build=delayed,
            activated_at=datetime(2026, 8, 10, 2, tzinfo=UTC),
        )
    )
    await index.stage_started.wait()
    active = await publish_ontology_semantic_generation(
        index=index,
        build=newer,
        activated_at=datetime(2026, 8, 10, 1, tzinfo=UTC),
    )
    index.release_stage.set()

    with pytest.raises(CatalogGenerationStaleError, match="stale"):
        await delayed_publish
    assert await index.active_generation() == active


@pytest.mark.parametrize(
    ("expected_id", "expected_digest"),
    (("generation-a", None), (None, DIGEST)),
)
async def test_activation_rejects_partial_active_identity_before_lookup(
    expected_id: str | None,
    expected_digest: str | None,
) -> None:
    with pytest.raises(ValueError, match="supplied together"):
        await InMemoryCatalogSemanticIndex().activate_generation(
            "generation-b",
            expected_generation_digest=DIGEST,
            expected_active_generation_id=expected_id,
            expected_active_generation_digest=expected_digest,
            activated_at=NOW,
        )


async def test_activation_rejects_substituted_validation_receipt_without_pointer_change() -> None:
    build = _build()
    receipt = validate_ontology_semantic_generation(
        build=build,
        manifest=_manifest(),
        validator_id="ontology-generation-validator-v1",
    )
    validated = bind_semantic_generation_validation(build, receipt)
    index = InMemoryCatalogSemanticIndex()
    await index.stage_generation(validated.metadata, validated.documents)

    with pytest.raises(ValueError, match="validation receipt mismatch"):
        await index.activate_generation(
            validated.metadata.generation_id,
            expected_generation_digest=validated.metadata.generation_digest,
            expected_active_generation_id=None,
            expected_active_generation_digest=None,
            activated_at=NOW,
            expected_validation_receipt_digest="sha256:" + "f" * 64,
        )

    assert await index.active_generation() is None


async def test_activation_cas_preserves_pointer_after_rejected_transitions() -> None:
    def validated(build: SemanticGenerationBuild) -> SemanticGenerationBuild:
        receipt = validate_ontology_semantic_generation(
            build=build,
            manifest=_manifest(),
            validator_id="ontology-generation-validator-v1",
        )
        return bind_semantic_generation_validation(build, receipt)

    def with_object(identifier: str) -> SemanticGenerationBuild:
        return validated(
            _build(
                objects=(
                    OntologyObjectRecord(
                        id=identifier,
                        object_type="Resource",
                        properties={"id": identifier},
                    ),
                ),
            )
        )

    first_build = validated(_build())
    second_build = with_object("resource-second")
    stale_build = with_object("resource-stale")
    index = InMemoryCatalogSemanticIndex()
    await index.stage_generation(first_build.metadata, first_build.documents)
    first = await index.activate_generation(
        first_build.metadata.generation_id,
        expected_generation_digest=first_build.metadata.generation_digest,
        expected_active_generation_id=None,
        expected_active_generation_digest=None,
        activated_at=NOW,
    )
    replay = await index.activate_generation(
        first_build.metadata.generation_id,
        expected_generation_digest=first_build.metadata.generation_digest,
        expected_active_generation_id=None,
        expected_active_generation_digest=None,
        activated_at=NOW,
    )
    assert replay == first

    await index.stage_generation(second_build.metadata, second_build.documents)
    await index.stage_generation(stale_build.metadata, stale_build.documents)
    with pytest.raises(ValueError, match="precedes active generation"):
        await index.activate_generation(
            second_build.metadata.generation_id,
            expected_generation_digest=second_build.metadata.generation_digest,
            expected_active_generation_id=first.generation_id,
            expected_active_generation_digest=first.generation_digest,
            activated_at=datetime(2026, 8, 9, 23, tzinfo=UTC),
        )
    assert await index.active_generation() == first

    second = await index.activate_generation(
        second_build.metadata.generation_id,
        expected_generation_digest=second_build.metadata.generation_digest,
        expected_active_generation_id=first.generation_id,
        expected_active_generation_digest=first.generation_digest,
        activated_at=datetime(2026, 8, 10, 1, tzinfo=UTC),
    )
    with pytest.raises(CatalogGenerationStaleError, match="stale"):
        await index.activate_generation(
            stale_build.metadata.generation_id,
            expected_generation_digest=stale_build.metadata.generation_digest,
            expected_active_generation_id=first.generation_id,
            expected_active_generation_digest=first.generation_digest,
            activated_at=datetime(2026, 8, 10, 2, tzinfo=UTC),
        )
    assert await index.active_generation() == second

    with pytest.raises(CatalogGenerationStaleError, match="stale"):
        await index.activate_generation(
            first_build.metadata.generation_id,
            expected_generation_digest=first_build.metadata.generation_digest,
            expected_active_generation_id=None,
            expected_active_generation_digest=None,
            activated_at=NOW,
        )
    assert await index.active_generation() == second


async def test_generation_rejects_wrong_embedding_dimension() -> None:
    build = _build()
    invalid = build.documents[0]
    documents = (
        replace(invalid, embedding=(0.1, 0.2)),
        *build.documents[1:],
    )

    with pytest.raises(ValueError, match="embedding dimension"):
        await InMemoryCatalogSemanticIndex().stage_generation(build.metadata, documents)


async def test_generation_rejects_ordered_document_identity_drift() -> None:
    build = _build()

    with pytest.raises(ValueError, match="document digest manifest"):
        await InMemoryCatalogSemanticIndex().stage_generation(
            build.metadata,
            tuple(reversed(build.documents)),
        )


async def test_retained_generation_rolls_back_atomically() -> None:
    manifest = _manifest()
    index = InMemoryCatalogSemanticIndex()

    async def activate(
        build: SemanticGenerationBuild,
        at: datetime,
    ) -> tuple[SemanticGenerationBuild, CatalogGenerationMetadata]:
        receipt = validate_ontology_semantic_generation(
            build=build,
            manifest=manifest,
            validator_id="ontology-generation-validator-v1",
        )
        validated = bind_semantic_generation_validation(build, receipt)
        metadata = await publish_ontology_semantic_generation(
            index=index,
            build=validated,
            activated_at=at,
        )
        return validated, metadata

    first_build, first = await activate(_build(), NOW)
    changed_record = OntologyObjectRecord(
        id="resource-new",
        object_type="Resource",
        properties={"id": "resource-new"},
    )
    second_build, second = await activate(
        _build(objects=(changed_record,), previous=first_build.documents),
        datetime(2026, 8, 10, 1, tzinfo=UTC),
    )
    compatibility = OntologyGenerationCompatibilityReceipt(
        previous_release_digest=first.ontology_release_digest,
        candidate_release_digest=second.ontology_release_digest,
        checked_declarations=(),
        added_declarations=(),
    )

    rollback = await index.rollback_generation(
        first.generation_id,
        expected_active_generation_id=second.generation_id,
        expected_active_generation_digest=second.generation_digest,
        expected_target_generation_digest=first.generation_digest,
        expected_validation_receipt_digest=first.validation_receipt_digest or "",
        ontology_compatibility_receipt=compatibility,
        rolled_back_at=datetime(2026, 8, 10, 2, tzinfo=UTC),
    )

    assert rollback.reactivated_generation_id == first.generation_id
    active = await index.active_generation()
    assert active is not None
    assert active.generation_id == first.generation_id
    assert second_build.metadata.generation_id == second.generation_id

    altered_manifest = build_document_digest_manifest(
        tuple(f"sha256:{value * 64}" for value in ("b", "c", "d"))
    )
    corrupted_retired = replace(rollback.retired_generation)
    object.__setattr__(corrupted_retired, "document_digest_manifest", altered_manifest)
    altered_receipt = CatalogGenerationRollbackReceipt(
        retired_generation=corrupted_retired,
        reactivated_generation=rollback.reactivated_generation,
        validation_receipt_digest=rollback.validation_receipt_digest,
        ontology_compatibility_receipt=rollback.ontology_compatibility_receipt,
        rolled_back_at=rollback.rolled_back_at,
    )
    assert altered_receipt.receipt_digest != rollback.receipt_digest


async def test_active_and_discovery_generation_pointers_are_independent() -> None:
    manifest = _manifest()
    index = InMemoryCatalogSemanticIndex()
    build = _build()
    receipt = validate_ontology_semantic_generation(
        build=build,
        manifest=manifest,
        validator_id="ontology-generation-validator-v1",
    )
    validated = bind_semantic_generation_validation(build, receipt)
    active = await publish_ontology_semantic_generation(
        index=index,
        build=validated,
        activated_at=NOW,
    )
    discovery_documents = tuple(
        replace(document, corpus="discovery") for document in validated.documents
    )
    discovery_manifest = build_document_digest_manifest(
        tuple(catalog_search_document_digest(item) for item in discovery_documents)
    )
    discovery_generation_digest = catalog_generation_digest(
        corpus="discovery",
        catalog_digest=validated.metadata.catalog_digest,
        semantic_schema_digest=validated.metadata.semantic_schema_digest,
        ontology_release_digest=validated.metadata.ontology_release_digest,
        embedding_space_id=validated.metadata.embedding_space_id,
        embedding_model_version=validated.metadata.embedding_model_version,
        embedding_dimension=validated.metadata.embedding_dimension,
        document_digest_manifest=discovery_manifest,
    )
    discovery_first = replace(
        validated.metadata,
        generation_id="ontology-search:discovery:first",
        generation_digest=discovery_generation_digest,
        corpus="discovery",
        document_digest_manifest=discovery_manifest,
    )
    discovery_second = replace(
        discovery_first,
        generation_id="ontology-search:discovery:second",
    )

    await index.stage_generation(discovery_first, discovery_documents)
    assert await index.active_generation("discovery") is None
    with pytest.raises(CatalogGenerationStaleError, match="unavailable"):
        await index.search(
            "Resource",
            corpus="discovery",
            expected_catalog_digest=discovery_first.catalog_digest,
        )

    first = await index.activate_generation(
        discovery_first.generation_id,
        expected_generation_digest=discovery_first.generation_digest,
        expected_active_generation_id=None,
        expected_active_generation_digest=None,
        activated_at=datetime(2026, 8, 10, 1, tzinfo=UTC),
    )
    await index.stage_generation(discovery_second, discovery_documents)
    second = await index.activate_generation(
        discovery_second.generation_id,
        expected_generation_digest=discovery_second.generation_digest,
        expected_active_generation_id=first.generation_id,
        expected_active_generation_digest=first.generation_digest,
        activated_at=datetime(2026, 8, 10, 2, tzinfo=UTC),
    )
    compatibility = OntologyGenerationCompatibilityReceipt(
        previous_release_digest=first.ontology_release_digest,
        candidate_release_digest=second.ontology_release_digest,
        checked_declarations=(),
        added_declarations=(),
    )

    await index.rollback_generation(
        first.generation_id,
        expected_active_generation_id=second.generation_id,
        expected_active_generation_digest=second.generation_digest,
        expected_target_generation_digest=first.generation_digest,
        expected_validation_receipt_digest=first.validation_receipt_digest or "",
        ontology_compatibility_receipt=compatibility,
        rolled_back_at=datetime(2026, 8, 10, 3, tzinfo=UTC),
    )

    active_after = await index.active_generation("active")
    discovery_after = await index.active_generation("discovery")
    active_results = await index.search("Resource", corpus="active")
    discovery_results = await index.search("Resource", corpus="discovery")
    assert active_after is not None
    assert active_after.generation_id == active.generation_id
    assert discovery_after is not None
    assert discovery_after.generation_id == first.generation_id
    assert {result.generation_id for result in active_results} == {active.generation_id}
    assert {result.generation_id for result in discovery_results} == {first.generation_id}
