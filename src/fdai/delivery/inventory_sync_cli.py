"""One-shot Azure inventory reconciliation entry point for scheduled jobs."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from fdai.delivery.azure.activity_log import (
    AzureActivityLogFactory,
    AzureActivityLogFactoryConfig,
)
from fdai.delivery.azure.arg_query import AzureArgQueryFactory, AzureArgQueryFactoryConfig
from fdai.delivery.azure.arm_inventory import (
    AzureArmInventoryFactory,
    AzureArmInventoryFactoryConfig,
)
from fdai.delivery.azure.inventory import AzureInventoryConfig, AzureResourceGraphInventory
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.event_publisher import EventPublisherContext
from fdai.delivery.inventory_delta import forward_inventory_delta
from fdai.delivery.inventory_sync import InventorySyncCoordinator
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
)
from fdai.shared.config.loader import load_config_from_env
from fdai.shared.providers.declarative_inventory import (
    DeclarativeInventory,
    DeclarativeInventoryConfig,
)
from fdai.shared.providers.inventory import Inventory, LinkRecord, ResourceRecord
from fdai.shared.providers.inventory_snapshot import (
    InventoryCoverageManifest,
    InventoryObservationKind,
    InventorySource,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InventoryJobConfig:
    """Validated environment contract for one inventory reconciliation job."""

    dsn: str
    scopes: tuple[str, ...]
    source_order: tuple[str, ...]
    resource_types: tuple[str, ...]
    management_endpoint: str
    management_audience: str
    freshness_budget_seconds: int
    recovery_delta_enabled: bool = False
    declarative_path: Path | None = None
    declarative_sha256: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> InventoryJobConfig:
        source = env if env is not None else os.environ
        dsn = source.get("FDAI_INVENTORY_DSN", "").strip()
        default_scope = source.get("AZURE_SUBSCRIPTION_ID", "").strip()
        scopes = _csv(source.get("FDAI_INVENTORY_SCOPES", default_scope))
        source_order = _csv(source.get("FDAI_INVENTORY_SOURCES", "arg,arm"))
        resource_types = _csv(source.get("FDAI_INVENTORY_RESOURCE_TYPES", ""))
        endpoint = source.get(
            "FDAI_INVENTORY_MANAGEMENT_ENDPOINT", "https://management.azure.com"
        ).strip()
        audience = source.get(
            "FDAI_INVENTORY_MANAGEMENT_AUDIENCE",
            "https://management.azure.com/.default",
        ).strip()
        try:
            freshness = int(source.get("FDAI_INVENTORY_FRESHNESS_SECONDS", "86400"))
        except ValueError as exc:
            raise ValueError("FDAI_INVENTORY_FRESHNESS_SECONDS MUST be an integer") from exc
        path_value = source.get("FDAI_INVENTORY_DECLARATIVE_PATH", "").strip()
        sha = source.get("FDAI_INVENTORY_DECLARATIVE_SHA256", "").strip() or None
        recovery_delta = _bool_env(source, "FDAI_INVENTORY_RECOVERY_DELTA", False)
        if not dsn:
            raise ValueError("FDAI_INVENTORY_DSN MUST NOT be empty")
        if not scopes:
            raise ValueError("FDAI_INVENTORY_SCOPES MUST NOT be empty")
        if not source_order or set(source_order) - {"arg", "arm", "declarative"}:
            raise ValueError("FDAI_INVENTORY_SOURCES supports arg, arm, declarative")
        if freshness < 1:
            raise ValueError("FDAI_INVENTORY_FRESHNESS_SECONDS MUST be >= 1")
        if "declarative" in source_order and (not path_value or sha is None):
            raise ValueError(
                "declarative fallback requires FDAI_INVENTORY_DECLARATIVE_PATH and SHA256"
            )
        return cls(
            dsn=dsn,
            scopes=scopes,
            source_order=source_order,
            resource_types=resource_types,
            management_endpoint=endpoint,
            management_audience=audience,
            freshness_budget_seconds=freshness,
            recovery_delta_enabled=recovery_delta,
            declarative_path=Path(path_value) if path_value else None,
            declarative_sha256=sha,
        )


async def run(config: InventoryJobConfig) -> str:
    """Build configured sources, run ordered fallback, and return the active source."""

    vocabulary_path = _REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
    vocabulary = load_resource_type_registry_from_mapping(
        yaml.safe_load(vocabulary_path.read_text(encoding="utf-8"))
    )
    resource_types = config.resource_types or tuple(
        item.id for item in vocabulary if item.azure_arm_type is not None
    )
    unknown_types = sorted(set(resource_types) - vocabulary.ids())
    if unknown_types:
        raise ValueError(f"unknown inventory resource types: {', '.join(unknown_types)}")
    if "resource-group" not in resource_types:
        resource_types = ("resource-group", *resource_types)
    store = PostgresInventorySnapshotStore(
        config=PostgresInventorySnapshotStoreConfig(
            dsn=config.dsn,
            freshness_budget_seconds=config.freshness_budget_seconds,
        )
    )
    started = datetime.now(tz=UTC)
    async with httpx.AsyncClient() as client:
        identity = ManagedIdentityWorkloadIdentity(http_client=client)
        sources: list[InventorySource] = []
        for source_priority, source_name in enumerate(config.source_order):
            observation = InventoryObservationKind.OBSERVED
            link_types: tuple[str, ...] = ("contains", "attached_to", "depends_on")
            inventory: Inventory
            if source_name == "arg":
                query = AzureArgQueryFactory(
                    identity=identity,
                    resource_types=vocabulary,
                    http_client=client,
                    config=AzureArgQueryFactoryConfig(
                        subscription_scopes=config.scopes,
                        arg_endpoint=config.management_endpoint,
                        audience=config.management_audience,
                    ),
                ).build_query_fn()
                inventory = AzureResourceGraphInventory(
                    config=AzureInventoryConfig(resource_types=resource_types), query=query
                )
            elif source_name == "arm":
                link_types = ("contains",)
                query = AzureArmInventoryFactory(
                    identity=identity,
                    resource_types=vocabulary,
                    http_client=client,
                    config=AzureArmInventoryFactoryConfig(
                        subscription_scopes=config.scopes,
                        arm_endpoint=config.management_endpoint,
                        audience=config.management_audience,
                    ),
                ).build_query_fn()
                inventory = AzureResourceGraphInventory(
                    config=AzureInventoryConfig(resource_types=resource_types), query=query
                )
            else:
                if config.declarative_path is None or config.declarative_sha256 is None:
                    raise ValueError("declarative fallback is missing its signed fixture")
                _verify_sha256(config.declarative_path, config.declarative_sha256)
                inventory = DeclarativeInventory(
                    DeclarativeInventoryConfig(
                        fixture_path=config.declarative_path,
                        known_resource_types=frozenset(vocabulary.ids()),
                        known_link_types=frozenset({"contains", "attached_to", "depends_on"}),
                    )
                )
                observation = InventoryObservationKind.EXPECTED
            sources.append(
                InventorySource(
                    name=source_name,
                    inventory=inventory,
                    manifest=InventoryCoverageManifest(
                        source=source_name,
                        scopes=config.scopes,
                        resource_types=resource_types,
                        observation_kind=observation,
                        started_at=started,
                        metadata={
                            "source_priority": source_priority,
                            "link_types": link_types,
                        },
                    ),
                )
            )
        result = await InventorySyncCoordinator(store=store).run(sources)
        if config.recovery_delta_enabled:
            await _forward_recovery_deltas(
                config=config,
                identity=identity,
                vocabulary=vocabulary,
                http_client=client,
            )
    await _project_security_assessment(config=config, source=result.source)
    return result.source


async def _project_security_assessment(*, config: InventoryJobConfig, source: str) -> None:
    if source not in {"arg", "arm"}:
        return
    from fdai.delivery.azure.security_assessment_projection import (
        project_azure_security_assessment,
    )
    from fdai.delivery.persistence.postgres_report_signal import (
        PostgresReportSignalStore,
        PostgresReportSignalStoreConfig,
    )
    from fdai.delivery.persistence.postgres_security_inventory import (
        PostgresSecurityInventoryReader,
    )

    snapshot_config = PostgresInventorySnapshotStoreConfig(
        dsn=config.dsn,
        freshness_budget_seconds=config.freshness_budget_seconds,
    )
    try:
        count = await project_azure_security_assessment(
            reader=PostgresSecurityInventoryReader(config=snapshot_config),
            writer=PostgresReportSignalStore(
                config=PostgresReportSignalStoreConfig(dsn=config.dsn)
            ),
            assessed_at=datetime.now(tz=UTC),
        )
    except Exception:  # noqa: BLE001 - optional read-only projection is isolated
        _LOGGER.warning(
            "security_assessment_projection_failed",
            extra={"inventory_source": source},
            exc_info=True,
        )
        return
    _LOGGER.info(
        "security_assessment_projected",
        extra={"inventory_source": source, "signal_count": count},
    )


async def _forward_recovery_deltas(
    *,
    config: InventoryJobConfig,
    identity: ManagedIdentityWorkloadIdentity,
    vocabulary: ResourceTypeRegistry,
    http_client: httpx.AsyncClient,
) -> None:
    app_config = load_config_from_env()
    state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=config.dsn))
    async with EventPublisherContext(kafka=app_config.kafka) as event_bus:
        for scope in config.scopes:
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
            await forward_inventory_delta(
                inventory=delta_inventory,
                state_store=state_store,
                event_bus=event_bus,
                topic=app_config.kafka.topic_events,
                scope=scope,
            )


def _verify_sha256(path: Path, expected: str) -> None:
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


def main() -> None:
    config = InventoryJobConfig.from_env()
    source = asyncio.run(run(config))
    print(f"inventory snapshot promoted from {source}")


if __name__ == "__main__":
    main()
