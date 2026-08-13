"""Full and incremental ontology semantic generation tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

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
    CatalogSearchDocument,
    build_document_digest_manifest,
    catalog_generation_digest,
    catalog_search_document_digest,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

DIGEST = "sha256:" + ("a" * 64)
NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _manifest() -> QueryManifest:
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
        principal_scope_digest=DIGEST,
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


def test_incremental_generation_reuses_unchanged_document_objects() -> None:
    first = _build()

    second = _build(previous=first.documents)

    assert second.metadata.generation_digest == first.metadata.generation_digest
    assert second.document_digests == first.document_digests
    assert second.reused_document_count == len(first.documents)
    assert all(left is right for left, right in zip(first.documents, second.documents, strict=True))


def test_generation_metadata_rejects_noncanonical_generation_digest() -> None:
    build = _build()

    with pytest.raises(ValueError, match="generation digest mismatch"):
        replace(build.metadata, generation_digest="sha256:" + ("f" * 64))


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
