"""One-shot inventory reconciliation entry point for scheduled jobs."""

from __future__ import annotations

import asyncio
import logging
import os
import ssl
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import yaml
from fdai_service_contracts import OperationalActivityStatus, OperationalFreshness

from fdai.delivery.azure.activity_log import AzureActivityLogFactory, AzureActivityLogFactoryConfig
from fdai.delivery.azure.arg_query import AzureArgQueryFactory, AzureArgQueryFactoryConfig
from fdai.delivery.azure.arm_inventory import (
    AzureArmInventoryFactory,
    AzureArmInventoryFactoryConfig,
)
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.inventory import AzureInventoryConfig, AzureResourceGraphInventory
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.inventory_collection_health_reporting import (
    build_scheduled_collection_health_projection,
)
from fdai.delivery.inventory_delta import forward_inventory_delta
from fdai.delivery.inventory_job_config import (
    InventoryJobConfig,
    read_bool_env,
    verify_declarative_sha256,
)
from fdai.delivery.inventory_scheduler import CollectionScheduleDecision
from fdai.delivery.inventory_sync import (
    InventoryPromotionEnricher,
    InventoryPromotionObserver,
    InventorySyncCoordinator,
    PromotedInventoryObservation,
)
from fdai.delivery.inventory_topology_history import InventoryTopologyHistoryPublisher
from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiAuth,
    KubernetesApiInventoryConfig,
    KubernetesApiInventorySource,
    ServiceAccountTokenAuth,
    WorkloadIdentityKubernetesAuth,
)
from fdai.delivery.kubernetes_inventory import (
    KubernetesInventoryEnricher,
    SequentialInventoryPromotionEnricher,
    UnavailableKubernetesInventoryEnricher,
)
from fdai.delivery.kubernetes_lifecycle_collection import KubernetesLifecycleCollector
from fdai.delivery.operational_activity import (
    EventBusOperationalActivityPublisher,
    ObservedInventorySnapshotStore,
    ontology_projection_activity,
)
from fdai.delivery.operational_history_policy import (
    load_operational_history_retention_policies,
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
from fdai.delivery.persistence.postgres_inventory_reconciliation import (
    InventoryReconciliationHealthState,
    PostgresInventoryReconciliationGate,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_kubernetes_lifecycle import (
    PostgresKubernetesLifecycleConfig,
    PostgresKubernetesLifecycleStore,
)
from fdai.delivery.persistence.postgres_operational_history import (
    PostgresOperationalHistoryConfig,
    PostgresOperationalHistoryStore,
)
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)
from fdai.delivery.persistence.postgres_state_transitions import (
    PostgresStateTransitionStore,
    PostgresStateTransitionStoreConfig,
)
from fdai.delivery.persistence.postgres_topology_history import (
    PostgresTopologyHistoryStore,
    PostgresTopologyHistoryStoreConfig,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.delivery.runtime_call_inventory import UnavailableRuntimeCallInventoryEnricher
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    ProviderRelationshipMappingCatalog,
    load_provider_relationship_mapping_catalog,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
    resource_type_mapping_digests,
)
from fdai.runtime.inventory_ontology import (
    InventoryOntologyProjectionStatus,
    InventoryOntologyProjector,
)
from fdai.runtime.venue import (
    bus_security_protocol,
    resolve_execution_venue,
    uses_developer_identity,
    uses_workload_identity,
)
from fdai.shared.config.loader import load_config_from_env
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.declarative_inventory import (
    DeclarativeInventory,
    DeclarativeInventoryConfig,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.inventory import Inventory, LinkRecord, ResourceRecord
from fdai.shared.providers.inventory_snapshot import (
    InventoryCoverageManifest,
    InventoryObservationKind,
    InventorySource,
    InventorySourcesExhaustedError,
)
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.workload_identity import WorkloadIdentity

_REPO_ROOT = repo_asset_root()
_LOGGER = logging.getLogger(__name__)
_COLLECTION_HEALTH_STATE_KEY = "inventory-collection-health"


@dataclass(frozen=True, slots=True)
class InventoryJobResult:
    """Report one promoted attempt after rereading the durable active pointer."""

    attempt_id: str
    source: str
    active: bool


def _load_resource_type_registry() -> ResourceTypeRegistry:
    vocabulary_path = _REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
    return load_resource_type_registry_from_mapping(
        yaml.safe_load(vocabulary_path.read_text(encoding="utf-8"))
    )


def _load_relationship_mapping_catalog() -> ProviderRelationshipMappingCatalog:
    return load_provider_relationship_mapping_catalog(
        _REPO_ROOT / "rule-catalog" / "vocabulary" / "provider-relationship-mappings"
    )


async def _build_kubernetes_enricher(
    *,
    config: InventoryJobConfig,
    relationship_catalog: ProviderRelationshipMappingCatalog,
    stack: AsyncExitStack,
    identity: WorkloadIdentity | None = None,
) -> InventoryPromotionEnricher:
    if (
        config.kubernetes_api_server is None
        or config.kubernetes_cluster_ref is None
        or config.kubernetes_auth_mode is None
        or (config.kubernetes_ca_path is None and config.kubernetes_ca_pem is None)
    ):
        return UnavailableKubernetesInventoryEnricher()
    try:
        kubernetes_ssl = ssl.create_default_context(
            cafile=(str(config.kubernetes_ca_path) if config.kubernetes_ca_path else None),
            cadata=config.kubernetes_ca_pem,
        )
    except OSError as exc:
        raise RuntimeError("Kubernetes CA bundle is unavailable") from exc
    auth: KubernetesApiAuth
    if config.kubernetes_auth_mode == "workload-identity":
        if identity is None or config.kubernetes_audience is None:
            raise RuntimeError("Kubernetes workload identity is unavailable")
        auth = WorkloadIdentityKubernetesAuth(
            identity=identity,
            audience=config.kubernetes_audience,
        )
    else:
        if config.kubernetes_token_path is None:
            raise RuntimeError("Kubernetes service-account token path is unavailable")
        auth = ServiceAccountTokenAuth(config.kubernetes_token_path)
    kubernetes_client = await stack.enter_async_context(httpx.AsyncClient(verify=kubernetes_ssl))
    return KubernetesInventoryEnricher(
        source=KubernetesApiInventorySource(
            config=KubernetesApiInventoryConfig(
                api_server=config.kubernetes_api_server,
                cluster_ref=config.kubernetes_cluster_ref,
            ),
            auth=auth,
            http_client=kubernetes_client,
        ),
        relationship_mapping_catalog=relationship_catalog,
    )


def _resolve_resource_types(
    config: InventoryJobConfig,
    vocabulary: ResourceTypeRegistry,
) -> tuple[str, ...]:
    resource_types = config.resource_types or tuple(
        item.id for item in vocabulary if item.azure_arm_type is not None
    )
    unknown_types = sorted(set(resource_types) - vocabulary.ids())
    if unknown_types:
        raise ValueError(f"unknown inventory resource types: {', '.join(unknown_types)}")
    if "resource-group" not in resource_types:
        resource_types = ("resource-group", *resource_types)
    return resource_types


def _build_sources(
    *,
    config: InventoryJobConfig,
    vocabulary: ResourceTypeRegistry,
    resource_types: tuple[str, ...],
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    started_at: datetime,
) -> tuple[InventorySource, ...]:
    """Build ordered provider sources without granting any source promotion authority."""
    sources: list[InventorySource] = []
    for source_priority, source_name in enumerate(config.source_order):
        observation_kind = InventoryObservationKind.OBSERVED
        link_types: tuple[str, ...] = (
            "contains",
            "attached_to",
            "depends_on",
            "peered_with",
            "routes_to",
        )
        inventory: Inventory
        if source_name == "arg":
            full_provider_scope = not config.resource_types
            query_factory = AzureArgQueryFactory(
                identity=identity,
                resource_types=vocabulary,
                http_client=http_client,
                config=AzureArgQueryFactoryConfig(
                    subscription_scopes=config.scopes,
                    arg_endpoint=config.management_endpoint,
                    audience=config.management_audience,
                    requests_per_second=config.arg_requests_per_second,
                ),
            )
            query = AzureArmInventoryFactory(
                identity=identity,
                resource_types=vocabulary,
                http_client=http_client,
                config=AzureArmInventoryFactoryConfig(
                    subscription_scopes=config.scopes,
                    arm_endpoint=config.management_endpoint,
                    audience=config.management_audience,
                ),
            ).build_child_overlay_query_fn(query_factory.build_query_fn())
            inventory = AzureResourceGraphInventory(
                config=AzureInventoryConfig(
                    resource_types=resource_types,
                    subscription_scopes=config.scopes,
                ),
                query=query,
                scope_coverage=(
                    query_factory.build_scope_coverage_fn() if full_provider_scope else None
                ),
                unmapped_resources=(
                    query_factory.build_unmapped_resource_query_fn()
                    if full_provider_scope
                    else None
                ),
                generation_relationships=query_factory.build_generation_relationship_fn(),
            )
        elif source_name == "arm":
            link_types = ("contains",)
            query = AzureArmInventoryFactory(
                identity=identity,
                resource_types=vocabulary,
                http_client=http_client,
                config=AzureArmInventoryFactoryConfig(
                    subscription_scopes=config.scopes,
                    arm_endpoint=config.management_endpoint,
                    audience=config.management_audience,
                ),
            ).build_query_fn()
            inventory = AzureResourceGraphInventory(
                config=AzureInventoryConfig(
                    resource_types=resource_types,
                    subscription_scopes=config.scopes,
                ),
                query=query,
            )
        else:
            if config.declarative_path is None or config.declarative_sha256 is None:
                raise ValueError("declarative fallback is missing its signed fixture")
            verify_declarative_sha256(config.declarative_path, config.declarative_sha256)
            inventory = DeclarativeInventory(
                DeclarativeInventoryConfig(
                    fixture_path=config.declarative_path,
                    known_resource_types=frozenset(vocabulary.ids()),
                    known_link_types=frozenset(
                        {"contains", "attached_to", "depends_on", "peered_with", "routes_to"}
                    ),
                )
            )
            observation_kind = InventoryObservationKind.EXPECTED
        sources.append(
            InventorySource(
                name=source_name,
                inventory=inventory,
                manifest=InventoryCoverageManifest(
                    source=source_name,
                    scopes=config.scopes,
                    resource_types=resource_types,
                    observation_kind=observation_kind,
                    started_at=started_at,
                    metadata={
                        "source_priority": source_priority,
                        "link_types": link_types,
                        "coverage_scope": (
                            "full_provider_scope"
                            if source_name == "arg" and not config.resource_types
                            else "requested_resource_types"
                        ),
                    },
                ),
            )
        )
    return tuple(sources)


def _build_ontology_observer(
    config: InventoryJobConfig,
    *,
    vocabulary: ResourceTypeRegistry,
    publisher: EventBusOperationalActivityPublisher,
    evidence_counts: dict[str, int],
) -> InventoryPromotionObserver:
    retention_policies = load_operational_history_retention_policies(os.environ)
    operational_history_store = PostgresOperationalHistoryStore(
        config=PostgresOperationalHistoryConfig(dsn=config.dsn)
    )
    observation_journal = PostgresInventoryObservationJournal(
        config=PostgresInventorySnapshotStoreConfig(dsn=config.dsn)
    )
    projector: InventoryOntologyProjector | None = None
    ontology_store: PostgresOntologyInstanceStore | None = None
    topology_publisher: InventoryTopologyHistoryPublisher | None = None
    if read_bool_env(os.environ, "FDAI_INVENTORY_ONTOLOGY_PROJECTION", True):
        catalog_root = _REPO_ROOT / "rule-catalog"
        catalog = load_ontology_catalog(
            catalog_root,
            schema_registry=PackageResourceSchemaRegistry(),
            probes_root=catalog_root / "probes",
        )
        ontology_store = PostgresOntologyInstanceStore(
            config=PostgresOntologyInstanceStoreConfig(dsn=config.dsn),
            object_types=catalog.object_types,
            link_types=catalog.link_types,
        )
        ontology_release_digest = catalog.build_release().digest
        projector = InventoryOntologyProjector(
            store=ontology_store,
            status_store=PostgresStateStore(config=PostgresStateStoreConfig(dsn=config.dsn)),
            ontology_release_digest=ontology_release_digest,
            resource_type_mappings=resource_type_mapping_digests(vocabulary),
            freshness_ceiling_seconds=config.reconciliation_interval_seconds,
            projection_lock=PostgresAdvisoryResourceLock(
                config=PostgresAdvisoryResourceLockConfig(
                    dsn=config.dsn,
                    lock_timeout_ms=30_000,
                )
            ),
            observation_journal=observation_journal,
        )
        topology_store = PostgresTopologyHistoryStore(
            config=PostgresTopologyHistoryStoreConfig(dsn=config.dsn)
        )
        topology_publisher = InventoryTopologyHistoryPublisher(
            writer=topology_store,
            ontology_release_digest=ontology_release_digest,
            history_reader=topology_store,
            transition_writer=PostgresStateTransitionStore(
                config=PostgresStateTransitionStoreConfig(dsn=config.dsn)
            ),
        )

    async def _observe(observation: PromotedInventoryObservation) -> None:
        evidence_counts[observation.generation] = len(observation.resources) + len(
            observation.links
        )
        if observation.recorded_at is None:
            raise ValueError("promoted inventory observation recorded_at MUST be supplied")
        for policy in retention_policies:
            await operational_history_store.put_retention_policy(
                policy,
                recorded_at=observation.recorded_at,
            )
        journal_append = await observation_journal.append_promoted_snapshot(observation)
        if projector is None or ontology_store is None or topology_publisher is None:
            return
        failures: list[tuple[str, Exception]] = []
        history_available = False
        try:
            history_available = await topology_publisher.publish(observation) is not None
        except Exception as exc:  # noqa: BLE001 - independent derived read model
            failures.append(("topology_history_failed", exc))
        result = None
        try:
            await ontology_store.sync_catalog()
            result = await projector.apply(
                observation,
                journal_high_watermark=journal_append.journal_high_watermark,
                projection_high_watermark=journal_append.projection_high_watermark,
            )
        except Exception as exc:  # noqa: BLE001 - independent derived read model
            failures.append(("projection_failed", exc))
        if failures:
            await publisher.publish(
                ontology_projection_activity(
                    generation=observation.generation,
                    status=OperationalActivityStatus.FAILED,
                    freshness=OperationalFreshness.UNAVAILABLE,
                    evidence_count=evidence_counts[observation.generation],
                    reason_codes=tuple(reason for reason, _ in failures),
                )
            )
            raise failures[0][1]
        if result is None:  # pragma: no cover - guarded by the failure branch
            raise RuntimeError("inventory ontology projection produced no result")
        available = (
            history_available and result.status is InventoryOntologyProjectionStatus.AVAILABLE
        )
        reason_codes = result.dropped_reasons + (
            () if history_available else ("topology_history_unavailable",)
        )
        await publisher.publish(
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
                evidence_count=result.object_count + result.link_count,
                reason_codes=reason_codes,
            )
        )

    return _observe


async def run(
    config: InventoryJobConfig,
    *,
    promotion_enricher: InventoryPromotionEnricher | None = None,
) -> InventoryJobResult:
    """Run ordered source fallback and optional verified pre-promotion enrichment."""
    vocabulary = _load_resource_type_registry()
    relationship_catalog = _load_relationship_mapping_catalog()
    resource_types = _resolve_resource_types(config, vocabulary)
    durable_store = PostgresInventorySnapshotStore(
        config=PostgresInventorySnapshotStoreConfig(
            dsn=config.dsn,
            freshness_budget_seconds=config.freshness_budget_seconds,
        )
    )
    async with AsyncExitStack() as stack:
        client = await stack.enter_async_context(httpx.AsyncClient())
        identity = _workload_identity(http_client=client)
        kubernetes_enricher = await _build_kubernetes_enricher(
            config=config,
            relationship_catalog=relationship_catalog,
            stack=stack,
            identity=identity,
        )
        effective_enricher = SequentialInventoryPromotionEnricher(
            promotion_enricher or UnavailableRuntimeCallInventoryEnricher(),
            kubernetes_enricher,
        )
        event_bus, event_topic = _build_job_event_bus(identity)
        activity_publisher = EventBusOperationalActivityPublisher(event_bus=event_bus)
        observed_store = ObservedInventorySnapshotStore(
            store=durable_store,
            publisher=activity_publisher,
        )
        evidence_counts: dict[str, int] = {}
        try:
            result = await InventorySyncCoordinator(
                store=observed_store,
                promotion_enricher=effective_enricher,
                promotion_observer=_build_ontology_observer(
                    config,
                    vocabulary=vocabulary,
                    publisher=activity_publisher,
                    evidence_counts=evidence_counts,
                ),
                relationship_mapping_catalog=relationship_catalog,
                progress_deadline_seconds=float(config.progress_deadline_seconds),
                attempt_deadline_seconds=float(config.attempt_deadline_seconds),
            ).run(
                _build_sources(
                    config=config,
                    vocabulary=vocabulary,
                    resource_types=resource_types,
                    identity=identity,
                    http_client=client,
                    started_at=datetime.now(tz=UTC),
                )
            )
            active_snapshot_id = await durable_store.active_snapshot_id()
            if active_snapshot_id is None:
                raise RuntimeError("inventory promotion completed without a durable active pointer")
            active = active_snapshot_id == result.attempt_id
            await observed_store.publish_terminal(
                attempt_id=result.attempt_id,
                source=result.source,
                active=active,
                evidence_count=evidence_counts.get(result.attempt_id, 0),
                reason_codes=(
                    ("activity_summary_truncated",)
                    if result.attempt_id not in evidence_counts
                    else ()
                ),
            )
            if config.recovery_delta_enabled:
                await _forward_recovery_deltas(
                    config=config,
                    identity=identity,
                    vocabulary=vocabulary,
                    http_client=client,
                    event_bus=event_bus,
                    topic=event_topic,
                    scope_lock=_recovery_delta_lock(config),
                )
        finally:
            await event_bus.close()
    return InventoryJobResult(
        attempt_id=result.attempt_id,
        source=result.source,
        active=active,
    )


async def run_recovery_delta(config: InventoryJobConfig) -> int:
    """Retry the read-only Activity Log delta independently of full-scan due state."""
    vocabulary = _load_resource_type_registry()
    async with httpx.AsyncClient() as client:
        identity = _workload_identity(http_client=client)
        return await _run_recovery_delta(
            config=config,
            vocabulary=vocabulary,
            identity=identity,
            http_client=client,
        )


async def _run_recovery_delta(
    *,
    config: InventoryJobConfig,
    vocabulary: ResourceTypeRegistry,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
) -> int:
    event_bus, event_topic = _build_job_event_bus(identity)
    try:
        return await _forward_recovery_deltas(
            config=config,
            identity=identity,
            vocabulary=vocabulary,
            http_client=http_client,
            event_bus=event_bus,
            topic=event_topic,
            scope_lock=_recovery_delta_lock(config),
        )
    finally:
        await event_bus.close()


def _build_job_event_bus(
    identity: WorkloadIdentity,
) -> tuple[EventHubsKafkaBus, str]:
    app_config = load_config_from_env()
    venue = resolve_execution_venue()
    return EventHubsKafkaBus(
        identity=identity if uses_workload_identity(venue) else None,
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=app_config.kafka.bootstrap_servers,
            dlq_suffix=app_config.kafka.topic_dlq_suffix,
            security_protocol=bus_security_protocol(venue),
            client_id="fdai-inventory-recovery",
        ),
    ), app_config.kafka.topic_events


