"""One-shot inventory reconciliation entry point for scheduled jobs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import ssl
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from fdai_service_contracts import OperationalActivityStatus, OperationalFreshness

from fdai.core.ontology_platform.aks_diagnostic_receipt_service import (
    AksDiagnosticReceiptService,
)
from fdai.core.ontology_platform.runtime_call_telemetry import RuntimeCallTelemetryProducer
from fdai.delivery import inventory_collection_health_reporting, inventory_sync_cli_support
from fdai.delivery.aks_diagnostic_receipts import (
    InventoryPromotionAksDiagnosticObserver,
    StateStoreAksDiagnosticReceiptWriter,
)
from fdai.delivery.azure.log_query import (
    AzureLogAnalyticsQueryConfig,
    AzureLogAnalyticsQueryProvider,
)
from fdai.delivery.azure.resource_health_inventory import (
    AzureResourceHealthInventoryConfig,
    AzureResourceHealthInventoryEnricher,
)
from fdai.delivery.azure.runtime_call_telemetry import (
    AzureContainerAppRevisionVerifier,
    AzureMonitorRuntimeCallAuthenticator,
    AzureMonitorRuntimeCallContextProvider,
    AzureRuntimeCallTelemetrySource,
)
from fdai.delivery.azure.static_web_app_inventory import (
    AzureStaticWebAppInventoryConfig,
    AzureStaticWebAppInventoryEnricher,
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
from fdai.delivery.inventory_job_config import (
    InventoryJobConfig,
    read_bool_env,
)
from fdai.delivery.inventory_scheduler import CollectionScheduleDecision
from fdai.delivery.inventory_sync import (
    InventoryPromotionEnricher,
    InventoryPromotionObserver,
    InventoryPromotionObserverError,
    InventoryPromotionRecovery,
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
from fdai.delivery.operational_activity import (
    EventBusOperationalActivityPublisher,
    ObservedInventorySnapshotStore,
    ontology_projection_activity,
)
from fdai.delivery.operational_history_policy import build_observation_journal
from fdai.delivery.persistence import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
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
from fdai.delivery.persistence.postgres_state_transitions import (
    PostgresStateTransitionStore,
    PostgresStateTransitionStoreConfig,
)
from fdai.delivery.persistence.postgres_topology_history import (
    PostgresTopologyHistoryStore,
    PostgresTopologyHistoryStoreConfig,
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
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    resource_type_mapping_digests,
)
from fdai.runtime.inventory_ontology import (
    InventoryOntologyProjectionStatus,
    InventoryOntologyProjector,
)
from fdai.runtime.venue import ExecutionVenue, resolve_execution_venue
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.inventory_snapshot import InventorySourcesExhaustedError
from fdai.shared.providers.workload_identity import WorkloadIdentity

_REPO_ROOT = repo_asset_root()
_LOGGER = logging.getLogger(__name__)
_COLLECTION_HEALTH_STATE_KEY = "inventory-collection-health"


class InventoryOntologyProjectionIncompleteError(RuntimeError):
    """A promoted snapshot remains pending after a degraded projection."""


@dataclass(frozen=True, slots=True)
class InventoryJobResult:
    """Report one promoted attempt after rereading the durable active pointer."""

    attempt_id: str
    source: str
    active: bool


@dataclass(frozen=True, slots=True)
class ChangeStreamDrainResult:
    """Sanitized per-source outcome for one bounded accelerator drain."""

    published: int
    unavailable_sources: tuple[str, ...] = ()

    @property
    def degraded(self) -> bool:
        """Return whether any enabled accelerator was unavailable."""
        return bool(self.unavailable_sources)


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


def _scope_ref(scopes: tuple[str, ...]) -> str:
    encoded = json.dumps(sorted(set(scopes)), separators=(",", ":")).encode("utf-8")
    return "scope-set:sha256:" + hashlib.sha256(encoded).hexdigest()


async def _build_kubernetes_enricher(
    *,
    config: InventoryJobConfig,
    relationship_catalog: ProviderRelationshipMappingCatalog,
    stack: AsyncExitStack,
    identity: WorkloadIdentity | None = None,
) -> InventoryPromotionEnricher:
    if not config.kubernetes_bindings:
        return UnavailableKubernetesInventoryEnricher()
    enrichers: list[InventoryPromotionEnricher] = []
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
                        cluster_ref=binding.cluster_ref,
                    ),
                    auth=auth,
                    http_client=kubernetes_client,
                ),
                relationship_mapping_catalog=relationship_catalog,
                scope_digest=binding.scope_digest,
            )
        )
    return enrichers[0] if len(enrichers) == 1 else SequentialInventoryPromotionEnricher(*enrichers)


_resolve_resource_types = inventory_sync_cli_support.resolve_resource_types
_build_sources = inventory_sync_cli_support.build_sources


def _build_ontology_observer(
    config: InventoryJobConfig,
    *,
    vocabulary: ResourceTypeRegistry,
    publisher: EventBusOperationalActivityPublisher,
    evidence_counts: dict[str, int],
) -> tuple[InventoryPromotionObserver, InventoryPromotionRecovery]:
    observation_journal = build_observation_journal(config.dsn, os.environ)
    catalog_root = _REPO_ROOT / "rule-catalog"
    catalog = load_ontology_catalog(
        catalog_root,
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=catalog_root / "probes",
    )
    ontology_release_digest = catalog.build_release().digest
    diagnostic_observer = InventoryPromotionAksDiagnosticObserver(
        service=AksDiagnosticReceiptService(
            writer=StateStoreAksDiagnosticReceiptWriter(
                store=PostgresStateStore(config=PostgresStateStoreConfig(dsn=config.dsn))
            )
        ),
        ontology_release=ontology_release_digest,
        scope_by_cluster_ref={
            binding.cluster_ref: binding.scope_digest for binding in config.kubernetes_bindings
        },
    )
    projector: InventoryOntologyProjector | None = None
    ontology_store: PostgresOntologyInstanceStore | None = None
    topology_publisher: InventoryTopologyHistoryPublisher | None = None
    if read_bool_env(os.environ, "FDAI_INVENTORY_ONTOLOGY_PROJECTION", True):
        ontology_store = PostgresOntologyInstanceStore(
            config=PostgresOntologyInstanceStoreConfig(dsn=config.dsn),
            object_types=catalog.object_types,
            link_types=catalog.link_types,
        )
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
            current_state_reader=ontology_store,
        )

    async def _observe(observation: PromotedInventoryObservation) -> None:
        evidence_counts[observation.generation] = len(observation.resources) + len(
            observation.links
        )
        journal_append = await observation_journal.append_promoted_snapshot(observation)
        await diagnostic_observer.observe(observation)
        if projector is None or ontology_store is None or topology_publisher is None:
            return
        failures: list[tuple[str, Exception]] = []
        history_available = False
        catalog_available = True
        try:
            await ontology_store.sync_catalog()
        except Exception as exc:  # noqa: BLE001 - independent derived read model
            failures.append(("catalog_sync_failed", exc))
            catalog_available = False
        result = None
        if catalog_available:
            history_succeeded = False
            try:
                history_available = await topology_publisher.publish(observation) is not None
                history_succeeded = True
            except Exception as exc:  # noqa: BLE001 - independent derived read model
                failures.append(("topology_history_failed", exc))
            if history_succeeded:
                try:
                    result = await projector.apply(
                        observation,
                        journal_high_watermark=journal_append.journal_high_watermark,
                        projection_high_watermark=journal_append.projection_high_watermark,
                        active_scope_projection_watermark=(
                            journal_append.active_scope_projection_watermark
                        ),
                        active_scope_refs=journal_append.active_scope_refs,
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
        if result.status is not InventoryOntologyProjectionStatus.AVAILABLE or not result.complete:
            raise InventoryOntologyProjectionIncompleteError(
                "inventory ontology projection is incomplete"
            )

    async def _recover() -> None:
        pending = await observation_journal.load_pending_promoted_snapshot()
        if pending is not None:
            try:
                await _observe(pending)
            except InventoryOntologyProjectionIncompleteError:
                return

    return _observe, _recover


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
        resource_health_enricher = AzureResourceHealthInventoryEnricher(
            identity=identity,
            http_client=client,
            config=AzureResourceHealthInventoryConfig(
                subscription_ids=config.scopes,
                endpoint=config.management_endpoint,
                audience=config.management_audience,
                freshness_ceiling_seconds=config.reconciliation_interval_seconds,
            ),
            previous_state_reader=durable_store,
        )
        static_web_app_enricher = AzureStaticWebAppInventoryEnricher(
            identity=identity,
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(
                subscription_ids=config.scopes,
                endpoint=config.management_endpoint,
                audience=config.management_audience,
                freshness_ceiling_seconds=config.reconciliation_interval_seconds,
            ),
            previous_state_reader=durable_store,
        )
        runtime_call_enricher = promotion_enricher or _build_runtime_call_enricher(
            config=config,
            identity=identity,
            http_client=client,
        )
        effective_enricher = SequentialInventoryPromotionEnricher(
            runtime_call_enricher,
            resource_health_enricher,
            static_web_app_enricher,
            kubernetes_enricher,
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
    due = await reconciliation_gate(config.reconciliation_interval_seconds)
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
