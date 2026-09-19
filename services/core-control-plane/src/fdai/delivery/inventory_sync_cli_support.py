"""Support routines for the inventory reconciliation CLI entry point."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx

from fdai.delivery.azure.arg_query import AzureArgQueryFactory, AzureArgQueryFactoryConfig
from fdai.delivery.azure.arg_resource_changes import (
    AzureResourceChangeFeed,
    AzureResourceChangeFeedConfig,
    forward_arg_resource_changes,
)
from fdai.delivery.azure.arm_inventory import (
    AzureArmInventoryFactory,
    AzureArmInventoryFactoryConfig,
)
from fdai.delivery.azure.inventory import AzureInventoryConfig, AzureResourceGraphInventory
from fdai.delivery.azure.metrics_api import AzureMonitorMetricsConfig, AzureMonitorMetricsProvider
from fdai.delivery.azure.metrics_api_queries import azure_metrics_api_queries
from fdai.delivery.azure.model_serving_inventory import (
    MODEL_SERVING_METRIC_NAME,
    AzureModelServingInventoryConfig,
    AzureModelServingInventoryEnricher,
)
from fdai.delivery.azure.resource_health_inventory import (
    AzureResourceHealthInventoryConfig,
    AzureResourceHealthInventoryEnricher,
)
from fdai.delivery.azure.static_web_app_inventory import (
    AzureStaticWebAppInventoryConfig,
    AzureStaticWebAppInventoryEnricher,
)
from fdai.delivery.inventory_collection import collection_configuration_digest
from fdai.delivery.inventory_job_config import InventoryJobConfig, verify_declarative_sha256
from fdai.delivery.inventory_progress import InventoryProgressRecorder
from fdai.delivery.inventory_sync import InventoryPromotionEnricher, PromotedInventoryObservation
from fdai.delivery.inventory_sync_cli_models import InventoryOntologyProjectionIncompleteError
from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiAuth,
    ServiceAccountTokenAuth,
    WorkloadIdentityKubernetesAuth,
)
from fdai.delivery.kubernetes_cluster_binding import KubernetesClusterBinding
from fdai.delivery.kubernetes_lifecycle_collection import KubernetesLifecycleCollector
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_inventory_snapshot import PostgresInventorySnapshotStore
from fdai.delivery.persistence.postgres_kubernetes_lifecycle import (
    PostgresKubernetesLifecycleConfig,
    PostgresKubernetesLifecycleStore,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    resource_type_mapping_digests,
)
from fdai.shared.providers.declarative_inventory import (
    DeclarativeInventory,
    DeclarativeInventoryConfig,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.inventory import UNCLASSIFIED_RESOURCE_TYPE, Inventory
from fdai.shared.providers.inventory_snapshot import (
    InventoryCoverageManifest,
    InventoryObservationKind,
    InventorySource,
)
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

_ResourceChangeForwarder = Callable[..., Awaitable[int]]
_WorkloadIdentityFactory = Callable[..., WorkloadIdentity]


async def recover_ontology_projection(
    *,
    load_pending: Callable[[], Awaitable[PromotedInventoryObservation | None]],
    observe: Callable[[PromotedInventoryObservation], Awaitable[None]],
    status_store: StateStore | None,
    release_digest: str,
    timeout_seconds: float = 60,
    allow_release_mismatch_collection: bool = False,
) -> None:
    """Replay one pending generation under the caller's lock and verify durable completion.

    Incomplete source evidence permits a fresh collection without claiming recovery. A release
    mismatch does the same only for an explicit operator-requested reconciliation; automatic
    recovery remains blocked. Other failures and deadline expiry propagate before collection.
    """
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 180:
        raise ValueError("inventory recovery deadline must be finite and at most 180 seconds")
    logger = logging.getLogger(__name__)
    async with asyncio.timeout(timeout_seconds):
        pending = await load_pending()
        if pending is None:
            return
        logger.info("inventory_projection_recovery_started")
        try:
            if status_store is not None:
                previous = await status_store.read_state("inventory-ontology:manifest")
                if (
                    previous is not None
                    and previous.get("ontology_release_digest") != release_digest
                ):
                    if allow_release_mismatch_collection:
                        logger.warning("inventory_projection_recovery_requires_fresh_collection")
                        return
                    raise RuntimeError(
                        "inventory projection recovery requires deployment alignment"
                    )
            await observe(pending)
            if status_store is None:
                logger.info("inventory_projection_recovery_projection_disabled")
                return
            manifest = await status_store.read_state("inventory-ontology:manifest")
            if (
                manifest is None
                or manifest.get("complete") is not True
                or manifest.get("generation") != pending.generation
                or manifest.get("ontology_release_digest") != release_digest
                or re.fullmatch(r"sha256:[a-f0-9]{64}", str(manifest.get("manifest_digest", "")))
                is None
                or await load_pending() is not None
            ):
                raise RuntimeError("inventory projection recovery readback did not converge")
        except InventoryOntologyProjectionIncompleteError:
            logger.warning("inventory_projection_recovery_source_incomplete")
            return
        except (Exception, asyncio.CancelledError):
            logger.warning("inventory_projection_recovery_failed")
            raise
        logger.info("inventory_projection_recovery_verified")


async def try_recovery_delta_operation(
    operation: Callable[[], Awaitable[int]],
    *,
    logger: logging.Logger,
) -> int | None:
    """Degrade one read-only Activity Log accelerator attempt independently."""

    try:
        return await operation()
    except Exception as exc:  # noqa: BLE001 - read-only accelerator degrades independently
        logger.warning(
            "inventory_change_stream_unavailable",
            extra={"reason": type(exc).__name__},
        )
        return None


def resolve_resource_types(
    config: InventoryJobConfig,
    vocabulary: ResourceTypeRegistry,
) -> tuple[str, ...]:
    """Validate the requested source types against the reviewed registry."""

    resource_types = config.resource_types or tuple(
        item.id for item in vocabulary if item.azure_arm_type is not None
    )
    unknown_types = sorted(set(resource_types) - vocabulary.ids())
    if unknown_types:
        raise ValueError(f"unknown inventory resource types: {', '.join(unknown_types)}")
    if "resource-group" not in resource_types:
        resource_types = ("resource-group", *resource_types)
    return resource_types


def _progress_source_observer(
    recorder: InventoryProgressRecorder | None,
    *,
    provider_types: int,
    initial_pages: int,
) -> Callable[[], Awaitable[object]] | None:
    if recorder is None:
        return None

    async def _observe() -> object:
        await recorder.begin_source(
            provider_types=provider_types,
            initial_pages=initial_pages,
        )
        return None

    return _observe


def build_sources(
    *,
    config: InventoryJobConfig,
    vocabulary: ResourceTypeRegistry,
    resource_types: tuple[str, ...],
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    started_at: datetime,
    progress_recorder: InventoryProgressRecorder | None = None,
) -> tuple[InventorySource, ...]:
    """Build ordered provider sources without granting promotion authority."""

    sources: list[InventorySource] = []
    for source_priority, source_name in enumerate(config.source_order):
        source_policy = config.snapshot_policy(source_name)
        collection_configuration = {
            "schema_version": "1.0.0",
            "source": source_name,
            "policy": asdict(source_policy),
            "management_endpoint": config.management_endpoint,
            "management_audience": config.management_audience,
            "arg_requests_per_second": config.arg_requests_per_second,
            "resource_type_mappings": dict(resource_type_mapping_digests(vocabulary)),
            "declarative_sha256": config.declarative_sha256
            if source_name == "declarative"
            else None,
        }
        configuration_digest = collection_configuration_digest(collection_configuration)
        arg_query_contract_digest: str | None = None
        concurrency = min(
            source_policy.global_concurrency_limit,
            source_policy.scope_concurrency_limit,
            source_policy.resource_type_concurrency_limit,
            source_policy.endpoint_concurrency_limit,
        )
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
                    max_pages=source_policy.max_cursor_pages,
                ),
                page_observer=(
                    None
                    if progress_recorder is None
                    else lambda _rows, has_more: progress_recorder.page_collected(has_more=has_more)
                ),
            )
            arg_query_contract_digest = query_factory.collection_contract_digest
            query = AzureArmInventoryFactory(
                identity=identity,
                resource_types=vocabulary,
                http_client=http_client,
                config=AzureArmInventoryFactoryConfig(
                    subscription_scopes=config.scopes,
                    arm_endpoint=config.management_endpoint,
                    audience=config.management_audience,
                    max_pages=source_policy.max_cursor_pages,
                    max_records=source_policy.max_objects,
                    max_total_response_bytes=source_policy.max_bytes_per_window,
                ),
            ).build_child_overlay_query_fn(query_factory.build_query_fn())
            inventory = AzureResourceGraphInventory(
                config=AzureInventoryConfig(
                    resource_types=resource_types,
                    subscription_scopes=config.scopes,
                    max_concurrent_queries=concurrency,
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
                shard_observer=(
                    None
                    if progress_recorder is None
                    else lambda resources, links, unmapped, gaps: (
                        progress_recorder.provider_type_completed(
                            resources=resources,
                            links=links,
                            unmapped_objects=unmapped,
                            coverage_gaps=gaps,
                        )
                    )
                ),
                source_observer=_progress_source_observer(
                    progress_recorder,
                    provider_types=len(resource_types) + (1 if full_provider_scope else 0),
                    initial_pages=len(resource_types) + (2 if full_provider_scope else 0),
                ),
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
                    max_pages=source_policy.max_cursor_pages,
                    max_records=source_policy.max_objects,
                    max_total_response_bytes=source_policy.max_bytes_per_window,
                ),
            ).build_query_fn()
            inventory = AzureResourceGraphInventory(
                config=AzureInventoryConfig(
                    resource_types=resource_types,
                    subscription_scopes=config.scopes,
                    max_concurrent_queries=concurrency,
                ),
                query=query,
                shard_observer=(
                    None
                    if progress_recorder is None
                    else lambda resources, links, unmapped, gaps: (
                        progress_recorder.provider_type_completed(
                            resources=resources,
                            links=links,
                            unmapped_objects=unmapped,
                            coverage_gaps=gaps,
                        )
                    )
                ),
                source_observer=_progress_source_observer(
                    progress_recorder,
                    provider_types=len(resource_types),
                    initial_pages=0,
                ),
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
        manifest_resource_types = (
            (*resource_types, UNCLASSIFIED_RESOURCE_TYPE)
            if source_name == "arg"
            and not config.resource_types
            and UNCLASSIFIED_RESOURCE_TYPE not in resource_types
            else resource_types
        )
        sources.append(
            InventorySource(
                name=source_name,
                inventory=inventory,
                manifest=InventoryCoverageManifest(
                    source=source_name,
                    scopes=config.scopes,
                    resource_types=manifest_resource_types,
                    observation_kind=observation_kind,
                    started_at=started_at,
                    metadata={
                        "collection_configuration_digest": configuration_digest,
                        "arg_query_contract_digest": arg_query_contract_digest,
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


def build_azure_inventory_enrichers(
    *,
    config: InventoryJobConfig,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    previous_state_reader: PostgresInventorySnapshotStore,
) -> tuple[InventoryPromotionEnricher, ...]:
    """Build the ordered Azure-owned enrichers for one full inventory refresh."""

    serving_lookback_seconds = min(config.reconciliation_interval_seconds, 21_600)
    serving_config = AzureModelServingInventoryConfig(
        lookback_seconds=serving_lookback_seconds,
        freshness_ceiling_seconds=config.reconciliation_interval_seconds,
        max_points_per_target=(serving_lookback_seconds + 59) // 60 + 1,
    )
    return (
        AzureResourceHealthInventoryEnricher(
            identity=identity,
            http_client=http_client,
            config=AzureResourceHealthInventoryConfig(
                subscription_ids=config.scopes,
                endpoint=config.management_endpoint,
                audience=config.management_audience,
                freshness_ceiling_seconds=config.reconciliation_interval_seconds,
            ),
            previous_state_reader=previous_state_reader,
        ),
        AzureModelServingInventoryEnricher(
            provider=AzureMonitorMetricsProvider(
                config=AzureMonitorMetricsConfig(
                    templates={
                        MODEL_SERVING_METRIC_NAME: azure_metrics_api_queries()[
                            MODEL_SERVING_METRIC_NAME
                        ]
                    },
                    endpoint=config.management_endpoint,
                    audience=config.management_audience,
                    timeout_seconds=serving_config.per_request_timeout_seconds,
                ),
                identity=identity,
                http_client=http_client,
            ),
            config=serving_config,
            previous_state_reader=previous_state_reader,
        ),
        AzureStaticWebAppInventoryEnricher(
            identity=identity,
            http_client=http_client,
            config=AzureStaticWebAppInventoryConfig(
                subscription_ids=config.scopes,
                endpoint=config.management_endpoint,
                audience=config.management_audience,
                freshness_ceiling_seconds=config.reconciliation_interval_seconds,
            ),
            previous_state_reader=previous_state_reader,
        ),
    )


async def forward_resource_changes(
    *,
    config: InventoryJobConfig,
    identity: WorkloadIdentity,
    vocabulary: ResourceTypeRegistry,
    http_client: httpx.AsyncClient,
    event_bus: EventBus,
    topic: str,
    scope_lock: ResourceLock,
    forward_arg_resource_changes_fn: _ResourceChangeForwarder = forward_arg_resource_changes,
) -> int:
    """Forward one bounded resourcechanges poll per configured scope."""

    state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=config.dsn))
    published = 0
    for scope in config.scopes:
        async with scope_lock.acquire(f"inventory-resource-change-feed:{scope}"):
            feed = AzureResourceChangeFeed(
                identity=identity,
                resource_types=vocabulary,
                http_client=http_client,
                config=AzureResourceChangeFeedConfig(
                    subscription_scope=scope,
                    arg_endpoint=config.management_endpoint,
                    audience=config.management_audience,
                    requests_per_second=config.arg_requests_per_second,
                ),
            )
            published += await forward_arg_resource_changes_fn(
                feed=feed,
                state_store=state_store,
                event_bus=event_bus,
                topic=topic,
                scope=scope,
            )
    return published


async def collect_kubernetes_lifecycle(
    config: InventoryJobConfig,
    *,
    logger: logging.Logger,
    workload_identity_factory: _WorkloadIdentityFactory,
) -> int | None:
    """Collect one leased Kubernetes lifecycle window without affecting due-state."""

    if not config.kubernetes_bindings:
        return 0
    store = PostgresKubernetesLifecycleStore(
        config=PostgresKubernetesLifecycleConfig(dsn=config.dsn)
    )
    total = 0
    failed = False
    identity: WorkloadIdentity | None = None
    if any(binding.auth_mode == "workload-identity" for binding in config.kubernetes_bindings):
        async with httpx.AsyncClient() as identity_client:
            identity = workload_identity_factory(http_client=identity_client)
            for binding in config.kubernetes_bindings:
                result = await _collect_kubernetes_binding_lifecycle(
                    binding,
                    store=store,
                    logger=logger,
                    identity=identity,
                )
                if result is None:
                    failed = True
                else:
                    total += result
    else:
        for binding in config.kubernetes_bindings:
            result = await _collect_kubernetes_binding_lifecycle(
                binding,
                store=store,
                logger=logger,
                identity=None,
            )
            if result is None:
                failed = True
            else:
                total += result
    return None if failed else total


async def _collect_kubernetes_binding_lifecycle(
    binding: KubernetesClusterBinding,
    *,
    store: PostgresKubernetesLifecycleStore,
    logger: logging.Logger,
    identity: WorkloadIdentity | None,
) -> int | None:
    now = datetime.now(UTC)
    holder = f"inventory-lifecycle:{binding.scope_digest}:{uuid4()}"
    try:
        cursor = await store.acquire(
            cluster_ref=binding.cluster_ref,
            holder=holder,
            now=now,
            lease_until=now + timedelta(seconds=45),
        )
        if cursor is None:
            return 0
        kubernetes_ssl = ssl.create_default_context(
            cafile=str(binding.ca_path) if binding.ca_path else None,
            cadata=binding.ca_pem,
        )
        auth: KubernetesApiAuth
        if binding.auth_mode == "workload-identity":
            if identity is None or binding.audience is None:
                raise RuntimeError("Kubernetes lifecycle workload identity is unavailable")
            auth = WorkloadIdentityKubernetesAuth(
                identity=identity,
                audience=binding.audience,
            )
        else:
            if binding.token_path is None:
                raise RuntimeError("Kubernetes lifecycle service-account token is unavailable")
            auth = ServiceAccountTokenAuth(binding.token_path)
        async with httpx.AsyncClient(verify=kubernetes_ssl) as kubernetes_client:
            batch = await KubernetesLifecycleCollector(
                api_server=binding.api_server,
                cluster_ref=binding.cluster_ref,
                auth=auth,
                http_client=kubernetes_client,
            ).collect(cursor)
        if not await store.append(batch, holder=holder, now=datetime.now(UTC)):
            logger.warning(
                "kubernetes_lifecycle_cursor_contended",
                extra={
                    "reason": "lease_or_sequence_changed",
                    "scope_digest": binding.scope_digest,
                },
            )
            return None
        if batch.limitation is not None:
            logger.warning(
                "kubernetes_lifecycle_collection_incomplete",
                extra={"reason": batch.limitation, "scope_digest": binding.scope_digest},
            )
        return len(batch.observations)
    except Exception as exc:  # noqa: BLE001 - independent read-only evidence source
        logger.warning(
            "kubernetes_lifecycle_collection_failed",
            extra={"reason": type(exc).__name__, "scope_digest": binding.scope_digest},
        )
        return None