def _workload_identity(*, http_client: httpx.AsyncClient) -> WorkloadIdentity:
    if uses_developer_identity(resolve_execution_venue()):
        return AsyncAzureCliWorkloadIdentity.from_env()
    return ManagedIdentityWorkloadIdentity.from_env(http_client=http_client)


async def _forward_recovery_deltas(
    *,
    config: InventoryJobConfig,
    identity: WorkloadIdentity,
    vocabulary: ResourceTypeRegistry,
    http_client: httpx.AsyncClient,
    event_bus: EventBus,
    topic: str,
    scope_lock: ResourceLock,
) -> int:
    """Forward every configured scope and commit each cursor only at its final fence."""
    state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=config.dsn))
    published = 0
    for scope in config.scopes:
        async with scope_lock.acquire(f"inventory-recovery-delta:{scope}"):
            activity_fetch = AzureActivityLogFactory(
                identity=identity,
                resource_types=vocabulary,
                http_client=http_client,
                config=AzureActivityLogFactoryConfig(
                    subscription_scope=scope,
                    arg_endpoint=config.management_endpoint,
                    audience=config.management_audience,
                ),
            ).build_fetch_fn()

            async def _noop_query(
                _resource_type: str,
            ) -> tuple[tuple[ResourceRecord, ...], tuple[LinkRecord, ...]]:
                return (), ()

            delta_inventory = AzureResourceGraphInventory(
                config=AzureInventoryConfig(resource_types=()),
                query=_noop_query,
                delta_fetch=activity_fetch,
            )
            published += await forward_inventory_delta(
                inventory=delta_inventory,
                state_store=state_store,
                event_bus=event_bus,
                topic=topic,
                scope=scope,
            )
    return published


