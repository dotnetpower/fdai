"""One-shot Azure inventory reconciliation entry point for scheduled jobs."""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from fdai.delivery.azure.arg_query import AzureArgQueryFactory, AzureArgQueryFactoryConfig
from fdai.delivery.azure.arm_inventory import (
    AzureArmInventoryFactory,
    AzureArmInventoryFactoryConfig,
)
from fdai.delivery.azure.inventory import AzureInventoryConfig, AzureResourceGraphInventory
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.inventory_sync import InventorySyncCoordinator
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.shared.providers.declarative_inventory import (
    DeclarativeInventory,
    DeclarativeInventoryConfig,
)
from fdai.shared.providers.inventory import Inventory
from fdai.shared.providers.inventory_snapshot import (
    InventoryCoverageManifest,
    InventoryObservationKind,
    InventorySource,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


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
                        metadata={"source_priority": source_priority},
                    ),
                )
            )
        result = await InventorySyncCoordinator(store=store).run(sources)
    return result.source


def _verify_sha256(path: Path, expected: str) -> None:
    if len(expected) != 64 or any(char not in "0123456789abcdefABCDEF" for char in expected):
        raise ValueError("declarative SHA256 MUST be 64 hexadecimal characters")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual.lower() != expected.lower():
        raise ValueError("declarative inventory SHA256 does not match")


def _csv(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))


def main() -> None:
    config = InventoryJobConfig.from_env()
    source = asyncio.run(run(config))
    print(f"inventory snapshot promoted from {source}")


if __name__ == "__main__":
    main()
