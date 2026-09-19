"""Project promoted inventory and publish its read-only evaluation handoff."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from fdai_service_contracts import OperationalActivityStatus, OperationalFreshness

from fdai.core.ontology_platform.aks_diagnostic_receipt_service import (
    AksDiagnosticReceiptService,
)
from fdai.delivery import inventory_sync_cli_support
from fdai.delivery.aks_diagnostic_receipts import (
    InventoryPromotionAksDiagnosticObserver,
    StateStoreAksDiagnosticReceiptWriter,
)
from fdai.delivery.inventory_configuration_events import (
    INVENTORY_CONFIGURATION_DELIVERY_KEY,
    configuration_delivery_record,
)
from fdai.delivery.inventory_job_config import InventoryJobConfig, read_bool_env
from fdai.delivery.inventory_sync import (
    InventoryPromotionObserver,
    InventoryPromotionRecovery,
    PromotedInventoryObservation,
)
from fdai.delivery.inventory_sync_cli_models import InventoryOntologyProjectionIncompleteError
from fdai.delivery.inventory_topology_history import InventoryTopologyHistoryPublisher
from fdai.delivery.operational_activity import (
    EventBusOperationalActivityPublisher,
    ontology_projection_activity,
)
from fdai.delivery.operational_history_policy import build_observation_journal
from fdai.delivery.persistence import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
    PostgresStateStore,
    PostgresStateStoreConfig,
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
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    resource_type_mapping_digests,
)
from fdai.runtime.inventory_ontology import (
    InventoryOntologyProjectionStatus,
    InventoryOntologyProjector,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_REPO_ROOT = repo_asset_root()


def build_ontology_observer(
    config: InventoryJobConfig,
    *,
    vocabulary: ResourceTypeRegistry,
    publisher: EventBusOperationalActivityPublisher,
    configuration_event_publisher: Callable[[PromotedInventoryObservation], Awaitable[int]],
    evidence_counts: dict[str, int],
) -> tuple[InventoryPromotionObserver, InventoryPromotionRecovery]:
    """Build projection and recovery observers for promoted inventory generations."""
    observation_journal = build_observation_journal(config.dsn, os.environ)
    catalog_root = _REPO_ROOT / "rule-catalog"
    catalog = load_ontology_catalog(
        catalog_root,
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=catalog_root / "probes",
    )
    ontology_release_digest = catalog.build_release().digest
    status_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=config.dsn))
    diagnostic_observer = InventoryPromotionAksDiagnosticObserver(
        service=AksDiagnosticReceiptService(
            writer=StateStoreAksDiagnosticReceiptWriter(store=status_store)
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
            status_store=status_store,
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
            freshness_ceiling_seconds=config.reconciliation_interval_seconds,
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
                    await status_store.write_state(
                        INVENTORY_CONFIGURATION_DELIVERY_KEY,
                        configuration_delivery_record(observation),
                    )
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
            history_available
            and result.status is InventoryOntologyProjectionStatus.AVAILABLE
            and result.complete
        )
        reason_codes = result.dropped_reasons + (
            () if history_available else ("topology_history_unavailable",)
        )
        if result.status is InventoryOntologyProjectionStatus.AVAILABLE and result.complete:
            try:
                await _deliver_configuration(observation)
            except Exception:  # noqa: BLE001 - recovery retries the exact generation
                await publisher.publish(
                    ontology_projection_activity(
                        generation=observation.generation,
                        status=OperationalActivityStatus.FAILED,
                        freshness=OperationalFreshness.UNAVAILABLE,
                        evidence_count=evidence_counts[observation.generation],
                        reason_codes=("configuration_event_publish_failed",),
                    )
                )
                raise
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

    async def _deliver_configuration(observation: PromotedInventoryObservation) -> None:
        expected = configuration_delivery_record(observation)
        retained = await status_store.read_state(INVENTORY_CONFIGURATION_DELIVERY_KEY)
        completed = configuration_delivery_record(observation, completed=True)
        if retained == completed:
            return
        if retained != expected:
            raise ValueError("inventory configuration delivery content changed")
        count = await configuration_event_publisher(observation)
        if type(count) is not int or count != len(observation.resources):
            raise ValueError("inventory configuration delivery count is incomplete")
        await status_store.write_state(INVENTORY_CONFIGURATION_DELIVERY_KEY, completed)

    async def _recover_observation(observation: PromotedInventoryObservation) -> None:
        manifest = await status_store.read_state("inventory-ontology:manifest")
        status = await status_store.read_state("inventory-ontology:status")
        if (
            manifest is not None
            and status is not None
            and manifest.get("generation") == observation.generation
            and status.get("generation") == observation.generation
            and manifest.get("ontology_release_digest") == ontology_release_digest
            and status.get("ontology_release_digest") == ontology_release_digest
            and manifest.get("complete") is True
            and status.get("complete") is True
            and status.get("status") == "available"
            and manifest.get("manifest_digest") == status.get("manifest_digest")
        ):
            await _deliver_configuration(observation)
            return
        await _observe(observation)

    async def _recover() -> None:
        await inventory_sync_cli_support.recover_ontology_projection(
            load_pending=observation_journal.load_pending_promoted_snapshot,
            observe=_recover_observation if projector is not None else _observe,
            status_store=status_store if projector is not None else None,
            release_digest=ontology_release_digest,
            allow_release_mismatch_collection=config.operator_requested,
        )

    return _observe, _recover


__all__ = ["build_ontology_observer"]
