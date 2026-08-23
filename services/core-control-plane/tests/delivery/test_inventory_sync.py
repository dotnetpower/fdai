"""Fail-closed inventory synchronization and fallback tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fdai.delivery.inventory_sync import (
    InventoryStreamError,
    InventorySyncCoordinator,
    PromotedInventoryObservation,
)
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    load_provider_relationship_mapping_catalog,
)
from fdai.shared.providers.inventory import (
    InventoryBatch,
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


async def test_promotion_observer_receives_verified_kubernetes_relationships() -> None:
    store = _Store()
    observed: list[PromotedInventoryObservation] = []

    async def _record(observation: PromotedInventoryObservation) -> None:
        observed.append(observation)

    cluster_ref = "kubernetes.cluster:example"
    resources = (
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
