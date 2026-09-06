"""Single-writer ownership for the provider-observed resource subgraph."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.runtime.inventory_ontology import (
    INVENTORY_ONTOLOGY_MANIFEST_KEY,
    INVENTORY_ONTOLOGY_STATUS_KEY,
    InventoryOntologyProjector,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.inventory import (
    LinkRecord,
    RelationshipDrop,
    RelationshipDropReason,
    RelationshipUnavailableReason,
    ResourceRecord,
)
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceValidationError,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore, InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[4]
ONTOLOGY_RELEASE_DIGEST = "sha256:" + "a" * 64


class _RecordingProjectionLock:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.entries = 0

    @asynccontextmanager
    async def acquire(self, resource_id: str) -> AsyncIterator[None]:
        assert resource_id == "inventory-ontology-projection"
        self.entries += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0)
            yield
        finally:
            self.active -= 1


class _RecordingObservationJournal:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def mark_ontology_projected(self, *, generation: str, watermark: int) -> None:
        self.calls.append((generation, watermark))


class _FailStatusOnceStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_status_once = True

    async def write_state(self, key: str, value: dict[str, object]) -> None:
        if key == INVENTORY_ONTOLOGY_STATUS_KEY and self.fail_status_once:
            self.fail_status_once = False
            raise RuntimeError("injected status commit failure")
        await super().write_state(key, value)


class _FailManifestOnceStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_manifest_once = True

    async def write_state(self, key: str, value: dict[str, object]) -> None:
        if key == INVENTORY_ONTOLOGY_MANIFEST_KEY and self.fail_manifest_once:
            self.fail_manifest_once = False
            raise RuntimeError("injected manifest commit failure")
        await super().write_state(key, value)


class _CountingOntologyStore(InMemoryOntologyInstanceStore):
    def __init__(self) -> None:
        catalog = load_ontology_catalog(
            REPO_ROOT / "rule-catalog",
            schema_registry=PackageResourceSchemaRegistry(),
            probes_root=REPO_ROOT / "rule-catalog" / "probes",
        )
        super().__init__(object_types=catalog.object_types, link_types=catalog.link_types)
        self.query_calls = 0

    async def query_objects(self, **kwargs: object):  # type: ignore[no-untyped-def]
        self.query_calls += 1
        return await super().query_objects(**kwargs)


class _AtomicOntologyStore(InMemoryOntologyInstanceStore):
    def __init__(self, status: InMemoryStateStore) -> None:
        catalog = load_ontology_catalog(
            REPO_ROOT / "rule-catalog",
            schema_registry=PackageResourceSchemaRegistry(),
            probes_root=REPO_ROOT / "rule-catalog" / "probes",
        )
        super().__init__(object_types=catalog.object_types, link_types=catalog.link_types)
        self._status = status

    async def replace_subgraph_with_state(
        self,
        *,
        objects: tuple[OntologyObjectRecord, ...],
        links: tuple[object, ...],
        previous_object_ids: tuple[str, ...],
        previous_link_keys: tuple[tuple[str, str, str], ...],
        state_updates: dict[str, dict[str, object]],
        expected_active_generation: str,
    ) -> None:
        assert expected_active_generation
        prior_objects = deepcopy(self._objects)
        prior_links = deepcopy(self._links)
        prior_state = deepcopy(self._status._state)  # noqa: SLF001 - transactional test double
        try:
            await super().replace_subgraph(
                objects=objects,
                links=links,  # type: ignore[arg-type]
                previous_object_ids=previous_object_ids,
                previous_link_keys=previous_link_keys,
            )
            for key, value in state_updates.items():
                await self._status.write_state(key, value)
        except Exception:
            self._objects = prior_objects
            self._links = prior_links
            self._status._state = prior_state  # noqa: SLF001 - transactional test double
            raise

    async def write_state_if_active_generation(
        self,
        *,
        expected_active_generation: str,
        state_updates: dict[str, dict[str, object]],
    ) -> None:
        assert expected_active_generation
        for key, value in state_updates.items():
            await self._status.write_state(key, value)


def _store() -> InMemoryOntologyInstanceStore:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    return InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )


def _projector(
    store: InMemoryOntologyInstanceStore,
    status: InMemoryStateStore,
    *,
    resource_type_mappings: dict[str, str] | None = None,
    ontology_release_digest: str = ONTOLOGY_RELEASE_DIGEST,
) -> InventoryOntologyProjector:
    return InventoryOntologyProjector(
        store=store,
        status_store=status,
        ontology_release_digest=ontology_release_digest,
        resource_type_mappings=resource_type_mappings,
        allow_non_atomic_store=not hasattr(store, "replace_subgraph_with_state"),
    )


async def test_projection_advances_journal_watermark_only_after_graph_commit() -> None:
    status = InMemoryStateStore()
    store = _AtomicOntologyStore(status)
    journal = _RecordingObservationJournal()
    projector = InventoryOntologyProjector(
        store=store,
        status_store=status,
        ontology_release_digest=ONTOLOGY_RELEASE_DIGEST,
        observation_journal=journal,
    )

    result = await projector.apply(
        _observation(generation="snapshot-watermark", resource_ids=("vm-1",)),
        journal_high_watermark=7,
        projection_high_watermark=6,
    )

    assert journal.calls == [("snapshot-watermark", 6)]
    assert result.journal_high_watermark == 7
    assert result.projection_high_watermark == 6
    manifest = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    assert manifest is not None
    assert manifest["journal_high_watermark"] == 7
    assert manifest["projection_high_watermark"] == 6


def _observation(
    *,
    generation: str,
    resource_ids: tuple[str, ...],
    links: tuple[LinkRecord, ...] = (),
    relationship_drops: tuple[RelationshipDrop, ...] = (),
    complete: bool = True,
    attach_metadata: bool = True,
) -> PromotedInventoryObservation:
    return PromotedInventoryObservation(
        generation=generation,
        resources=tuple(
            ResourceRecord(resource_id=item, type="compute.vm", props={"name": item})
            for item in resource_ids
        ),
        links=tuple(
            replace(link, observation_metadata=_metadata(generation, index))
            for index, link in enumerate(links)
        )
        if attach_metadata
        else links,
        complete=complete,
        relationship_drops=relationship_drops,
    )


def _metadata(generation: str, index: int) -> LinkObservationMetadata:
    recorded_at = datetime(2026, 8, 12, 12, tzinfo=UTC)
    return LinkObservationMetadata(
        state_fact=StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity="inventory-provider",
            source_revision="provider-schema-v1",
            effective_at=recorded_at - timedelta(minutes=1),
            recorded_at=recorded_at,
            evidence_cutoff=recorded_at - timedelta(minutes=1),
            freshness_ceiling_seconds=300,
            completeness=1.0,
            synthetic=False,
            evidence_refs=(f"inventory-receipt-{index}",),
        ),
        verification_method="deterministic-cross-check",
        verified=True,
        verifier_identity="inventory-generation-verifier",
        verifier_revision="verifier-v1",
        verification_receipt_ref=f"verification-receipt-{index}",
        inventory_generation=generation,
        mapping_id=f"test.mapping-{index}",
        mapping_revision="sha256:" + "1" * 64,
        source_schema_version="provider-schema-v1",
        source_schema_digest="sha256:" + "2" * 64,
    )


async def test_first_generation_writes_owned_objects_and_manifest() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = _projector(store, status)

    result = await projector.apply(
        _observation(
            generation="snapshot-1",
            resource_ids=("vm-1", "vm-2"),
            links=(
                LinkRecord(
                    from_id="vm-1",
                    from_type="compute.vm",
                    link_type="depends_on",
                    to_id="vm-2",
                    to_type="compute.vm",
                ),
            ),
        )
    )

    assert result.generation == "snapshot-1"
    assert result.ontology_release_digest == ONTOLOGY_RELEASE_DIGEST
    assert result.object_count == 2
    assert result.link_count == 1
    assert result.complete is True
    assert result.relationship_complete is True

    manifest = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    assert manifest is not None
    assert sorted(manifest["object_ids"]) == ["vm-1", "vm-2"]
    assert manifest["generation"] == "snapshot-1"
    assert manifest["ontology_release_digest"] == ONTOLOGY_RELEASE_DIGEST
    status_record = await status.read_state(INVENTORY_ONTOLOGY_STATUS_KEY)
    assert status_record is not None
    assert status_record["schema_version"] == "1.3.0"
    assert status_record["generation"] == "snapshot-1"
    assert status_record["ontology_release_digest"] == ONTOLOGY_RELEASE_DIGEST
    assert status_record["status"] == "available"
    assert status_record["complete"] is True
    assert status_record["relationship_complete"] is True
    assert status_record["dropped_reasons"] == []
    manifest = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    assert manifest is not None
    assert status_record["manifest_digest"] == manifest["manifest_digest"]


async def test_projector_serializes_the_complete_commit_under_injected_lock() -> None:
    store = _store()
    status = InMemoryStateStore()
    projection_lock = _RecordingProjectionLock()
    projector = InventoryOntologyProjector(
        store=store,
        status_store=status,
        ontology_release_digest=ONTOLOGY_RELEASE_DIGEST,
        projection_lock=projection_lock,
        allow_non_atomic_store=True,
    )

    await asyncio.gather(
        projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",))),
        projector.apply(_observation(generation="snapshot-2", resource_ids=("vm-2",))),
    )

    assert projection_lock.entries == 2
    assert projection_lock.max_active == 1
    manifest = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    assert manifest is not None
    assert manifest["generation"] == "snapshot-2"


async def test_projector_rejects_non_atomic_store_before_graph_write() -> None:
    store = _store()
    projector = InventoryOntologyProjector(
        store=store,
        status_store=InMemoryStateStore(),
        ontology_release_digest=ONTOLOGY_RELEASE_DIGEST,
    )

    with pytest.raises(RuntimeError, match="requires atomic graph and state commits"):
        await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))

    assert await store.get_object("vm-1") is None


async def test_projector_retry_recovers_after_manifest_write_before_status_commit() -> None:
    status = _FailStatusOnceStore()
    store = _AtomicOntologyStore(status)
    projector = _projector(store, status)
    observation = _observation(generation="snapshot-1", resource_ids=("vm-1",))

    with pytest.raises(RuntimeError, match="injected status commit failure"):
        await projector.apply(observation)

    assert await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY) is None
    assert await status.read_state(INVENTORY_ONTOLOGY_STATUS_KEY) is None
    result = await projector.apply(observation)
    assert result.status == "available"
    committed = await status.read_state(INVENTORY_ONTOLOGY_STATUS_KEY)
    assert committed is not None
    assert committed["generation"] == "snapshot-1"


async def test_projector_retry_recovers_after_graph_commit_before_manifest_write() -> None:
    status = _FailManifestOnceStore()
    store = _AtomicOntologyStore(status)
    projector = _projector(store, status)
    observation = _observation(generation="snapshot-1", resource_ids=("vm-1",))

    with pytest.raises(RuntimeError, match="injected manifest commit failure"):
        await projector.apply(observation)

    assert await store.get_object("vm-1") is None

    result = await projector.apply(observation)

    assert result.status == "available"
    manifest = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    committed = await status.read_state(INVENTORY_ONTOLOGY_STATUS_KEY)
    assert manifest is not None
    assert committed is not None
    assert committed["manifest_digest"] == manifest["manifest_digest"]


async def test_new_generation_replaces_interrupted_generation_without_foreign_ownership() -> None:
    status = _FailManifestOnceStore()
    store = _AtomicOntologyStore(status)
    projector = _projector(store, status)

    with pytest.raises(RuntimeError, match="injected manifest commit failure"):
        await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))

    result = await projector.apply(_observation(generation="snapshot-2", resource_ids=("vm-2",)))

    assert result.status == "available"
    assert await store.get_object("vm-1") is None
    assert await store.get_object("vm-2") is not None


async def test_projector_reads_revisions_in_bounded_batches() -> None:
    store = _CountingOntologyStore()
    projector = _projector(store, InMemoryStateStore())

    await projector.apply(
        _observation(
            generation="snapshot-large",
            resource_ids=tuple(f"vm-{index:04d}" for index in range(1_001)),
        )
    )

    assert store.query_calls == 2


async def test_multi_link_type_manifest_replays_and_upgrades_legacy_schema() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = _projector(store, status)
    observation = _observation(
        generation="snapshot-multi-link",
        resource_ids=("vm-1", "vm-2", "vm-3"),
        links=(
            LinkRecord(
                from_id="vm-2",
                from_type="compute.vm",
                link_type="attached_to",
                to_id="vm-3",
                to_type="compute.vm",
            ),
            LinkRecord(
                from_id="vm-1",
                from_type="compute.vm",
                link_type="routes_to",
                to_id="vm-2",
                to_type="compute.vm",
            ),
        ),
    )

    await projector.apply(observation)
    await projector.apply(observation)
    manifest = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    assert manifest is not None
    legacy_manifest = {
        "schema_version": "1.2.0",
        "generation": manifest["generation"],
        "ontology_release_digest": manifest["ontology_release_digest"],
        "object_ids": manifest["object_ids"],
        "link_keys": manifest["link_keys"],
    }
    await status.write_state(INVENTORY_ONTOLOGY_MANIFEST_KEY, legacy_manifest)

    await projector.apply(observation)

    upgraded = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    assert upgraded is not None
    assert upgraded["schema_version"] == "1.3.0"
    assert upgraded["link_keys"] == [
        ["vm-2", "attached_to", "vm-3"],
        ["vm-1", "routes_to", "vm-2"],
    ]


async def test_projector_rejects_tampered_manifest_before_replacing_owned_graph() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = _projector(store, status)
    await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))

    manifest = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    assert manifest is not None
    manifest["object_ids"] = ["vm-tampered"]
    await status.write_state(INVENTORY_ONTOLOGY_MANIFEST_KEY, manifest)

    with pytest.raises(ValueError, match="manifest (digest|object content)"):
        await projector.apply(_observation(generation="snapshot-2", resource_ids=("vm-2",)))

    assert await store.get_object("vm-1") is not None
    assert await store.get_object("vm-2") is None


async def test_projector_rejects_same_generation_content_changes() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = _projector(store, status)
    observation = _observation(generation="snapshot-same", resource_ids=("vm-1",))
    await projector.apply(observation)
    changed = replace(
        observation,
        resources=(replace(observation.resources[0], props={"name": "changed"}),),
    )

    with pytest.raises(ValueError, match="generation content changed"):
        await projector.apply(changed)


async def test_projector_reprojects_same_generation_for_new_ontology_release() -> None:
    store = _store()
    status = InMemoryStateStore()
    observation = _observation(generation="snapshot-same", resource_ids=("vm-1",))
    await _projector(store, status).apply(observation)
    next_release_digest = "sha256:" + "b" * 64

    result = await _projector(
        store,
        status,
        ontology_release_digest=next_release_digest,
    ).apply(observation)

    manifest = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    projection_status = await status.read_state(INVENTORY_ONTOLOGY_STATUS_KEY)
    assert result.ontology_release_digest == next_release_digest
    assert manifest is not None
    assert manifest["ontology_release_digest"] == next_release_digest
    assert projection_status is not None
    assert projection_status["ontology_release_digest"] == next_release_digest
    assert await store.get_object("vm-1") is not None


async def test_release_transition_rejects_same_generation_content_changes() -> None:
    store = _store()
    status = InMemoryStateStore()
    observation = _observation(generation="snapshot-same", resource_ids=("vm-1",))
    await _projector(store, status).apply(observation)
    changed = replace(
        observation,
        resources=(replace(observation.resources[0], props={"name": "changed"}),),
    )

    with pytest.raises(ValueError, match="generation content changed"):
        await _projector(
            store,
            status,
            ontology_release_digest="sha256:" + "b" * 64,
        ).apply(changed)


async def test_legacy_manifest_cannot_cross_ontology_releases() -> None:
    store = _store()
    status = InMemoryStateStore()
    observation = _observation(generation="snapshot-legacy", resource_ids=("vm-1",))
    await store.upsert_object(
        OntologyObjectRecord(
            id="vm-1",
            object_type="Resource",
            properties={"id": "vm-1", "type": "compute.vm", "name": "vm-1"},
        )
    )
    await status.write_state(
        INVENTORY_ONTOLOGY_MANIFEST_KEY,
        {
            "schema_version": "1.2.0",
            "generation": observation.generation,
            "ontology_release_digest": ONTOLOGY_RELEASE_DIGEST,
            "complete": True,
            "relationship_complete": True,
            "dropped_reasons": [],
            "object_ids": ["vm-1"],
            "link_keys": [],
        },
    )

    with pytest.raises(ValueError, match="legacy inventory ontology manifest"):
        await _projector(
            store,
            status,
            ontology_release_digest="sha256:" + "b" * 64,
        ).apply(observation)


async def test_manifest_digest_binds_object_and_link_properties() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = _projector(store, status)
    link = LinkRecord(
        from_id="vm-1",
        from_type="compute.vm",
        link_type="depends_on",
        to_id="vm-2",
        to_type="compute.vm",
    )
    await projector.apply(
        _observation(generation="snapshot-content", resource_ids=("vm-1", "vm-2"), links=(link,))
    )
    manifest = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    assert manifest is not None
    manifest["link_content"][0]["properties"] = {"tampered": True}
    await status.write_state(INVENTORY_ONTOLOGY_MANIFEST_KEY, manifest)

    with pytest.raises(ValueError, match="manifest digest"):
        await projector.apply(
            _observation(generation="snapshot-content-next", resource_ids=("vm-3",))
        )


async def test_legacy_manifest_is_rebuilt_to_current_schema_on_retry() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = _projector(store, status)
    observation = _observation(generation="snapshot-legacy", resource_ids=("vm-1",))
    await store.upsert_object(
        OntologyObjectRecord(
            id="vm-1",
            object_type="Resource",
            properties={"id": "vm-1", "type": "compute.vm", "name": "vm-1"},
        )
    )
    await status.write_state(
        INVENTORY_ONTOLOGY_MANIFEST_KEY,
        {
            "schema_version": "1.2.0",
            "generation": observation.generation,
            "ontology_release_digest": ONTOLOGY_RELEASE_DIGEST,
            "complete": True,
            "relationship_complete": True,
            "dropped_reasons": [],
            "object_ids": ["vm-1"],
            "link_keys": [],
        },
    )

    await projector.apply(observation)
    upgraded = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    assert upgraded is not None
    assert upgraded["schema_version"] == "1.3.0"
    assert upgraded["object_content"][0]["properties"]["name"] == "vm-1"


def test_projector_rejects_unpinned_ontology_release() -> None:
    with pytest.raises(ValueError, match="release digest"):
        InventoryOntologyProjector(
            store=_store(),
            status_store=InMemoryStateStore(),
            ontology_release_digest="unbound",
        )


async def test_projector_persists_resource_type_classification() -> None:
    store = _store()
    status = InMemoryStateStore()
    await store.upsert_object(
        OntologyObjectRecord(
            id="compute.vm",
            object_type="ResourceType",
            properties={"id": "compute.vm", "category": "compute"},
        )
    )
    projector = _projector(
        store,
        status,
        resource_type_mappings={"compute.vm": "sha256:" + ("a" * 64)},
    )

    result = await projector.apply(
        _observation(generation="snapshot-classified", resource_ids=("vm-1",))
    )

    assert result.complete is True
    assert result.link_count == 1
    graph = await store.traverse(
        root_ids=("vm-1",),
        link_types=("resource_classified_as",),
        max_depth=1,
        limit=10,
    )
    assert [(item.from_id, item.to_id) for item in graph.links] == [("vm-1", "compute.vm")]


async def test_projector_drops_unseeded_resource_type_without_blocking_generation() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = _projector(
        store,
        status,
        resource_type_mappings={"compute.vm": "sha256:" + ("a" * 64)},
    )

    result = await projector.apply(
        _observation(generation="snapshot-seed-drift", resource_ids=("vm-1",))
    )

    assert result.complete is True
    assert result.link_count == 0
    assert result.dropped_reasons == ("unseeded_resource_type",)
    assert await store.get_object("vm-1") is not None
    status_record = await status.read_state(INVENTORY_ONTOLOGY_STATUS_KEY)
    assert status_record is not None
    assert status_record["status"] == "available"
    assert status_record["relationship_complete"] is False
    assert status_record["dropped_reasons"] == ["unseeded_resource_type"]


async def test_classified_non_edge_advances_manifest_with_incomplete_coverage() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = _projector(store, status)
    await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))

    result = await projector.apply(
        _observation(
            generation="snapshot-2",
            resource_ids=("vm-2",),
            relationship_drops=(
                RelationshipDrop(
                    reason=RelationshipDropReason.MISSING_TARGET_ENDPOINT,
                    mapping_id="azure.example-depends-on-target",
                    unavailable_reason=(
                        RelationshipUnavailableReason.TARGET_OUTSIDE_ACTIVE_GENERATION
                    ),
                ),
            ),
        )
    )

    assert result.status == "available"
    assert result.complete is True
    assert result.relationship_complete is False
    assert await store.get_object("vm-1") is None
    assert await store.get_object("vm-2") is not None
    manifest = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    assert manifest is not None
    assert manifest["generation"] == "snapshot-2"
    assert manifest["complete"] is True
    assert manifest["relationship_complete"] is False
    assert manifest["dropped_reasons"] == ["missing_target_endpoint"]


async def test_projector_rejects_malformed_mapping_for_unseeded_resource_type() -> None:
    projector = _projector(
        _store(),
        InMemoryStateStore(),
        resource_type_mappings={"compute.vm": "not-a-digest"},
    )

    with pytest.raises(ValueError, match="canonical SHA-256"):
        await projector.apply(
            _observation(generation="snapshot-invalid-mapping", resource_ids=("vm-1",))
        )


async def test_one_resource_can_retain_multiple_observed_attachments() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = _projector(store, status)

    result = await projector.apply(
        _observation(
            generation="snapshot-attachments",
            resource_ids=("vm-1", "network-1", "disk-1"),
            links=(
                LinkRecord(
                    from_id="vm-1",
                    from_type="compute.vm",
                    link_type="attached_to",
                    to_id="network-1",
                    to_type="compute.vm",
                ),
                LinkRecord(
                    from_id="vm-1",
                    from_type="compute.vm",
                    link_type="attached_to",
                    to_id="disk-1",
                    to_type="compute.vm",
                ),
            ),
        )
    )

    assert result.link_count == 2


async def test_next_generation_deletes_disappeared_resources() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = _projector(store, status)

    await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1", "vm-2")))
    await projector.apply(_observation(generation="snapshot-2", resource_ids=("vm-1",)))

    assert await store.get_object("vm-1") is not None
    assert await store.get_object("vm-2") is None


async def test_repeated_generation_is_idempotent() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = _projector(store, status)

    first = await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))
    second = await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))

    assert first.object_count == second.object_count == 1
    assert await store.get_object("vm-1") is not None


async def test_foreign_owned_object_is_rejected() -> None:
    store = _store()
    status = InMemoryStateStore()
    await store.upsert_object(
        OntologyObjectRecord(
            id="vm-1",
            object_type="Resource",
            properties={"id": "vm-1", "type": "compute.vm"},
        )
    )
    projector = _projector(store, status)

    with pytest.raises(OntologyInstanceValidationError, match="owned by another projection"):
        await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))


async def test_incomplete_observation_preserves_prior_projection_and_records_unavailable() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = _projector(store, status)

    await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))
    prior_manifest = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    result = await projector.apply(
        _observation(generation="snapshot-2", resource_ids=("vm-2",), complete=False)
    )

    assert result.complete is False
    assert "observation_incomplete" in result.dropped_reasons
    assert getattr(result, "status", None) == "unavailable"
    assert await store.get_object("vm-1") is not None
    assert await store.get_object("vm-2") is None
    assert await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY) == prior_manifest
    unavailable_status = await status.read_state("inventory-ontology:status")
    assert unavailable_status is not None
    assert unavailable_status["schema_version"] == "1.3.0"
    assert unavailable_status["generation"] == "snapshot-2"
    assert unavailable_status["ontology_release_digest"] == ONTOLOGY_RELEASE_DIGEST
    assert unavailable_status["status"] == "unavailable"
    assert unavailable_status["complete"] is False
    assert unavailable_status["relationship_complete"] is False
    assert unavailable_status["dropped_reasons"] == ["observation_incomplete"]


async def test_replay_refuses_incomplete_projection_before_status_write() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = _projector(store, status)
    await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))
    prior_status = await status.read_state(INVENTORY_ONTOLOGY_STATUS_KEY)

    with pytest.raises(ValueError, match="replay is incomplete"):
        await projector.apply(
            _observation(generation="snapshot-1", resource_ids=("vm-1",), complete=False),
            fail_before_incomplete_status=True,
        )

    assert await status.read_state(INVENTORY_ONTOLOGY_STATUS_KEY) == prior_status


async def test_metadata_less_link_preserves_prior_projection_and_reports_unverified() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = _projector(store, status)
    await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))

    result = await projector.apply(
        _observation(
            generation="snapshot-2",
            resource_ids=("vm-1", "vm-2"),
            links=(
                LinkRecord(
                    from_id="vm-1",
                    from_type="compute.vm",
                    link_type="depends_on",
                    to_id="vm-2",
                    to_type="compute.vm",
                ),
            ),
            attach_metadata=False,
        )
    )

    assert result.status == "unavailable"
    assert result.link_count == 0
    assert "unverified_metadata" in result.dropped_reasons
    assert await store.get_object("vm-2") is None
