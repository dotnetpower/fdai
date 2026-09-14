"""Compose analyzer inventory readers over one durable database."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from fdai.delivery.persistence import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.inventory import ResourceRecord


class AnalyzerInventoryIdentityError(RuntimeError):
    """The active inventory cannot supply unambiguous analyzer query identities."""


class AnalyzerProviderReferenceReader(Protocol):
    """Read exact provider identities from one active inventory snapshot."""

    async def read_active_resources(
        self,
        *,
        resource_ids: tuple[str, ...],
    ) -> tuple[str | None, Mapping[str, ResourceRecord]]: ...


@dataclass(frozen=True, slots=True)
class AnalyzerInventorySources:
    """Logical projection and exact provider-reference reader for one database."""

    projection: PostgresOntologyInstanceStore
    provider_references: PostgresInventorySnapshotStore


def build_analyzer_inventory_sources(dsn: str) -> AnalyzerInventorySources | None:
    """Bind both analyzer inventory views, or ``None`` when no DSN is supplied."""

    normalized_dsn = dsn.strip().replace(
        "postgresql+psycopg://",
        "postgresql://",
        1,
    )
    if not normalized_dsn:
        return None
    catalog_root = repo_asset_root() / "rule-catalog"
    catalog = load_ontology_catalog(
        catalog_root,
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=catalog_root / "probes",
    )
    return AnalyzerInventorySources(
        projection=PostgresOntologyInstanceStore(
            config=PostgresOntologyInstanceStoreConfig(dsn=normalized_dsn),
            object_types=catalog.object_types,
            link_types=catalog.link_types,
        ),
        provider_references=PostgresInventorySnapshotStore(
            config=PostgresInventorySnapshotStoreConfig(dsn=normalized_dsn)
        ),
    )


async def read_provider_query_references(
    reader: AnalyzerProviderReferenceReader | None,
    *,
    expected_resource_types: Mapping[str, str],
) -> dict[str, str]:
    """Resolve exact query identities without projecting them into findings."""

    resource_ids = tuple(sorted(expected_resource_types))
    if not resource_ids:
        return {}
    if reader is None:
        raise AnalyzerInventoryIdentityError(
            "active inventory provider identity reader is unavailable"
        )
    try:
        snapshot_id, resources = await reader.read_active_resources(resource_ids=resource_ids)
    except Exception as exc:  # noqa: BLE001 - identity ambiguity MUST retry the tick
        raise AnalyzerInventoryIdentityError(
            f"active inventory provider identity read failed: {type(exc).__name__}"
        ) from exc
    if snapshot_id is None:
        raise AnalyzerInventoryIdentityError(
            "active inventory provider identity snapshot is unavailable"
        )

    provider_query_refs: dict[str, str] = {}
    for resource_id in resource_ids:
        resource = resources.get(resource_id)
        if (
            resource is None
            or resource.resource_id != resource_id
            or resource.type.strip() != expected_resource_types[resource_id]
            or resource.provider_ref is None
        ):
            raise AnalyzerInventoryIdentityError(
                "active inventory provider identity does not match eligible analyzer targets"
            )
        provider_query_refs[resource_id] = resource.provider_ref.strip()
    if len(set(provider_query_refs.values())) != len(provider_query_refs):
        raise AnalyzerInventoryIdentityError(
            "active inventory provider identity is ambiguous across analyzer targets"
        )
    return provider_query_refs


__all__ = [
    "AnalyzerInventoryIdentityError",
    "AnalyzerInventorySources",
    "AnalyzerProviderReferenceReader",
    "build_analyzer_inventory_sources",
    "read_provider_query_references",
]
