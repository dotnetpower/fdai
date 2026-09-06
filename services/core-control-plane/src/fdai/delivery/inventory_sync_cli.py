"""One-shot inventory reconciliation entry point for scheduled jobs."""

from __future__ import annotations

import asyncio
import logging
import os
import ssl
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from fdai_service_contracts import OperationalActivityStatus, OperationalFreshness

from fdai.delivery import inventory_collection_health_reporting, inventory_sync_cli_support
from fdai.delivery.azure.resource_health_inventory import (
    AzureResourceHealthInventoryConfig,
    AzureResourceHealthInventoryEnricher,
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
from fdai.delivery.runtime_call_inventory import UnavailableRuntimeCallInventoryEnricher
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
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.inventory_snapshot import InventorySourcesExhaustedError
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
            current_state_reader=ontology_store,
        )

    async def _observe(observation: PromotedInventoryObservation) -> None:
        evidence_counts[observation.generation] = len(observation.resources) + len(
            observation.links
        )
        journal_append = await observation_journal.append_promoted_snapshot(observation)
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
            raise RuntimeError("inventory ontology projection is incomplete")

    async def _recover() -> None:
        if projector is None or ontology_store is None or topology_publisher is None:
            return
        pending = await observation_journal.load_pending_promoted_snapshot()
        if pending is not None:
            await _observe(pending)

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
        effective_enricher = SequentialInventoryPromotionEnricher(
            promotion_enricher or UnavailableRuntimeCallInventoryEnricher(),
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
) -> None:
    """Persist one sanitized aggregate projection for principal-gated reads."""

    projection = inventory_collection_health_reporting.build_scheduled_collection_health_projection(
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
    """Drain the read-only change accelerators without stopping completeness scans.

    The bounded ARG resourcechanges accelerator runs first - it is the
    lower-latency freshness hint - followed by the Activity Log recovery
    delta fallback/audit source. Each degrades independently: a source
    that is disabled or raises does not mask the other's success. The
    combined result is `None` only when both are unavailable (disabled
    counts as `0`, not unavailable), otherwise it is the sum of whatever
    each source actually published."""

    resource_change_result = await _try_resource_change_feed(config)
    recovery_delta_result = await _try_recovery_delta(config)
    if resource_change_result is None and recovery_delta_result is None:
        return None
    return (resource_change_result or 0) + (recovery_delta_result or 0)


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
