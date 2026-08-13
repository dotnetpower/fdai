"""One-shot inventory reconciliation entry point for scheduled jobs."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml
from fdai_service_contracts import OperationalActivityStatus, OperationalFreshness

from fdai.delivery.azure.activity_log import AzureActivityLogFactory, AzureActivityLogFactoryConfig
from fdai.delivery.azure.arg_query import AzureArgQueryFactory, AzureArgQueryFactoryConfig
from fdai.delivery.azure.arm_inventory import (
    AzureArmInventoryFactory,
    AzureArmInventoryFactoryConfig,
)
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.inventory import AzureInventoryConfig, AzureResourceGraphInventory
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.inventory_delta import forward_inventory_delta
from fdai.delivery.inventory_sync import (
    InventoryPromotionObserver,
    InventorySyncCoordinator,
    PromotedInventoryObservation,
)
from fdai.delivery.inventory_topology_history import InventoryTopologyHistoryPublisher
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
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventoryReconciliationGate,
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)
from fdai.delivery.persistence.postgres_topology_history import (
    PostgresTopologyHistoryStore,
    PostgresTopologyHistoryStoreConfig,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
    resource_type_mapping_digests,
)
from fdai.runtime.inventory_ontology import (
    InventoryOntologyProjectionStatus,
    InventoryOntologyProjector,
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
)
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.workload_identity import WorkloadIdentity

_REPO_ROOT = Path(__file__).resolve().parents[5]
_LOGGER = logging.getLogger(__name__)
_MANAGEMENT_AUDIENCE_BY_ORIGIN = {
    "https://management.azure.com": "https://management.azure.com/.default",
    "https://management.chinacloudapi.cn": "https://management.chinacloudapi.cn/.default",
    "https://management.microsoftazure.de": "https://management.microsoftazure.de/.default",
    "https://management.usgovcloudapi.net": "https://management.usgovcloudapi.net/.default",
}


@dataclass(frozen=True, slots=True)
class InventoryJobConfig:
    """Validate the environment contract for one inventory reconciliation job."""

    dsn: str
    scopes: tuple[str, ...]
    source_order: tuple[str, ...]
    resource_types: tuple[str, ...]
    management_endpoint: str
    management_audience: str
    freshness_budget_seconds: int
    reconciliation_interval_seconds: int
    recovery_delta_enabled: bool = False
    declarative_path: Path | None = None
    declarative_sha256: str | None = None

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        runtime_values: Mapping[str, object] | None = None,
    ) -> InventoryJobConfig:
        """Parse bounded job settings and reject incomplete source configuration."""
        source = env if env is not None else os.environ
        dsn = source.get("FDAI_INVENTORY_DSN", "").strip()
        default_scope = source.get("AZURE_SUBSCRIPTION_ID", "").strip()
        scopes = _csv(source.get("FDAI_INVENTORY_SCOPES", default_scope))
        source_order = _csv(source.get("FDAI_INVENTORY_SOURCES", "arg,arm"))
        resource_types = _csv(source.get("FDAI_INVENTORY_RESOURCE_TYPES", ""))
        management_endpoint = source.get(
            "FDAI_INVENTORY_MANAGEMENT_ENDPOINT", "https://management.azure.com"
        ).strip()
        management_audience = source.get(
            "FDAI_INVENTORY_MANAGEMENT_AUDIENCE",
            "https://management.azure.com/.default",
        ).strip()
        freshness = _freshness_seconds(source=source, runtime_values=runtime_values)
        reconciliation_interval = _integer_env(
            source,
            "FDAI_INVENTORY_RECONCILIATION_INTERVAL_SECONDS",
            21_600,
        )
        declarative_value = source.get("FDAI_INVENTORY_DECLARATIVE_PATH", "").strip()
        declarative_sha256 = source.get("FDAI_INVENTORY_DECLARATIVE_SHA256", "").strip() or None
        recovery_delta_enabled = _bool_env(
            source,
            "FDAI_INVENTORY_RECOVERY_DELTA",
            False,
        )

        if not dsn:
            raise ValueError("FDAI_INVENTORY_DSN MUST NOT be empty")
        if not scopes:
            raise ValueError("FDAI_INVENTORY_SCOPES MUST NOT be empty")
        if not source_order or set(source_order) - {"arg", "arm", "declarative"}:
            raise ValueError("FDAI_INVENTORY_SOURCES supports arg, arm, declarative")
        _validate_management_origin(management_endpoint, management_audience)
        if freshness < 1:
            raise ValueError("FDAI_INVENTORY_FRESHNESS_SECONDS MUST be >= 1")
        if reconciliation_interval < 60:
            raise ValueError("FDAI_INVENTORY_RECONCILIATION_INTERVAL_SECONDS MUST be >= 60")
        if "declarative" in source_order and (not declarative_value or declarative_sha256 is None):
            raise ValueError(
                "declarative fallback requires FDAI_INVENTORY_DECLARATIVE_PATH and SHA256"
            )
        return cls(
            dsn=dsn,
            scopes=scopes,
            source_order=source_order,
            resource_types=resource_types,
            management_endpoint=management_endpoint,
            management_audience=management_audience,
            freshness_budget_seconds=freshness,
            reconciliation_interval_seconds=reconciliation_interval,
            recovery_delta_enabled=recovery_delta_enabled,
            declarative_path=Path(declarative_value) if declarative_value else None,
            declarative_sha256=declarative_sha256,
        )


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


def _validate_management_origin(endpoint: str, audience: str) -> None:
    parsed = urlparse(endpoint)
    normalized = endpoint.rstrip("/")
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
        or normalized not in _MANAGEMENT_AUDIENCE_BY_ORIGIN
    ):
        raise ValueError("FDAI_INVENTORY_MANAGEMENT_ENDPOINT MUST be an approved HTTPS ARM origin")
    if audience != _MANAGEMENT_AUDIENCE_BY_ORIGIN[normalized]:
        raise ValueError("FDAI_INVENTORY_MANAGEMENT_AUDIENCE MUST match the ARM origin")


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
        link_types: tuple[str, ...] = ("contains", "attached_to", "depends_on")
        inventory: Inventory
        if source_name == "arg":
            query = AzureArgQueryFactory(
                identity=identity,
                resource_types=vocabulary,
                http_client=http_client,
                config=AzureArgQueryFactoryConfig(
                    subscription_scopes=config.scopes,
                    arg_endpoint=config.management_endpoint,
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
            _verify_sha256(config.declarative_path, config.declarative_sha256)
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
    projector: InventoryOntologyProjector | None = None
    ontology_store: PostgresOntologyInstanceStore | None = None
    topology_publisher: InventoryTopologyHistoryPublisher | None = None
    if _bool_env(os.environ, "FDAI_INVENTORY_ONTOLOGY_PROJECTION", True):
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
        )
        topology_publisher = InventoryTopologyHistoryPublisher(
            writer=PostgresTopologyHistoryStore(
                config=PostgresTopologyHistoryStoreConfig(dsn=config.dsn)
            ),
            ontology_release_digest=ontology_release_digest,
        )

    async def _observe(observation: PromotedInventoryObservation) -> None:
        evidence_counts[observation.generation] = len(observation.resources) + len(
            observation.links
        )
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
            result = await projector.apply(observation)
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


async def run(config: InventoryJobConfig) -> InventoryJobResult:
    """Run ordered source fallback and verify the promoted durable pointer."""
    vocabulary = _load_resource_type_registry()
    resource_types = _resolve_resource_types(config, vocabulary)
    durable_store = PostgresInventorySnapshotStore(
        config=PostgresInventorySnapshotStoreConfig(
            dsn=config.dsn,
            freshness_budget_seconds=config.freshness_budget_seconds,
        )
    )
    async with httpx.AsyncClient() as client:
        identity = ManagedIdentityWorkloadIdentity.from_env(http_client=client)
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
                promotion_observer=_build_ontology_observer(
                    config,
                    vocabulary=vocabulary,
                    publisher=activity_publisher,
                    evidence_counts=evidence_counts,
                ),
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
        identity = ManagedIdentityWorkloadIdentity.from_env(http_client=client)
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
    execution_venue = os.environ.get("FDAI_EXECUTION_VENUE", "deployed").strip()
    if execution_venue not in {"local", "deployed"}:
        raise RuntimeError("FDAI_EXECUTION_VENUE MUST be local or deployed")
    return EventHubsKafkaBus(
        identity=identity if execution_venue == "deployed" else None,
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=app_config.kafka.bootstrap_servers,
            dlq_suffix=app_config.kafka.topic_dlq_suffix,
            security_protocol="SASL_SSL" if execution_venue == "deployed" else "PLAINTEXT",
            client_id="fdai-inventory-recovery",
        ),
    ), app_config.kafka.topic_events


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


def _freshness_seconds(
    *,
    source: Mapping[str, str],
    runtime_values: Mapping[str, object] | None,
) -> int:
    if runtime_values is None:
        return _integer_env(source, "FDAI_INVENTORY_FRESHNESS_SECONDS", 86_400)
    value = runtime_values.get("inventory.freshness_seconds")
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("effective inventory freshness setting MUST be an integer")
    return value


def _integer_env(source: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(source.get(key, str(default)))
    except ValueError as exc:
        raise ValueError(f"{key} MUST be an integer") from exc


def _verify_sha256(path: Path, expected: str) -> None:
    """Verify one declarative fallback without exposing its content."""
    if len(expected) != 64 or any(char not in "0123456789abcdefABCDEF" for char in expected):
        raise ValueError("declarative SHA256 MUST be 64 hexadecimal characters")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual.lower() != expected.lower():
        raise ValueError("declarative inventory SHA256 does not match")


def _csv(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))


def _bool_env(source: Mapping[str, str], key: str, default: bool) -> bool:
    raw = source.get(key)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true"}:
        return True
    if normalized in {"0", "false"}:
        return False
    raise ValueError(f"{key} MUST be one of 1, 0, true, false")


async def _main() -> None:
    from fdai.delivery.runtime_settings import runtime_settings_service_from_env

    runtime_values = await runtime_settings_service_from_env(os.environ).effective_values()
    config = InventoryJobConfig.from_env(runtime_values=runtime_values)
    snapshot_config = PostgresInventorySnapshotStoreConfig(
        dsn=config.dsn,
        freshness_budget_seconds=config.freshness_budget_seconds,
    )
    due = await PostgresInventoryReconciliationGate(config=snapshot_config)(
        config.reconciliation_interval_seconds
    )
    if not due:
        _LOGGER.info(
            "inventory_reconciliation_not_due",
            extra={"interval_seconds": config.reconciliation_interval_seconds},
        )
        if config.recovery_delta_enabled:
            published = await run_recovery_delta(config)
            print(f"inventory reconciliation not due; recovery delta published {published}")
        else:
            print("inventory reconciliation not due")
        return
    result = await run(config)
    if result.active:
        print(f"inventory snapshot promoted from {result.source}")
    else:
        print(f"inventory snapshot from {result.source} superseded by a newer attempt")


def main() -> None:
    """Run one due-checked reconciliation under the job process identity."""
    asyncio.run(_main())


if __name__ == "__main__":
    main()


__all__ = ["InventoryJobConfig", "InventoryJobResult", "run", "run_recovery_delta"]