def _recovery_delta_lock(config: InventoryJobConfig) -> ResourceLock:
    return PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(
            dsn=config.dsn,
            lock_timeout_ms=30_000,
        )
    )


async def _load_job_config() -> InventoryJobConfig:
    """Resolve one authoritative settings snapshot for an inventory tick."""

    from fdai.delivery.runtime_settings import runtime_settings_service_from_env

    runtime_values = await runtime_settings_service_from_env(os.environ).effective_values()
    return InventoryJobConfig.from_env(runtime_values=runtime_values)


async def _run_due_once(config: InventoryJobConfig | None = None) -> InventoryJobConfig:
    """Run one tick and return the single settings snapshot it used."""

    if config is None:
        config = await _load_job_config()
    await _collect_kubernetes_lifecycle(config)
    snapshot_config = PostgresInventorySnapshotStoreConfig(
        dsn=config.dsn,
        freshness_budget_seconds=config.freshness_budget_seconds,
    )
    published = await _drain_change_stream(config)
    reconciliation_gate = PostgresInventoryReconciliationGate(
        config=snapshot_config,
        change_min_interval_seconds=config.change_min_interval_seconds,
        source_policy=config.snapshot_policy(config.source_order[0]),
        cursor_scopes=config.scopes,
    )
    due = await reconciliation_gate(config.reconciliation_interval_seconds)
    await _publish_collection_health(
        config,
        health_state=reconciliation_gate.last_health_state,
        decision=reconciliation_gate.last_decision,
    )
    if not due:
        _LOGGER.info(
            "inventory_reconciliation_not_due",
            extra={
                "interval_seconds": config.reconciliation_interval_seconds,
                "change_records_published": published if published is not None else 0,
                "change_stream_available": published is not None,
            },
        )
        print(
            "inventory reconciliation not due; "
            + (
                f"change records published {published}"
                if published is not None
                else "change stream unavailable"
            ),
            flush=True,
        )
        return config
    result = await run(config)
    if result.active:
        print(f"inventory snapshot promoted from {result.source}", flush=True)
    else:
        print(
            f"inventory snapshot from {result.source} superseded by a newer attempt",
            flush=True,
        )
    return config


