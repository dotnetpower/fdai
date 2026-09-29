#!/usr/bin/env python3
"""Refresh local inventory from Azure Resource Graph without synthetic data."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml
from fdai.delivery.azure.arg_query import (
    AzureArgQueryFactory,
    AzureArgQueryFactoryConfig,
)
from fdai.delivery.azure.arm_inventory import (
    AzureArmInventoryFactory,
    AzureArmInventoryFactoryConfig,
)
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.inventory import AzureInventoryConfig, AzureResourceGraphInventory
from fdai.delivery.inventory_job_config import InventoryJobConfig
from fdai.delivery.inventory_operator_graph import write_operator_inventory_graph
from fdai.delivery.inventory_sync import (
    InventoryPromotionEnricher,
    InventorySyncCoordinator,
    PromotedInventoryObservation,
)
from fdai.delivery.inventory_sync_cli import (
    build_inventory_promotion_enricher,
)
from fdai.delivery.operational_activity import (
    EventBusOperationalActivityPublisher,
    ObservedInventorySnapshotStore,
    ontology_projection_activity,
)
from fdai.delivery.persistence import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
    PostgresStateStore,
    PostgresStateStoreConfig,
)
from fdai.delivery.persistence.postgres_inventory_observation import (
    PostgresInventoryObservationJournal,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    load_provider_relationship_mapping_catalog,
)
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
    resource_type_mapping_digests,
)
from fdai.runtime.inventory_ontology import (
    InventoryOntologyProjectionResult,
    InventoryOntologyProjector,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.inventory_snapshot import (
    InventoryCoverageManifest,
    InventoryObservationKind,
    InventorySource,
    InventorySourcesExhaustedError,
)
from fdai_service_contracts import OperationalActivityStatus, OperationalFreshness

REPO_ROOT = Path(__file__).resolve().parents[3]


def _emit_duration(stage: str, started_at: float) -> None:
    duration_ms = max(0, round((time.monotonic() - started_at) * 1000))
    print(
        f"service=authoritative-inventory stage={stage} event=completed duration_ms={duration_ms}",
        file=sys.stderr,
        flush=True,
    )


class _TimedPromotionEnricher:
    def __init__(self, delegate: InventoryPromotionEnricher) -> None:
        self._delegate = delegate

    async def enrich(
        self,
        observation: PromotedInventoryObservation,
    ) -> PromotedInventoryObservation:
        started_at = time.monotonic()
        try:
            return await self._delegate.enrich(observation)
        finally:
            _emit_duration("enrichment", started_at)


async def refresh() -> InventoryOntologyProjectionResult:
    """Promote one complete ARG snapshot and its derived ontology subgraph."""
    refresh_started_at = time.monotonic()
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
    if not dsn:
        raise RuntimeError("FDAI_STATE_STORE_DSN MUST be configured")
    if not subscription_id:
        raise RuntimeError("AZURE_SUBSCRIPTION_ID MUST be configured")
    inventory_config = InventoryJobConfig.from_env(
        {
            **os.environ,
            "FDAI_INVENTORY_DSN": dsn,
            "FDAI_INVENTORY_SCOPES": subscription_id,
            "FDAI_INVENTORY_RECOVERY_DELTA": "0",
            "FDAI_INVENTORY_RESOURCE_CHANGE_FEED": "0",
        }
    )

    registry = PackageResourceSchemaRegistry()
    catalog_root = REPO_ROOT / "rule-catalog"
    ontology = load_ontology_catalog(
        catalog_root,
        schema_registry=registry,
        probes_root=catalog_root / "probes",
    )
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (catalog_root / "vocabulary/resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    query_types = tuple(item.id for item in resource_types if item.azure_arm_type is not None)
    relationship_catalog = load_provider_relationship_mapping_catalog(
        catalog_root / "vocabulary/provider-relationship-mappings"
    )

    ontology_store = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(dsn=dsn),
        object_types=ontology.object_types,
        link_types=ontology.link_types,
    )
    await ontology_store.sync_catalog()
    state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    snapshot_config = PostgresInventorySnapshotStoreConfig(dsn=dsn)
    observation_journal = PostgresInventoryObservationJournal(config=snapshot_config)
    projector = InventoryOntologyProjector(
        store=ontology_store,
        status_store=state_store,
        ontology_release_digest=ontology.build_release().digest,
        resource_type_mappings=resource_type_mapping_digests(resource_types),
        observation_journal=observation_journal,
    )
    snapshot_store = PostgresInventorySnapshotStore(config=snapshot_config)
    projected: InventoryOntologyProjectionResult | None = None
    evidence_counts: dict[str, int] = {}
    event_bus = EventHubsKafkaBus(
        identity=None,
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip(),
            security_protocol="PLAINTEXT",
            client_id="fdai-local-inventory-refresh",
        ),
    )
    activity_publisher = EventBusOperationalActivityPublisher(
        event_bus=event_bus,
        topic=os.environ.get("FDAI_STAGE_TOPIC", "fdai.pipeline.stages").strip(),
    )
    observed_store = ObservedInventorySnapshotStore(
        store=snapshot_store,
        publisher=activity_publisher,
    )

    async def project(observation: PromotedInventoryObservation) -> None:
        nonlocal projected
        projection_started_at = time.monotonic()
        evidence_counts[observation.generation] = len(observation.resources) + len(
            observation.links
        )
        journal_started_at = time.monotonic()
        journal_append = await observation_journal.append_promoted_snapshot(observation)
        _emit_duration("journal-append", journal_started_at)
        active_scope_watermark = journal_append.active_scope_projection_watermark
        graph_started_at = time.monotonic()
        projected = await projector.apply(
            observation,
            journal_high_watermark=journal_append.journal_high_watermark,
            projection_high_watermark=journal_append.projection_high_watermark,
            active_scope_projection_watermark=active_scope_watermark,
            active_scope_refs=journal_append.active_scope_refs,
        )
        _emit_duration("graph-projection", graph_started_at)
        available = projected.status.value == "available"
        activity_started_at = time.monotonic()
        await activity_publisher.publish(
            ontology_projection_activity(
                generation=observation.generation,
                status=(
                    OperationalActivityStatus.COMPLETED
                    if available
                    else OperationalActivityStatus.DEGRADED
                ),
                freshness=(
                    OperationalFreshness.FRESH if available else OperationalFreshness.UNAVAILABLE
                ),
                evidence_count=projected.object_count + projected.link_count,
                reason_codes=projected.dropped_reasons,
            )
        )
        _emit_duration("projection-activity", activity_started_at)
        _emit_duration("ontology-projection", projection_started_at)

    try:
        async with AsyncExitStack() as stack:
            client = await stack.enter_async_context(httpx.AsyncClient())
            identity = AsyncAzureCliWorkloadIdentity.from_env()
            binding_started_at = time.monotonic()
            effective_enricher = await build_inventory_promotion_enricher(
                config=inventory_config,
                identity=identity,
                http_client=client,
                stack=stack,
                relationship_catalog=relationship_catalog,
                previous_state_reader=snapshot_store,
            )
            _emit_duration("enricher-binding", binding_started_at)
            query_factory = AzureArgQueryFactory(
                identity=identity,
                resource_types=resource_types,
                http_client=client,
                config=AzureArgQueryFactoryConfig(subscription_scopes=(subscription_id,)),
            )
            query = AzureArmInventoryFactory(
                identity=identity,
                resource_types=resource_types,
                http_client=client,
                config=AzureArmInventoryFactoryConfig(
                    subscription_scopes=(subscription_id,),
                ),
            ).build_child_overlay_query_fn(query_factory.build_query_fn())
            inventory = AzureResourceGraphInventory(
                config=AzureInventoryConfig(
                    resource_types=query_types,
                    subscription_scopes=(subscription_id,),
                ),
                query=query,
                scope_coverage=query_factory.build_scope_coverage_fn(),
                unmapped_resources=query_factory.build_unmapped_resource_query_fn(),
                generation_relationships=query_factory.build_generation_relationship_fn(),
            )
            source = InventorySource(
                name="azure-resource-graph",
                inventory=inventory,
                manifest=InventoryCoverageManifest(
                    source="azure-resource-graph",
                    scopes=(subscription_id,),
                    resource_types=query_types,
                    observation_kind=InventoryObservationKind.OBSERVED,
                    started_at=datetime.now(UTC),
                    metadata={
                        "coverage_scope": "full_provider_scope",
                        "credential": "azure-cli",
                        "synthetic": False,
                        "link_types": (
                            "contains",
                            "attached_to",
                            "depends_on",
                            "peered_with",
                            "routes_to",
                        ),
                    },
                ),
            )
            collection_started_at = time.monotonic()
            result = await InventorySyncCoordinator(
                store=observed_store,
                promotion_observer=project,
                promotion_enricher=_TimedPromotionEnricher(effective_enricher),
                relationship_mapping_catalog=relationship_catalog,
            ).run((source,))
            _emit_duration("collection-promotion", collection_started_at)
            active_snapshot_id = await snapshot_store.active_snapshot_id()
            if active_snapshot_id is None:
                raise RuntimeError("inventory promotion completed without a durable active pointer")
            await observed_store.publish_terminal(
                attempt_id=result.attempt_id,
                source=result.source,
                active=active_snapshot_id == result.attempt_id,
                evidence_count=evidence_counts.get(result.attempt_id, 0),
            )
    finally:
        await event_bus.close()

    if projected is None:
        raise RuntimeError("inventory snapshot promoted without ontology projection evidence")
    operator_projection_started_at = time.monotonic()
    await write_operator_inventory_graph(dsn=dsn, state_store=state_store)
    _emit_duration("operator-projection", operator_projection_started_at)
    _emit_duration("total", refresh_started_at)
    return projected


def main() -> int:
    """Run one authoritative local refresh and print only aggregate evidence."""
    try:
        result = asyncio.run(refresh())
    except InventorySourcesExhaustedError as exc:
        codes = ",".join(sorted({failure.code.value for failure in exc.failures}))
        print(f"authoritative local inventory unavailable: {codes or 'source_unavailable'}")
        return 0
    print(
        "authoritative local inventory refreshed: "
        f"resources={result.object_count} links={result.link_count} complete={result.complete}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
