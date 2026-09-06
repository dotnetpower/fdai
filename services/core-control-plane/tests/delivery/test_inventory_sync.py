"""Fail-closed inventory synchronization and fallback tests."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fdai.delivery.inventory_sync import (
    InventoryProjectionSourceState,
    InventoryProjectionSourceStatus,
    InventoryRelationshipCoverage,
    InventoryStreamError,
    InventorySyncCoordinator,
    PromotedInventoryObservation,
    _ObservationAccumulator,
    _validate_resource_state_enrichment,
    compute_relationship_coverage,
)
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    load_provider_relationship_mapping_catalog,
)
from fdai.shared.providers.inventory import (
    InventoryBatch,
    LinkRecord,
    ProviderScopeCoverage,
    ProviderTypeCount,
    RelationshipDrop,
    RelationshipDropReason,
    RelationshipUnavailableReason,
    ResourceRecord,
)
from fdai.shared.providers.inventory_snapshot import (
    InventoryAttemptFailure,
    InventoryCoverageManifest,
    InventoryFailureCode,
    InventorySource,
    InventorySourcesExhaustedError,
)
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)


@dataclass
class _Store:
    batches: dict[str, list[InventoryBatch]] = field(default_factory=dict)
    promoted: list[str] = field(default_factory=list)
    promoted_manifests: list[InventoryCoverageManifest] = field(default_factory=list)
    failed: list[tuple[str, InventoryAttemptFailure]] = field(default_factory=list)
    sequence: int = 0

    async def begin(self, manifest: InventoryCoverageManifest) -> str:
        self.sequence += 1
        attempt = f"attempt-{self.sequence}"
        self.batches[attempt] = []
        return attempt

    async def stage(self, attempt_id: str, batch: InventoryBatch) -> None:
        self.batches[attempt_id].append(batch)

    async def promote(self, attempt_id: str, manifest: InventoryCoverageManifest) -> None:
        self.promoted.append(attempt_id)
        self.promoted_manifests.append(manifest)

    async def fail(self, attempt_id: str, failure: InventoryAttemptFailure) -> None:
        self.failed.append((attempt_id, failure))


def test_drop_classifications_can_use_the_verified_promoted_drop_set() -> None:
    accumulator = _ObservationAccumulator(
        enabled=True,
        relationship_mapping_catalog=None,
    )

    classifications = accumulator.relationship_drop_classifications(
        (RelationshipDrop(reason=RelationshipDropReason.UNVERIFIED_METADATA),)
    )

    assert classifications == (
        {
            "reason": "unverified_metadata",
            "mapping_id": "unattributed",
            "source_property_path": "unattributed",
            "source_provider_type": "unattributed",
            "target_provider_type": "unresolved",
            "unavailable_reason": "unclassified",
            "count": 1,
        },
    )


class _Inventory:
    def __init__(self, batches: list[InventoryBatch] | None = None, error: Exception | None = None):
        self._batches = batches or []
        self._error = error

    async def full_snapshot(self, since: str | None = None):
        del since
        for batch in self._batches:
            yield batch
        if self._error is not None:
            raise self._error

    async def delta(self, cursor: str):
        del cursor
        yield InventoryBatch(final=True)


def _source(name: str, inventory: Any) -> InventorySource:
    return InventorySource(
        name=name,
        inventory=inventory,
        manifest=InventoryCoverageManifest(
            source=name,
            scopes=("scope-1",),
            resource_types=("compute.vm",),
        ),
    )


class _StallingInventory:
    def __init__(self, stalled: asyncio.Event) -> None:
        self._stalled = stalled

    async def full_snapshot(self, since: str | None = None):
        del since
        yield InventoryBatch(
            resources=(ResourceRecord(resource_id="r-1", type="compute.vm", props={}),)
        )
        self._stalled.set()
        await asyncio.Event().wait()

    async def delta(self, cursor: str):
        del cursor
        yield InventoryBatch(final=True)


class _SlowButProgressingInventory:
    def __init__(self, *, beats: int, gap_seconds: float) -> None:
        self._beats = beats
        self._gap = gap_seconds

    async def full_snapshot(self, since: str | None = None):
        del since
        for _ in range(self._beats):
            await asyncio.sleep(self._gap)
            yield InventoryBatch()
        yield InventoryBatch(final=True)

    async def delta(self, cursor: str):
        del cursor
        yield InventoryBatch(final=True)


class _CancellationAwareInventory:
    def __init__(self) -> None:
        self.closed = False

    async def full_snapshot(self, since: str | None = None):
        del since
        try:
            yield InventoryBatch()
            await asyncio.Event().wait()
        except BaseException:
            self.closed = True
            raise

    async def delta(self, cursor: str):
        del cursor
        yield InventoryBatch(final=True)


class _DropEnricher:
    async def enrich(
        self, observation: PromotedInventoryObservation
    ) -> PromotedInventoryObservation:
        return replace(
            observation,
            relationship_drops=(
                RelationshipDrop(reason=RelationshipDropReason.MISSING_TARGET_ENDPOINT),
            ),
        )


class _RunLock:
    def __init__(self) -> None:
        self.active = False
        self.ids: list[str] = []

    @asynccontextmanager
    async def acquire(self, resource_id: str):
        assert not self.active
        self.active = True
        self.ids.append(resource_id)
        try:
            yield
        finally:
            self.active = False


async def test_complete_stream_promotes_terminal_records() -> None:
    store = _Store()
    resource = ResourceRecord(resource_id="vm-1", type="compute.vm")
    result = await InventorySyncCoordinator(store=store).run(
        [_source("arg", _Inventory([InventoryBatch(resources=(resource,), final=True)]))]
    )
    assert result.source == "arg"
    assert store.promoted == ["attempt-1"]
    assert store.batches["attempt-1"][0].resources == (resource,)
    assert store.batches["attempt-1"][0].final is False


async def test_run_lock_serializes_collection_promotion_and_observer() -> None:
    lock = _RunLock()
    store = _Store()
    observed: list[tuple[str, bool]] = []

    async def recover() -> None:
        observed.append(("recovery", lock.active))

    async def observer(_observation: PromotedInventoryObservation) -> None:
        observed.append(("observer", lock.active))

    await InventorySyncCoordinator(
        store=store,
        promotion_observer=observer,
        pre_run_recovery=recover,
        run_lock=lock,
    ).run((_source("arg", _Inventory([InventoryBatch(final=True)])),))

    assert lock.ids == ["inventory-sync-coordinator"]
    assert observed == [("recovery", True), ("observer", True)]
    assert lock.active is False


async def test_failed_recovery_blocks_new_inventory_attempt() -> None:
    store = _Store()

    async def recover() -> None:
        raise RuntimeError("pending projection unavailable")

    with pytest.raises(RuntimeError, match="pending projection unavailable"):
        await InventorySyncCoordinator(
            store=store,
            pre_run_recovery=recover,
        ).run((_source("arg", _Inventory([InventoryBatch(final=True)])),))

    assert store.batches == {}
    assert store.promoted == []


async def test_enrichment_relationship_gaps_reach_the_promoted_manifest() -> None:
    store = _Store()
    await InventorySyncCoordinator(
        store=store,
        promotion_enricher=_DropEnricher(),
    ).run((_source("arg", _Inventory([InventoryBatch(final=True)])),))

    metadata = store.promoted_manifests[0].metadata
    assert metadata["relationship_complete"] is False
    assert metadata["relationship_drop_reasons"] == ["missing_target_endpoint"]


async def test_stalled_source_fails_its_own_attempt_at_the_progress_deadline() -> None:
    store = _Store()
    stalled = asyncio.Event()
    coordinator = InventorySyncCoordinator(
        store=store,
        progress_deadline_seconds=0.05,
        attempt_deadline_seconds=5.0,
    )

    with pytest.raises(InventorySourcesExhaustedError):
        await coordinator.run((_source("arg", _StallingInventory(stalled)),))

    assert stalled.is_set()
    assert store.promoted == []
    assert [failure.code for _, failure in store.failed] == [InventoryFailureCode.PARTIAL]
    assert store.failed[0][1].message == "inventory source exceeded its no-progress deadline"


async def test_deadline_on_one_source_allows_the_next_source() -> None:
    store = _Store()
    coordinator = InventorySyncCoordinator(
        store=store,
        progress_deadline_seconds=0.05,
        attempt_deadline_seconds=5.0,
    )

    result = await coordinator.run(
        (
            _source("arg", _StallingInventory(asyncio.Event())),
            _source("arm", _Inventory([InventoryBatch(final=True)])),
        )
    )

    assert result.source == "arm"
    assert store.promoted == ["attempt-2"]


async def test_slow_source_that_keeps_progressing_is_not_killed() -> None:
    store = _Store()
    coordinator = InventorySyncCoordinator(
        store=store,
        progress_deadline_seconds=0.2,
        attempt_deadline_seconds=5.0,
    )

    result = await coordinator.run(
        (_source("arg", _SlowButProgressingInventory(beats=6, gap_seconds=0.05)),)
    )

    assert result.source == "arg"
    assert store.failed == []


async def test_absolute_ceiling_bounds_a_source_that_keeps_rearming() -> None:
    store = _Store()
    coordinator = InventorySyncCoordinator(
        store=store,
        progress_deadline_seconds=0.2,
        attempt_deadline_seconds=0.25,
    )

    with pytest.raises(InventorySourcesExhaustedError):
        await coordinator.run(
            (_source("arg", _SlowButProgressingInventory(beats=100, gap_seconds=0.05)),)
        )

    assert store.failed[0][1].message == "inventory source exceeded its absolute ceiling"


async def test_timed_out_attempt_closes_its_source_stream() -> None:
    inventory = _CancellationAwareInventory()
    coordinator = InventorySyncCoordinator(
        store=_Store(),
        progress_deadline_seconds=0.05,
        attempt_deadline_seconds=5.0,
    )

    with pytest.raises(InventorySourcesExhaustedError):
        await coordinator.run((_source("arg", inventory),))

    assert inventory.closed is True


def test_coordinator_rejects_incompatible_attempt_deadlines() -> None:
    with pytest.raises(ValueError, match="progress_deadline_seconds"):
        InventorySyncCoordinator(store=_Store(), progress_deadline_seconds=0)
    with pytest.raises(ValueError, match="attempt_deadline_seconds"):
        InventorySyncCoordinator(
            store=_Store(),
            progress_deadline_seconds=100,
            attempt_deadline_seconds=99,
        )
    with pytest.raises(ValueError, match="abandonment window"):
        InventorySyncCoordinator(store=_Store(), attempt_deadline_seconds=1741)


async def test_final_fence_coverage_is_promoted_as_snapshot_metadata() -> None:
    store = _Store()
    coverage = ProviderScopeCoverage(
        capture_method="provider_type_aggregation",
        provider_object_count=12,
        mapped_provider_object_count=9,
        provider_type_count=4,
        unmapped_provider_types=(
            ProviderTypeCount(provider_type="example.extensions", count=1),
            ProviderTypeCount(provider_type="example.watchers", count=2),
        ),
    )

    await InventorySyncCoordinator(store=store).run(
        [
            _source(
                "arg",
                _Inventory([InventoryBatch(final=True, provider_scope_coverage=coverage)]),
            )
        ]
    )

    assert store.promoted_manifests[0].metadata["provider_scope_coverage"] == {
        "schema_version": "1.1.0",
        "capture_method": "provider_type_aggregation",
        "provider_object_count": 12,
        "mapped_provider_object_count": 9,
        "unmapped_provider_object_count": 3,
        "materialized_unmapped_provider_object_count": 0,
        "provider_identity_complete": False,
        "provider_type_count": 4,
        "unmapped_provider_type_count": 2,
        "unmapped_provider_types": [
            {"provider_type": "example.extensions", "count": 1},
            {"provider_type": "example.watchers", "count": 2},
        ],
    }


async def test_missing_fence_falls_back_without_promotion() -> None:
    store = _Store()
    result = await InventorySyncCoordinator(store=store).run(
        [
            _source("arg", _Inventory([InventoryBatch()])),
            _source("arm", _Inventory([InventoryBatch(final=True)])),
        ]
    )
    assert result.source == "arm"
    assert result.failures[0].code is InventoryFailureCode.PARTIAL
    assert store.promoted == ["attempt-2"]


async def test_data_after_fence_is_rejected() -> None:
    store = _Store()
    with pytest.raises(InventorySourcesExhaustedError) as error:
        await InventorySyncCoordinator(store=store).run(
            [
                _source(
                    "arg",
                    _Inventory([InventoryBatch(final=True), InventoryBatch(resources=())]),
                )
            ]
        )
    assert error.value.failures[0].code is InventoryFailureCode.PARTIAL


async def test_promotion_observer_receives_the_promoted_generation() -> None:
    store = _Store()
    observed: list[PromotedInventoryObservation] = []

    async def _record(observation: PromotedInventoryObservation) -> None:
        observed.append(observation)

    resource = ResourceRecord(resource_id="vm-1", type="compute.vm")
    await InventorySyncCoordinator(store=store, promotion_observer=_record).run(
        [_source("arg", _Inventory([InventoryBatch(resources=(resource,), final=True)]))]
    )
    assert [item.generation for item in observed] == ["attempt-1"]
    assert observed[0].resources == (resource,)
    assert observed[0].complete is True
    assert observed[0].recorded_at is not None
    assert observed[0].recorded_at.tzinfo is not None


async def test_subset_snapshot_cannot_replace_complete_derived_projection() -> None:
    store = _Store()
    observed: list[PromotedInventoryObservation] = []

    async def _record(observation: PromotedInventoryObservation) -> None:
        observed.append(observation)

    source = InventorySource(
        name="arg",
        inventory=_Inventory(
            [
                InventoryBatch(
                    resources=(ResourceRecord(resource_id="r-1", type="compute.vm"),),
                    final=True,
                )
            ]
        ),
        manifest=InventoryCoverageManifest(
            source="arg",
            scopes=("scope-1",),
            resource_types=("compute.vm",),
            metadata={"coverage_scope": "requested_resource_types"},
        ),
    )

    with pytest.raises(InventorySourcesExhaustedError):
        await InventorySyncCoordinator(store=store, promotion_observer=_record).run((source,))

    assert observed == []
    assert store.promoted_manifests == []


async def test_promotion_enrichment_stages_verified_links_before_single_writer_observation() -> (
    None
):
    store = _Store()
    observed: list[PromotedInventoryObservation] = []

    class _Enricher:
        async def enrich(
            self,
            observation: PromotedInventoryObservation,
        ) -> PromotedInventoryObservation:
            assert observation.recorded_at is not None
            metadata = LinkObservationMetadata(
                state_fact=StateFactMetadata(
                    lane=StateFactLane.OBSERVED,
                    authority=StateFactAuthority.TELEMETRY,
                    source_identity="telemetry.runtime-calls",
                    source_revision="1.0.0",
                    effective_at=observation.recorded_at,
                    recorded_at=observation.recorded_at,
                    evidence_cutoff=observation.recorded_at,
                    freshness_ceiling_seconds=300,
                    completeness=1.0,
                    synthetic=False,
                    evidence_refs=("telemetry:runtime-call:one",),
                ),
                verification_method="deterministic-cross-check",
                verified=True,
                verifier_identity="inventory.endpoint-verifier",
                verifier_revision="1.0.0",
                verification_receipt_ref="sha256:" + "1" * 64,
                inventory_generation=observation.generation,
                mapping_id="runtime-call-endpoint-identity",
                mapping_revision="1.0.0",
                source_schema_version="fdai.runtime-call-observation@1.1.0",
                source_schema_digest="sha256:" + "2" * 64,
            )
            return replace(
                observation,
                links=(
                    *observation.links,
                    LinkRecord(
                        from_id="caller",
                        from_type="compute.vm",
                        link_type="runtime_calls",
                        to_id="target",
                        to_type="compute.vm",
                        observation_metadata=metadata,
                    ),
                ),
                source_states=(
                    InventoryProjectionSourceState(
                        source="runtime_call_graph",
                        status=InventoryProjectionSourceStatus.AVAILABLE,
                        observed_at=observation.recorded_at,
                        reason=None,
                    ),
                ),
            )

    async def _record(observation: PromotedInventoryObservation) -> None:
        observed.append(observation)

    resources = (
        ResourceRecord(resource_id="caller", type="compute.vm"),
        ResourceRecord(resource_id="target", type="compute.vm"),
    )
    await InventorySyncCoordinator(
        store=store,
        promotion_enricher=_Enricher(),
        promotion_observer=_record,
    ).run([_source("arg", _Inventory([InventoryBatch(resources=resources, final=True)]))])

    assert store.promoted == ["attempt-1"]
    assert [link.link_type for batch in store.batches["attempt-1"] for link in batch.links] == [
        "runtime_calls"
    ]
    assert [link.link_type for link in observed[0].links] == ["runtime_calls"]
    assert store.promoted_manifests[0].metadata["derived_source_states"] == [
        {
            "source": "runtime_call_graph",
            "status": "available",
            "observed_at": observed[0].recorded_at.isoformat(),
            "reason": None,
        }
    ]


async def test_promotion_enrichment_cannot_replace_provider_records() -> None:
    store = _Store()

    class _Enricher:
        async def enrich(
            self,
            observation: PromotedInventoryObservation,
        ) -> PromotedInventoryObservation:
            return replace(observation, resources=())

    with pytest.raises(InventorySourcesExhaustedError):
        await InventorySyncCoordinator(
            store=store,
            promotion_enricher=_Enricher(),
        ).run(
            [
                _source(
                    "arg",
                    _Inventory(
                        [
                            InventoryBatch(
                                resources=(ResourceRecord("resource:one", "compute.vm"),),
                                final=True,
                            )
                        ]
                    ),
                )
            ]
        )

    assert store.promoted == []


async def test_promotion_enrichment_stages_provider_availability_without_replacing_resource() -> (
    None
):
    store = _Store()
    observed: list[PromotedInventoryObservation] = []

    class _Enricher:
        async def enrich(
            self,
            observation: PromotedInventoryObservation,
        ) -> PromotedInventoryObservation:
            assert observation.recorded_at is not None
            resource = observation.resources[0]
            props = {
                **resource.props,
                "availabilityState": "Available",
                "availabilityReasonKind": "status_only",
                "state_fact_metadata": {
                    "availabilityState": StateFactMetadata(
                        lane=StateFactLane.OBSERVED,
                        authority=StateFactAuthority.PROVIDER,
                        source_identity="azure-resource-health",
                        source_revision="azure-resource-health:sha256:" + "1" * 64,
                        effective_at=observation.recorded_at,
                        recorded_at=observation.recorded_at,
                        evidence_cutoff=observation.recorded_at,
                        freshness_ceiling_seconds=300,
                        completeness=1.0,
                        synthetic=False,
                        evidence_refs=("azure-resource-health:sha256:" + "1" * 64,),
                    ).to_mapping()
                },
            }
            return replace(
                observation,
                resources=(replace(resource, props=props),),
                state_base_generation="snapshot-0",
                state_base_generation_checked=True,
            )

    async def _record(observation: PromotedInventoryObservation) -> None:
        observed.append(observation)

    resource = ResourceRecord(
        resource_id="workspace-1",
        type="log-workspace",
        props={"name": "workspace"},
        provider_ref="/subscriptions/example/resourceGroups/example/providers/example/type/one",
        last_seen="2026-09-06T00:00:00+00:00",
    )
    await InventorySyncCoordinator(
        store=store,
        promotion_enricher=_Enricher(),
        promotion_observer=_record,
    ).run([_source("arg", _Inventory([InventoryBatch(resources=(resource,), final=True)]))])

    staged = [
        item
        for batch in store.batches["attempt-1"]
        for item in batch.resources
        if item.resource_id == "workspace-1"
    ]
    assert len(staged) == 2
    assert staged[-1].props["availabilityState"] == "Available"
    assert observed[0].resources[0].props["name"] == "workspace"
    assert observed[0].resources[0].props["availabilityState"] == "Available"
    assert store.promoted_manifests[0].metadata["state_base_generation"] == "snapshot-0"


async def test_promotion_enrichment_stages_reviewed_static_web_app_operational_state() -> None:
    store = _Store()
    observed: list[PromotedInventoryObservation] = []

    class _Enricher:
        async def enrich(
            self,
            observation: PromotedInventoryObservation,
        ) -> PromotedInventoryObservation:
            assert observation.recorded_at is not None
            resource = observation.resources[0]
            source_revision = "azure-static-web-app-environment:sha256:" + "1" * 64
            props = {
                **resource.props,
                "staticSiteEnvironmentStatus": "Ready",
                "state_fact_metadata": {
                    "staticSiteEnvironmentStatus": StateFactMetadata(
                        lane=StateFactLane.OBSERVED,
                        authority=StateFactAuthority.PROVIDER,
                        source_identity="azure-static-web-app-default-environment",
                        source_revision=source_revision,
                        effective_at=observation.recorded_at,
                        recorded_at=observation.recorded_at,
                        evidence_cutoff=observation.recorded_at,
                        freshness_ceiling_seconds=300,
                        completeness=1.0,
                        synthetic=False,
                        evidence_refs=(source_revision,),
                    ).to_mapping()
                },
            }
            return replace(
                observation,
                resources=(replace(resource, props=props),),
                state_base_generation="snapshot-0",
                state_base_generation_checked=True,
            )

    async def _record(observation: PromotedInventoryObservation) -> None:
        observed.append(observation)

    resource = ResourceRecord(
        resource_id="static-web-app-1",
        type="static-web-app",
        props={"name": "static-web-app"},
        provider_ref=(
            "/subscriptions/example/resourceGroups/example/providers/Microsoft.Web/staticSites/one"
        ),
        last_seen="2026-09-06T00:00:00+00:00",
    )
    await InventorySyncCoordinator(
        store=store,
        promotion_enricher=_Enricher(),
        promotion_observer=_record,
    ).run([_source("arg", _Inventory([InventoryBatch(resources=(resource,), final=True)]))])

    staged = [
        item
        for batch in store.batches["attempt-1"]
        for item in batch.resources
        if item.resource_id == "static-web-app-1"
    ]
    assert len(staged) == 2
    assert staged[-1].props["staticSiteEnvironmentStatus"] == "Ready"
    assert observed[0].resources[0].props["staticSiteEnvironmentStatus"] == "Ready"


@pytest.mark.parametrize(
    ("source_revision", "evidence_refs"),
    [
        ("not-content-addressed", ("not-content-addressed",)),
        (
            "azure-static-web-app-environment:sha256:" + "1" * 64,
            ("azure-static-web-app-environment:sha256:" + "2" * 64,),
        ),
    ],
)
def test_state_enrichment_rejects_unbound_evidence(
    source_revision: str,
    evidence_refs: tuple[str, ...],
) -> None:
    observed_at = datetime(2026, 9, 6, tzinfo=UTC)
    original = ResourceRecord(resource_id="static-web-app-1", type="static-web-app")
    candidate = replace(
        original,
        props={
            "staticSiteEnvironmentStatus": "Ready",
            "state_fact_metadata": {
                "staticSiteEnvironmentStatus": StateFactMetadata(
                    lane=StateFactLane.OBSERVED,
                    authority=StateFactAuthority.PROVIDER,
                    source_identity="azure-static-web-app-default-environment",
                    source_revision=source_revision,
                    effective_at=observed_at,
                    recorded_at=observed_at,
                    evidence_cutoff=observed_at,
                    freshness_ceiling_seconds=300,
                    completeness=1.0,
                    synthetic=False,
                    evidence_refs=evidence_refs,
                ).to_mapping()
            },
        },
    )

    with pytest.raises(ValueError, match="authoritative provider evidence"):
        _validate_resource_state_enrichment(original, candidate)


def test_state_enrichment_rejects_an_availability_reason_without_state() -> None:
    original = ResourceRecord(resource_id="static-web-app-1", type="static-web-app")
    candidate = replace(
        original,
        props={
            "availabilityReasonKind": "status_only",
            "staticSiteEnvironmentStatus": "Ready",
            "state_fact_metadata": {
                "staticSiteEnvironmentStatus": StateFactMetadata(
                    lane=StateFactLane.OBSERVED,
                    authority=StateFactAuthority.PROVIDER,
                    source_identity="azure-static-web-app-default-environment",
                    source_revision="azure-static-web-app-environment:sha256:" + "1" * 64,
                    effective_at=datetime(2026, 9, 6, tzinfo=UTC),
                    recorded_at=datetime(2026, 9, 6, tzinfo=UTC),
                    evidence_cutoff=datetime(2026, 9, 6, tzinfo=UTC),
                    freshness_ceiling_seconds=300,
                    completeness=1.0,
                    synthetic=False,
                    evidence_refs=("azure-static-web-app-environment:sha256:" + "1" * 64,),
                ).to_mapping()
            },
        },
    )

    with pytest.raises(ValueError, match="reason requires availability state"):
        _validate_resource_state_enrichment(original, candidate)


async def test_promotion_enrichment_cannot_add_a_dangling_endpoint() -> None:
    store = _Store()

    class _Enricher:
        async def enrich(
            self,
            observation: PromotedInventoryObservation,
        ) -> PromotedInventoryObservation:
            assert observation.recorded_at is not None
            metadata = LinkObservationMetadata(
                state_fact=StateFactMetadata(
                    lane=StateFactLane.OBSERVED,
                    authority=StateFactAuthority.TELEMETRY,
                    source_identity="telemetry.runtime-calls",
                    source_revision="1.0.0",
                    effective_at=observation.recorded_at,
                    recorded_at=observation.recorded_at,
                    evidence_cutoff=observation.recorded_at,
                    freshness_ceiling_seconds=300,
                    completeness=1.0,
                    synthetic=False,
                    evidence_refs=("telemetry:runtime-call:one",),
                ),
                verification_method="deterministic-cross-check",
                verified=True,
                verifier_identity="inventory.endpoint-verifier",
                verifier_revision="1.0.0",
                verification_receipt_ref="sha256:" + "1" * 64,
                inventory_generation=observation.generation,
                mapping_id="runtime-call-endpoint-identity",
                mapping_revision="1.0.0",
                source_schema_version="fdai.runtime-call-observation@1.1.0",
                source_schema_digest="sha256:" + "2" * 64,
            )
            return replace(
                observation,
                links=(
                    LinkRecord(
                        from_id="caller",
                        from_type="compute.vm",
                        link_type="runtime_calls",
                        to_id="missing-target",
                        to_type="compute.vm",
                        observation_metadata=metadata,
                    ),
                ),
            )

    resources = (
        ResourceRecord(resource_id="caller", type="compute.vm"),
        ResourceRecord(resource_id="target", type="compute.vm"),
    )
    with pytest.raises(InventorySourcesExhaustedError):
        await InventorySyncCoordinator(
            store=store,
            promotion_enricher=_Enricher(),
        ).run([_source("arg", _Inventory([InventoryBatch(resources=resources, final=True)]))])

    assert store.promoted == []
    assert store.failed[0][1].code is InventoryFailureCode.INVALID_DATA


async def test_promotion_observer_receives_verified_kubernetes_relationships() -> None:
    store = _Store()
    observed: list[PromotedInventoryObservation] = []

    async def _record(observation: PromotedInventoryObservation) -> None:
        observed.append(observation)

    cluster_ref = "kubernetes.cluster:example"
    resources = (
        ResourceRecord(
            resource_id=cluster_ref,
            type="kubernetes-cluster",
            props={"cluster_ref": cluster_ref, "name": "example"},
            last_seen="2026-08-13T10:00:00Z",
        ),
        ResourceRecord(
            resource_id=f"{cluster_ref}/namespace/default",
            type="kubernetes.namespace",
            props={
                "cluster_ref": cluster_ref,
                "namespace": "default",
                "name": "default",
            },
            last_seen="2026-08-13T10:00:00Z",
        ),
        ResourceRecord(
            resource_id=f"{cluster_ref}/service/api",
            type="kubernetes.service",
            props={
                "cluster_ref": cluster_ref,
                "namespace": "default",
                "name": "api",
                "selector": {"app": "api"},
            },
            last_seen="2026-08-13T10:00:00Z",
        ),
        ResourceRecord(
            resource_id=f"{cluster_ref}/pod/api-0",
            type="kubernetes.pod",
            props={
                "cluster_ref": cluster_ref,
                "namespace": "default",
                "name": "api-0",
                "labels": {"app": "api"},
            },
            last_seen="2026-08-13T10:00:00Z",
        ),
        ResourceRecord(
            resource_id=f"{cluster_ref}/endpoints/api",
            type="kubernetes.endpoints",
            props={
                "cluster_ref": cluster_ref,
                "namespace": "default",
                "name": "api",
            },
            last_seen="2026-08-13T10:00:00Z",
        ),
    )
    catalog = load_provider_relationship_mapping_catalog(
        Path("rule-catalog/vocabulary/provider-relationship-mappings")
    )

    await InventorySyncCoordinator(
        store=store,
        promotion_observer=_record,
        relationship_mapping_catalog=catalog,
    ).run([_source("kubernetes", _Inventory([InventoryBatch(resources=resources, final=True)]))])

    assert len(observed) == 1
    assert [link.link_type for link in observed[0].links] == [
        "contains",
        "contains",
        "contains",
        "contains",
        "kubernetes_exposes_endpoints",
        "kubernetes_selects",
    ]
    assert observed[0].relationship_drops == ()
    assert all(
        link.observation_metadata is not None and link.observation_metadata.verified
        for link in observed[0].links
    )


async def test_promotion_manifest_preserves_relationship_coverage_gaps() -> None:
    store = _Store()
    await InventorySyncCoordinator(store=store).run(
        [
            _source(
                "arg",
                _Inventory(
                    [
                        InventoryBatch(
                            relationship_drops=(
                                RelationshipDrop(
                                    reason=RelationshipDropReason.UNRESOLVED_REFERENCE,
                                    mapping_id="azure.example-depends-on-target",
                                    source_property_path="properties.target",
                                    source_provider_type="Microsoft.Example/widgets",
                                    unavailable_reason=(
                                        RelationshipUnavailableReason.REFERENCE_NOT_OBSERVED
                                    ),
                                ),
                            ),
                            final=True,
                        )
                    ]
                ),
            )
        ]
    )

    assert store.promoted_manifests[0].metadata["relationship_complete"] is False
    assert store.promoted_manifests[0].metadata["relationship_drop_reasons"] == [
        "unresolved_reference"
    ]
    assert store.promoted_manifests[0].metadata["relationship_drop_classifications"] == [
        {
            "reason": "unresolved_reference",
            "mapping_id": "azure.example-depends-on-target",
            "source_property_path": "properties.target",
            "source_provider_type": "Microsoft.Example/widgets",
            "target_provider_type": "unresolved",
            "unavailable_reason": "reference_not_observed",
            "count": 1,
        }
    ]
    assert store.promoted_manifests[0].metadata["relationship_coverage"] == {
        "materialized": 0,
        "reviewed_unavailable": 1,
        "unclassified": 0,
        "total_candidates": 1,
        "complete": True,
    }


async def test_promotion_manifest_marks_relationship_coverage_incomplete_when_unclassified() -> (
    None
):
    store = _Store()
    await InventorySyncCoordinator(store=store).run(
        [
            _source(
                "arg",
                _Inventory(
                    [
                        InventoryBatch(
                            relationship_drops=(
                                RelationshipDrop(
                                    reason=RelationshipDropReason.UNRESOLVED_REFERENCE,
                                    mapping_id="azure.example-depends-on-target",
                                    source_property_path="properties.target",
                                    source_provider_type="Microsoft.Example/widgets",
                                    unavailable_reason=(
                                        RelationshipUnavailableReason.REFERENCE_NOT_OBSERVED
                                    ),
                                ),
                                RelationshipDrop(
                                    reason=RelationshipDropReason.UNVERIFIED_METADATA,
                                ),
                            ),
                            final=True,
                        )
                    ]
                ),
            )
        ]
    )

    assert store.promoted_manifests[0].metadata["relationship_coverage"] == {
        "materialized": 0,
        "reviewed_unavailable": 1,
        "unclassified": 1,
        "total_candidates": 2,
        "complete": False,
    }


def test_compute_relationship_coverage_counts_materialized_and_classified_drops() -> None:
    link = LinkRecord(
        from_id="vm-1",
        from_type="compute.vm",
        link_type="depends_on",
        to_id="vm-2",
        to_type="compute.vm",
    )
    observation = PromotedInventoryObservation(
        generation="attempt-1",
        resources=(),
        links=(link,),
        complete=True,
        relationship_drops=(
            RelationshipDrop(
                reason=RelationshipDropReason.UNRESOLVED_REFERENCE,
                unavailable_reason=RelationshipUnavailableReason.REFERENCE_NOT_OBSERVED,
            ),
            RelationshipDrop(reason=RelationshipDropReason.UNVERIFIED_METADATA),
        ),
    )

    coverage = compute_relationship_coverage(observation)

    assert coverage == InventoryRelationshipCoverage(
        materialized=1,
        reviewed_unavailable=1,
        unclassified=1,
        total_candidates=3,
        complete=False,
    )


def test_compute_relationship_coverage_is_complete_only_without_unclassified_drops() -> None:
    link = LinkRecord(
        from_id="vm-1",
        from_type="compute.vm",
        link_type="depends_on",
        to_id="vm-2",
        to_type="compute.vm",
    )
    observation = PromotedInventoryObservation(
        generation="attempt-1",
        resources=(),
        links=(link,),
        complete=True,
        relationship_drops=(
            RelationshipDrop(
                reason=RelationshipDropReason.UNRESOLVED_REFERENCE,
                unavailable_reason=RelationshipUnavailableReason.REFERENCE_NOT_OBSERVED,
            ),
        ),
    )

    assert compute_relationship_coverage(observation) == InventoryRelationshipCoverage(
        materialized=1,
        reviewed_unavailable=1,
        unclassified=0,
        total_candidates=2,
        complete=True,
    )


def test_compute_relationship_coverage_stays_incomplete_for_a_truncated_generation() -> None:
    observation = PromotedInventoryObservation(
        generation="attempt-1",
        resources=(),
        links=(),
        complete=False,
    )

    assert compute_relationship_coverage(observation).complete is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "materialized": -1,
            "reviewed_unavailable": 0,
            "unclassified": 0,
            "total_candidates": -1,
            "complete": False,
        },
        {
            "materialized": True,
            "reviewed_unavailable": 0,
            "unclassified": 0,
            "total_candidates": 1,
            "complete": False,
        },
        {
            "materialized": 1,
            "reviewed_unavailable": 0,
            "unclassified": 0,
            "total_candidates": 2,
            "complete": False,
        },
        {
            "materialized": 1,
            "reviewed_unavailable": 0,
            "unclassified": 1,
            "total_candidates": 2,
            "complete": True,
        },
    ],
)
def test_relationship_coverage_rejects_malformed_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="inventory relationship coverage"):
        InventoryRelationshipCoverage(**kwargs)


async def test_promotion_observer_is_not_called_for_a_failed_stream() -> None:
    store = _Store()
    observed: list[PromotedInventoryObservation] = []

    async def _record(observation: PromotedInventoryObservation) -> None:
        observed.append(observation)

    with pytest.raises(InventorySourcesExhaustedError):
        await InventorySyncCoordinator(store=store, promotion_observer=_record).run(
            [_source("arg", _Inventory([InventoryBatch()]))]
        )
    assert observed == []


async def test_observer_failure_leaves_the_promotion_intact() -> None:
    store = _Store()

    async def _explode(observation: PromotedInventoryObservation) -> None:
        raise RuntimeError("derived projection unavailable")

    result = await InventorySyncCoordinator(store=store, promotion_observer=_explode).run(
        [_source("arg", _Inventory([InventoryBatch(final=True)]))]
    )
    assert result.source == "arg"
    assert store.promoted == ["attempt-1"]
    assert isinstance(InventoryStreamError("example"), RuntimeError)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (httpx.ConnectTimeout("blocked"), InventoryFailureCode.NETWORK_BLOCKED),
        (RuntimeError("ARG returned HTTP 403"), InventoryFailureCode.FORBIDDEN),
        (RuntimeError("ARG returned HTTP 429"), InventoryFailureCode.THROTTLED),
        (RuntimeError("pagination cap exceeded"), InventoryFailureCode.PARTIAL),
    ],
)
async def test_failure_classification_drives_fallback(
    error: Exception, code: InventoryFailureCode
) -> None:
    store = _Store()
    result = await InventorySyncCoordinator(store=store).run(
        [
            _source("arg", _Inventory(error=error)),
            _source("arm", _Inventory([InventoryBatch(final=True)])),
        ]
    )
    assert result.failures[0].code is code