async def _collect_kubernetes_lifecycle(config: InventoryJobConfig) -> int | None:
    """Collect one leased watch window independently of inventory snapshot due state."""

    if (
        config.kubernetes_api_server is None
        or config.kubernetes_cluster_ref is None
        or config.kubernetes_auth_mode is None
        or (config.kubernetes_ca_path is None and config.kubernetes_ca_pem is None)
    ):
        return 0
    now = datetime.now(UTC)
    holder = f"inventory-lifecycle:{uuid4()}"
    store = PostgresKubernetesLifecycleStore(
        config=PostgresKubernetesLifecycleConfig(dsn=config.dsn)
    )
    try:
        cursor = await store.acquire(
            cluster_ref=config.kubernetes_cluster_ref,
            holder=holder,
            now=now,
            lease_until=now + timedelta(seconds=45),
        )
        if cursor is None:
            return 0
        kubernetes_ssl = ssl.create_default_context(
            cafile=str(config.kubernetes_ca_path) if config.kubernetes_ca_path else None,
            cadata=config.kubernetes_ca_pem,
        )
        async with httpx.AsyncClient() as identity_client:
            identity = _workload_identity(http_client=identity_client)
            auth: KubernetesApiAuth
            if config.kubernetes_auth_mode == "workload-identity":
                if config.kubernetes_audience is None:
                    raise RuntimeError("Kubernetes lifecycle workload audience is unavailable")
                auth = WorkloadIdentityKubernetesAuth(
                    identity=identity,
                    audience=config.kubernetes_audience,
                )
            else:
                if config.kubernetes_token_path is None:
                    raise RuntimeError("Kubernetes lifecycle service-account token is unavailable")
                auth = ServiceAccountTokenAuth(config.kubernetes_token_path)
            async with httpx.AsyncClient(verify=kubernetes_ssl) as kubernetes_client:
                batch = await KubernetesLifecycleCollector(
                    api_server=config.kubernetes_api_server,
                    cluster_ref=config.kubernetes_cluster_ref,
                    auth=auth,
                    http_client=kubernetes_client,
                ).collect(cursor)
        if not await store.append(batch, holder=holder, now=datetime.now(UTC)):
            _LOGGER.warning(
                "kubernetes_lifecycle_cursor_contended",
                extra={"reason": "lease_or_sequence_changed"},
            )
            return None
        if batch.limitation is not None:
            _LOGGER.warning(
                "kubernetes_lifecycle_collection_incomplete",
                extra={"reason": batch.limitation},
            )
        return len(batch.observations)
    except Exception as exc:  # noqa: BLE001 - independent read-only evidence source
        _LOGGER.warning(
            "kubernetes_lifecycle_collection_failed",
            extra={"reason": type(exc).__name__},
        )
        return None


