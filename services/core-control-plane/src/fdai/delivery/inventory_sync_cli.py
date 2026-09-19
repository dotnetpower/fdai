"""One-shot inventory reconciliation entry point for scheduled jobs."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import ssl
import sys
from contextlib import AsyncExitStack
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial

import httpx
from fdai_service_contracts import InventoryProgressStage

from fdai.core.ontology_platform.runtime_call_telemetry import RuntimeCallTelemetryProducer
from fdai.delivery import inventory_collection_health_reporting, inventory_sync_cli_support
from fdai.delivery.aks_subscription_discovery import (
    AksSubscriptionDiscoveryConfig,
    AksSubscriptionDiscoveryError,
    AksUnavailableScope,
    AzureAksSubscriptionBindingDiscovery,
    subscription_scope_digest,
)
from fdai.delivery.azure.arg_projection import to_neutral_id
from fdai.delivery.azure.log_query import (
    AzureLogAnalyticsQueryConfig,
    AzureLogAnalyticsQueryProvider,
)
from fdai.delivery.azure.runtime_call_telemetry import (
    AzureContainerAppRevisionVerifier,
    AzureMonitorRuntimeCallAuthenticator,
    AzureMonitorRuntimeCallContextProvider,
    AzureRuntimeCallTelemetrySource,
)
from fdai.delivery.inventory_change_acceleration import (
    build_job_event_bus as _build_job_event_bus,
)
from fdai.delivery.inventory_change_acceleration import (
    forward_recovery_deltas as _forward_recovery_deltas,
)
from fdai.delivery.inventory_change_acceleration import (
    load_resource_type_registry as _load_resource_type_registry,
)
from fdai.delivery.inventory_change_acceleration import (
    recovery_delta_lock as _recovery_delta_lock,
)
from fdai.delivery.inventory_change_acceleration import (
    run_recovery_delta,
    run_resource_change_feed,
)
from fdai.delivery.inventory_change_acceleration import workload_identity as _workload_identity
from fdai.delivery.inventory_configuration_events import publish_promoted_resource_events
from fdai.delivery.inventory_job_config import InventoryJobConfig
from fdai.delivery.inventory_ontology_observer import (
    build_ontology_observer as _build_ontology_observer,
)
from fdai.delivery.inventory_progress import InventoryProgressUnavailableError
from fdai.delivery.inventory_progress_wiring import build_inventory_progress_recorder
from fdai.delivery.inventory_scheduler import CollectionScheduleDecision
from fdai.delivery.inventory_sync import (
    InventoryPromotionEnricher,
    InventoryPromotionObserverError,
    InventorySyncCoordinator,
)
from fdai.delivery.inventory_sync_cli_models import (
    ChangeStreamDrainResult,
    InventoryJobResult,
    generation_digest,
)
from fdai.delivery.inventory_sync_cli_models import (
    scope_ref as _scope_ref,
)
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
from fdai.delivery.operational_activity import (
    EventBusOperationalActivityPublisher,
    ObservedInventorySnapshotStore,
)
from fdai.delivery.persistence import (
    PostgresStateStore,
    PostgresStateStoreConfig,
)
from fdai.delivery.persistence.postgres_inventory_reconciliation import (
    InventoryReconciliationHealthState,
    PostgresInventoryReconciliationGate,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.delivery.runtime_call_inventory import (
    RuntimeCallInventoryEnricher,
    UnavailableRuntimeCallInventoryEnricher,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    ProviderRelationshipMappingCatalog,
    load_provider_relationship_mapping_catalog,
)
from fdai.runtime.venue import ExecutionVenue, resolve_execution_venue
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.inventory_snapshot import InventorySourcesExhaustedError
from fdai.shared.providers.workload_identity import WorkloadIdentity

_REPO_ROOT = repo_asset_root()
_LOGGER = logging.getLogger(__name__)
_COLLECTION_HEALTH_STATE_KEY = "inventory-collection-health"


def _load_relationship_mapping_catalog() -> ProviderRelationshipMappingCatalog:
    return load_provider_relationship_mapping_catalog(
        _REPO_ROOT / "rule-catalog" / "vocabulary" / "provider-relationship-mappings"
    )


def _build_runtime_call_enricher(
    *,
    config: InventoryJobConfig,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
) -> InventoryPromotionEnricher:
    """Bind authenticated Azure Monitor evidence or explicit unavailability."""

    if (
        config.monitor_workspace_id is None
        or not config.runtime_call_evidence_enabled
        or resolve_execution_venue(os.environ) is not ExecutionVenue.DEPLOYED
    ):
        return UnavailableRuntimeCallInventoryEnricher()
    catalog_root = _REPO_ROOT / "rule-catalog"
    catalog = load_ontology_catalog(
        catalog_root,
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=catalog_root / "probes",
    )
    scope_ref = _scope_ref(config.scopes)
    source = AzureRuntimeCallTelemetrySource(
        provider=AzureLogAnalyticsQueryProvider(
            config=AzureLogAnalyticsQueryConfig(
                workspace_id=config.monitor_workspace_id,
            ),
            identity=identity,
            http_client=http_client,
        ),
        context_provider=AzureMonitorRuntimeCallContextProvider(),
        endpoint_verifier=AzureContainerAppRevisionVerifier(
            identity=identity,
            http_client=http_client,
            management_endpoint=config.management_endpoint,
            management_audience=config.management_audience,
        ),
        scope_ref=scope_ref,
        freshness_ceiling_seconds=config.reconciliation_interval_seconds,
    )
    return RuntimeCallInventoryEnricher(
        source=source,
        producer=RuntimeCallTelemetryProducer(
            authenticator=AzureMonitorRuntimeCallAuthenticator(),
        ),
        ontology_release=catalog.build_release(),
        scope_ref=scope_ref,
        endpoint_verifier_identity="inventory.runtime-call-endpoint-verifier",
        endpoint_verifier_revision="1.0.0",
    )


async def _build_kubernetes_enricher(
    *,
    config: InventoryJobConfig,
    relationship_catalog: ProviderRelationshipMappingCatalog,
    stack: AsyncExitStack,
    identity: WorkloadIdentity | None = None,
) -> InventoryPromotionEnricher:
    if config.kubernetes_connector_registration_path is not None:
        if (
            config.kubernetes_bindings
            or config.kubernetes_subscription_discovery
            or config.kubernetes_api_server
            or config.kubernetes_unavailable_scopes
        ):
            raise ValueError("Kubernetes connector MUST NOT be combined with direct collection")
        from fdai.delivery.kubernetes_connector_runtime import FileConnectorRegistrations
        from fdai.delivery.kubernetes_connector_snapshot import (
            ConnectorInventorySource,
            ConnectorSnapshotInbox,
        )

        principal = config.kubernetes_connector_principal_ref
        if not principal:
            raise ValueError("Kubernetes connector requires a registered principal")
        registrations = FileConnectorRegistrations(config.kubernetes_connector_registration_path)
        registration = await registrations.read(principal)
        if registration is None:
            raise ValueError("Kubernetes connector enrollment is unavailable")
        registration.admit(
            principal_ref=principal,
            scope=registration.scope,
            capability="inventory.snapshot",
            now=datetime.now(UTC),
        )
        inbox = ConnectorSnapshotInbox(
            PostgresStateStore(config=PostgresStateStoreConfig(dsn=config.dsn)),
            registrations=registrations,
            allow_cluster_resources=config.kubernetes_connector_cluster_resources,
            now=lambda: datetime.now(UTC),
        )
        return KubernetesInventoryEnricher(
            source=ConnectorInventorySource(inbox, principal_ref=principal),
            relationship_mapping_catalog=relationship_catalog,
            scope_digest="sha256:"
            + hashlib.sha256(registration.scope.cluster_ref.encode()).hexdigest(),
        )
    if not config.kubernetes_bindings and not config.kubernetes_unavailable_scopes:
        return UnavailableKubernetesInventoryEnricher()
    enrichers: list[InventoryPromotionEnricher] = []
    enrichers.extend(
        UnavailableKubernetesInventoryEnricher(
            reason=item.reason,
            scope_digest=item.scope_digest,
        )
        for item in config.kubernetes_unavailable_scopes
    )
    for binding in config.kubernetes_bindings:
        try:
            kubernetes_ssl = ssl.create_default_context(
                cafile=str(binding.ca_path) if binding.ca_path else None,
                cadata=binding.ca_pem,
            )
        except OSError as exc:
            raise RuntimeError("Kubernetes CA bundle is unavailable") from exc
        auth: KubernetesApiAuth
        if binding.auth_mode == "workload-identity":
            if identity is None or binding.audience is None:
                raise RuntimeError("Kubernetes workload identity is unavailable")
            auth = WorkloadIdentityKubernetesAuth(
                identity=identity,
                audience=binding.audience,
            )
        else:
            if binding.token_path is None:
                raise RuntimeError("Kubernetes service-account token path is unavailable")
            auth = ServiceAccountTokenAuth(binding.token_path)
        kubernetes_client = await stack.enter_async_context(
            httpx.AsyncClient(verify=kubernetes_ssl)
        )
        enrichers.append(
            KubernetesInventoryEnricher(
                source=KubernetesApiInventorySource(
                    config=KubernetesApiInventoryConfig(
                        api_server=binding.api_server,
                        cluster_ref=to_neutral_id(binding.cluster_ref),
                    ),
                    auth=auth,
                    http_client=kubernetes_client,
                ),
                relationship_mapping_catalog=relationship_catalog,
                scope_digest=binding.scope_digest,
            )
        )
    return enrichers[0] if len(enrichers) == 1 else SequentialInventoryPromotionEnricher(*enrichers)


async def build_inventory_promotion_enricher(
    *,
    config: InventoryJobConfig,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    stack: AsyncExitStack,
    relationship_catalog: ProviderRelationshipMappingCatalog,
    previous_state_reader: PostgresInventorySnapshotStore,
    runtime_call_enricher: InventoryPromotionEnricher | None = None,
) -> InventoryPromotionEnricher:
    """Build the shared ordered enrichment pipeline for every full inventory refresh."""

    config = await _discover_subscription_kubernetes_bindings(
        config,
        identity=identity,
        http_client=http_client,
    )
    kubernetes_enricher = await _build_kubernetes_enricher(
        config=config,
        relationship_catalog=relationship_catalog,
        stack=stack,
        identity=identity,
    )
    return SequentialInventoryPromotionEnricher(
        runtime_call_enricher
        or _build_runtime_call_enricher(
            config=config,
            identity=identity,
            http_client=http_client,
        ),
        *inventory_sync_cli_support.build_azure_inventory_enrichers(
            config=config,
            identity=identity,
            http_client=http_client,
            previous_state_reader=previous_state_reader,
        ),
        kubernetes_enricher,
    )


_resolve_resource_types = inventory_sync_cli_support.resolve_resource_types
_build_sources = inventory_sync_cli_support.build_sources


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
        progress_recorder = await build_inventory_progress_recorder(
            config=config,
            identity=identity,
            http_client=client,
        )
        effective_enricher = await build_inventory_promotion_enricher(
            config=config,
            identity=identity,
            http_client=client,
            stack=stack,
            relationship_catalog=relationship_catalog,
            previous_state_reader=durable_store,
            runtime_call_enricher=promotion_enricher,
        )
        event_bus, event_topic = _build_job_event_bus(identity)
        activity_publisher = EventBusOperationalActivityPublisher(event_bus=event_bus)
        observed_store = ObservedInventorySnapshotStore(
            store=durable_store,
            publisher=activity_publisher,
        )
        evidence_counts: dict[str, int] = {}
        ontology_observer, ontology_recovery = _build_ontology_observer(
            config,
            vocabulary=vocabulary,
            publisher=activity_publisher,
            configuration_event_publisher=partial(
                publish_promoted_resource_events,
                event_bus=event_bus,
                topic=event_topic,
                scope_ref=_scope_ref(config.scopes),
            ),
            evidence_counts=evidence_counts,
        )
        try:
            result = await InventorySyncCoordinator(
                store=observed_store,
                promotion_enricher=effective_enricher,
                promotion_observer=ontology_observer,
                pre_run_recovery=ontology_recovery,
                run_lock=PostgresAdvisoryResourceLock(
                    config=PostgresAdvisoryResourceLockConfig(
                        dsn=config.dsn,
                        lock_timeout_ms=30_000,
                    )
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
                    progress_recorder=progress_recorder,
                )
            )
            await progress_recorder.advance(
                InventoryProgressStage.VERIFY,
                generation_digest=generation_digest(result.attempt_id),
            )
            active_snapshot_id = await durable_store.active_snapshot_id()
            if active_snapshot_id is None:
                raise RuntimeError("inventory promotion completed without a durable active pointer")
            active = active_snapshot_id == result.attempt_id
            if not active:
                raise RuntimeError("inventory active generation readback did not match promotion")
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
                await inventory_sync_cli_support.try_recovery_delta_operation(
                    lambda: _forward_recovery_deltas(
                        config=config,
                        identity=identity,
                        vocabulary=vocabulary,
                        http_client=client,
                        event_bus=event_bus,
                        topic=event_topic,
                        scope_lock=_recovery_delta_lock(config),
                    ),
                    logger=_LOGGER,
                )
        except Exception:
            try:
                await progress_recorder.fail("inventory_reconciliation_failed")
            except (ValueError, InventoryProgressUnavailableError) as progress_error:
                if "terminal inventory progress" not in str(progress_error):
                    if not isinstance(progress_error, InventoryProgressUnavailableError):
                        raise
            raise
        finally:
            await event_bus.close()
    return InventoryJobResult(
        attempt_id=result.attempt_id,
        source=result.source,
        active=active,
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
    config = await _resolve_subscription_kubernetes_bindings(config)
    await _collect_kubernetes_lifecycle(config)
    snapshot_config = PostgresInventorySnapshotStoreConfig(
        dsn=config.dsn,
        freshness_budget_seconds=config.freshness_budget_seconds,
    )
    collection_policy = config.collection_policy
    if collection_policy is None:
        raise RuntimeError("inventory collection policy is unavailable")
    drain = await _drain_change_stream(config)
    active_accelerator_sources = tuple(
        source_id
        for enabled, source_id in (
            (config.resource_change_feed_enabled, "resourcechanges-delta"),
            (config.recovery_delta_enabled, "activity-log-delta"),
        )
        if enabled
    )
    reconciliation_gate = PostgresInventoryReconciliationGate(
        config=snapshot_config,
        change_min_interval_seconds=config.change_min_interval_seconds,
        source_policy=config.snapshot_policy(config.source_order[0]),
        cursor_scopes=config.scopes,
        cursor_prefixes=tuple(
            prefix
            for enabled, prefix in (
                (config.resource_change_feed_enabled, "arg_resource_change_cursor:"),
                (config.recovery_delta_enabled, "inventory_delta_cursor:"),
            )
            if enabled
        ),
        cursor_stale_after_seconds=min(
            (
                collection_policy.source(source_id).target_freshness_seconds
                for source_id in active_accelerator_sources
            ),
            default=0.0,
        ),
    )
    due = await reconciliation_gate(
        config.reconciliation_interval_seconds,
        operator_requested=config.operator_requested,
    )
    await _publish_collection_health(
        config,
        health_state=reconciliation_gate.last_health_state,
        decision=reconciliation_gate.last_decision,
        accelerator_degraded=drain.degraded,
    )
    if not due:
        _LOGGER.info(
            "inventory_reconciliation_not_due",
            extra={
                "interval_seconds": config.reconciliation_interval_seconds,
                "change_records_published": drain.published,
                "change_stream_available": not drain.degraded,
                "unavailable_sources": drain.unavailable_sources,
            },
        )
        message = f"inventory reconciliation not due; change records published {drain.published}"
        if drain.degraded:
            message += f"; unavailable sources {','.join(drain.unavailable_sources)}"
        print(message, flush=True)
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


async def _resolve_subscription_kubernetes_bindings(
    config: InventoryJobConfig,
) -> InventoryJobConfig:
    """Resolve one subscription binding snapshot with the inventory read identity."""

    if not config.kubernetes_subscription_discovery:
        return config
    async with httpx.AsyncClient() as client:
        identity = _workload_identity(http_client=client)
        return await _discover_subscription_kubernetes_bindings(
            config,
            identity=identity,
            http_client=client,
        )


async def _discover_subscription_kubernetes_bindings(
    config: InventoryJobConfig,
    *,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
) -> InventoryJobConfig:
    """Resolve subscription bindings with an already selected read identity."""

    if not config.kubernetes_subscription_discovery or config.kubernetes_bindings:
        return config
    subscription_id = config.scopes[0]
    discovery = AzureAksSubscriptionBindingDiscovery(
        identity=identity,
        http_client=http_client,
        config=AksSubscriptionDiscoveryConfig(
            management_endpoint=config.management_endpoint,
            management_audience=config.management_audience,
        ),
    )
    try:
        result = await discovery.discover(subscription_id)
    except AksSubscriptionDiscoveryError:
        return replace(
            config,
            kubernetes_bindings=(),
            kubernetes_unavailable_scopes=(
                AksUnavailableScope(
                    scope_digest=subscription_scope_digest(subscription_id),
                    reason="kubernetes_subscription_discovery_unavailable",
                ),
            ),
        )
    if result.private_clusters:
        from fdai.delivery.kubernetes_connector_preflight_runtime import build_observer_constraints
        from fdai.delivery.kubernetes_connector_proposals import (
            ObserverDeploymentProposalService,
        )

        proposal_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=config.dsn))
        proposals = ObserverDeploymentProposalService(
            proposal_store,
            constraints=build_observer_constraints(proposal_store, now=lambda: datetime.now(UTC)),
            now=lambda: datetime.now(UTC),
        )
        async with asyncio.timeout(10):
            await proposals.observe(result.private_clusters)
        from fdai.delivery.kubernetes_connector_projection import publish_discovered_proposals

        await publish_discovered_proposals(
            targets=tuple(to_neutral_id(item.cluster_ref) for item in result.private_clusters),
            service=proposals,
            store=proposal_store,
            identity=identity,
        )
    return replace(
        config,
        kubernetes_bindings=result.bindings,
        kubernetes_unavailable_scopes=result.unavailable_scopes,
    )


async def _collect_kubernetes_lifecycle(config: InventoryJobConfig) -> int | None:
    """Collect one leased watch window independently of inventory snapshot due state."""
    return await inventory_sync_cli_support.collect_kubernetes_lifecycle(
        config,
        logger=_LOGGER,
        workload_identity_factory=_workload_identity,
    )


async def _publish_collection_health(
    config: InventoryJobConfig,
    *,
    health_state: InventoryReconciliationHealthState | None,
    decision: CollectionScheduleDecision | None,
    accelerator_degraded: bool = False,
) -> None:
    """Persist one sanitized aggregate projection for principal-gated reads."""

    projection = inventory_collection_health_reporting.build_scheduled_collection_health_projection(
        config,
        health_state=health_state,
        decision=decision,
        accelerator_degraded=accelerator_degraded,
    )
    if projection is None:
        return
    await PostgresStateStore(config=PostgresStateStoreConfig(dsn=config.dsn)).write_state(
        _COLLECTION_HEALTH_STATE_KEY, projection
    )


async def _drain_change_stream(config: InventoryJobConfig) -> ChangeStreamDrainResult:
    """Drain the read-only change accelerators without stopping completeness scans.

    The bounded ARG resourcechanges accelerator runs first - it is the
    lower-latency freshness hint - followed by the Activity Log recovery
    delta fallback/audit source. Each degrades independently: a source
    that is disabled or raises does not mask the other's success. The
    The result preserves both the published count and which enabled sources
    were unavailable. Disabled sources count as available no-ops."""

    resource_change_result = await _try_resource_change_feed(config)
    recovery_delta_result = await _try_recovery_delta(config)
    unavailable = tuple(
        source
        for source, result in (
            ("resourcechanges", resource_change_result),
            ("activity_log", recovery_delta_result),
        )
        if result is None
    )
    return ChangeStreamDrainResult(
        published=(resource_change_result or 0) + (recovery_delta_result or 0),
        unavailable_sources=unavailable,
    )


async def _try_resource_change_feed(config: InventoryJobConfig) -> int | None:
    if not config.resource_change_feed_enabled:
        return 0
    try:
        return await run_resource_change_feed(config)
    except Exception as exc:  # noqa: BLE001 - read-only accelerator degrades independently
        _LOGGER.warning(
            "inventory_resource_change_feed_unavailable",
            extra={"reason": type(exc).__name__},
        )
        return None


async def _try_recovery_delta(config: InventoryJobConfig) -> int | None:
    if not config.recovery_delta_enabled:
        return 0
    return await inventory_sync_cli_support.try_recovery_delta_operation(
        lambda: run_recovery_delta(config), logger=_LOGGER
    )


async def _main(argv: list[str]) -> None:
    loop = argv == ["--loop"]
    initial = argv == ["--initial"]
    if argv and not loop and not initial:
        raise ValueError("inventory reconciliation accepts only --initial or --loop")
    while True:
        config = await _load_job_config()
        if initial:
            await run(config)
            return
        try:
            await _run_due_once(config)
        except (InventorySourcesExhaustedError, InventoryPromotionObserverError) as exc:
            if not loop:
                raise
            failure_codes = (
                tuple(failure.code.value for failure in exc.failures)
                if isinstance(exc, InventorySourcesExhaustedError)
                else ("ontology_projection_failed",)
            )
            _LOGGER.warning(
                "inventory_reconciliation_loop_tick_failed",
                extra={"failure_codes": failure_codes},
            )
            print("inventory reconciliation failed; retry scheduled", flush=True)
        if not loop:
            return
        await asyncio.sleep(config.loop_seconds)


def container_argv(argv: list[str]) -> list[str]:
    """Translate the Container Apps positional mode into the existing CLI contract."""

    if argv == ["once"]:
        return []
    if argv == ["loop"]:
        return ["--loop"]
    raise ValueError("inventory container entrypoint accepts once or loop")


def container_main() -> None:
    """Run inventory synchronization from a positional Container Apps command."""

    asyncio.run(_main(container_argv(sys.argv[1:])))


def main() -> None:
    """Run one due-checked reconciliation under the job process identity."""
    asyncio.run(_main(sys.argv[1:]))


if __name__ == "__main__":
    main()


__all__ = [
    "InventoryJobConfig",
    "InventoryJobResult",
    "container_argv",
    "container_main",
    "run",
    "run_recovery_delta",
    "run_resource_change_feed",
]