async def _publish_collection_health(
    config: InventoryJobConfig,
    *,
    health_state: InventoryReconciliationHealthState | None,
    decision: CollectionScheduleDecision | None,
) -> None:
    """Persist one sanitized aggregate projection for principal-gated reads."""

    projection = build_scheduled_collection_health_projection(
        config,
        health_state=health_state,
        decision=decision,
    )
    if projection is None:
        return
    await PostgresStateStore(config=PostgresStateStoreConfig(dsn=config.dsn)).write_state(
        _COLLECTION_HEALTH_STATE_KEY, projection
    )


async def _drain_change_stream(config: InventoryJobConfig) -> int | None:
    """Drain the read-only change accelerator without stopping completeness scans."""

    if not config.recovery_delta_enabled:
        return 0
    try:
        return await run_recovery_delta(config)
    except Exception as exc:  # noqa: BLE001 - read-only accelerator degrades independently
        _LOGGER.warning(
            "inventory_change_stream_unavailable",
            extra={"reason": type(exc).__name__},
        )
        return None


async def _main(argv: list[str]) -> None:
    loop = argv == ["--loop"]
    if argv and not loop:
        raise ValueError("inventory reconciliation accepts only --loop")
    while True:
        config = await _load_job_config()
        try:
            await _run_due_once(config)
        except InventorySourcesExhaustedError as exc:
            if not loop:
                raise
            _LOGGER.warning(
                "inventory_reconciliation_loop_tick_failed",
                extra={
                    "failure_codes": tuple(failure.code.value for failure in exc.failures),
                },
            )
            print("inventory reconciliation failed; retry scheduled", flush=True)
        if not loop:
            return
        await asyncio.sleep(config.loop_seconds)


def main() -> None:
    """Run one due-checked reconciliation under the job process identity."""
    asyncio.run(_main(sys.argv[1:]))


if __name__ == "__main__":
    main()


__all__ = ["InventoryJobConfig", "InventoryJobResult", "run", "run_recovery_delta"]
