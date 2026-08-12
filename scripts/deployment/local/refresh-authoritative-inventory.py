#!/usr/bin/env python3
"""Refresh local inventory from Azure Resource Graph without synthetic data."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
import yaml
from fdai.delivery.azure.arg_query import (
    AzureArgQueryFactory,
    AzureArgQueryFactoryConfig,
)
from fdai.delivery.azure.dev_workload_identity import AzureCliWorkloadIdentity
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.inventory import AzureInventoryConfig, AzureResourceGraphInventory
from fdai.delivery.inventory_sync import InventorySyncCoordinator, PromotedInventoryObservation
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
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.runtime.inventory_ontology import (
    InventoryOntologyProjectionResult,
    InventoryOntologyProjector,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.inventory_snapshot import (
    InventoryCoverageManifest,
    InventoryObservationKind,
    InventorySource,
    InventorySourcesExhaustedError,
)
from fdai.shared.providers.workload_identity import IdentityToken
from fdai_service_contracts import OperationalActivityStatus, OperationalFreshness
from psycopg.rows import dict_row

REPO_ROOT = Path(__file__).resolve().parents[3]


class AsyncAzureCliIdentity:
    """Adapt the dev-only synchronous Azure CLI identity to async provider I/O."""

    def __init__(self) -> None:
        self._identity = AzureCliWorkloadIdentity.from_env()

    async def get_token(self, audience: str) -> IdentityToken:
        """Acquire one cached, audience-scoped token without blocking the event loop."""
        return await asyncio.to_thread(self._identity.get_token_sync, audience)


async def refresh() -> InventoryOntologyProjectionResult:
    """Promote one complete ARG snapshot and its derived ontology subgraph."""
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
    if not dsn:
        raise RuntimeError("FDAI_STATE_STORE_DSN MUST be configured")
    if not subscription_id:
        raise RuntimeError("AZURE_SUBSCRIPTION_ID MUST be configured")

    registry = PackageResourceSchemaRegistry()
    catalog_root = REPO_ROOT / "rule-catalog"
    ontology = load_ontology_catalog(
        catalog_root,
        schema_registry=registry,
        probes_root=catalog_root / "probes",
    )
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (catalog_root / "vocabulary/resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    query_types = tuple(item.id for item in resource_types if item.azure_arm_type is not None)

    ontology_store = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(dsn=dsn),
        object_types=ontology.object_types,
        link_types=ontology.link_types,
    )
    await ontology_store.sync_catalog()
    state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    projector = InventoryOntologyProjector(store=ontology_store, status_store=state_store)
    snapshot_store = PostgresInventorySnapshotStore(
        config=PostgresInventorySnapshotStoreConfig(dsn=dsn)
    )
    projected: InventoryOntologyProjectionResult | None = None
    evidence_counts: dict[str, int] = {}
    event_bus = EventHubsKafkaBus(
        identity=None,
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip(),
            security_protocol="PLAINTEXT",
            client_id="fdai-local-inventory-refresh",
        ),
    )
    activity_publisher = EventBusOperationalActivityPublisher(
        event_bus=event_bus,
        topic=os.environ.get("FDAI_STAGE_TOPIC", "aw.pipeline.stages").strip(),
    )
    observed_store = ObservedInventorySnapshotStore(
        store=snapshot_store,
        publisher=activity_publisher,
    )

    async def project(observation: PromotedInventoryObservation) -> None:
        nonlocal projected
        evidence_counts[observation.generation] = len(observation.resources) + len(
            observation.links
        )
        projected = await projector.apply(observation)
        available = projected.status.value == "available"
        await activity_publisher.publish(
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
                evidence_count=projected.object_count + projected.link_count,
                reason_codes=projected.dropped_reasons,
            )
        )

    try:
        async with httpx.AsyncClient() as client:
            query = AzureArgQueryFactory(
                identity=AsyncAzureCliIdentity(),
                resource_types=resource_types,
                http_client=client,
                config=AzureArgQueryFactoryConfig(subscription_scopes=(subscription_id,)),
            ).build_query_fn()
            inventory = AzureResourceGraphInventory(
                config=AzureInventoryConfig(
                    resource_types=query_types,
                    subscription_scopes=(subscription_id,),
                ),
                query=query,
            )
            source = InventorySource(
                name="azure-resource-graph",
                inventory=inventory,
                manifest=InventoryCoverageManifest(
                    source="azure-resource-graph",
                    scopes=("configured-subscription",),
                    resource_types=query_types,
                    observation_kind=InventoryObservationKind.OBSERVED,
                    started_at=datetime.now(UTC),
                    metadata={
                        "credential": "azure-cli",
                        "synthetic": False,
                        "link_types": (
                            "contains",
                            "attached_to",
                            "depends_on",
                            "peered_with",
                            "routes_to",
                        ),
                    },
                ),
            )
            result = await InventorySyncCoordinator(
                store=observed_store,
                promotion_observer=project,
            ).run((source,))
            active_snapshot_id = await snapshot_store.active_snapshot_id()
            if active_snapshot_id is None:
                raise RuntimeError("inventory promotion completed without a durable active pointer")
            await observed_store.publish_terminal(
                attempt_id=result.attempt_id,
                source=result.source,
                active=active_snapshot_id == result.attempt_id,
                evidence_count=evidence_counts.get(result.attempt_id, 0),
            )
    finally:
        await event_bus.close()

    if projected is None:
        raise RuntimeError("inventory snapshot promoted without ontology projection evidence")
    await _write_operator_inventory_projection(dsn=dsn, state_store=state_store)
    return projected


async def _write_operator_inventory_projection(
    *,
    dsn: str,
    state_store: PostgresStateStore,
) -> None:
    """Materialize one bounded authenticated graph from the promoted snapshot."""
    normalized_dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    async with await psycopg.AsyncConnection.connect(
        normalized_dsn,
        row_factory=dict_row,
        connect_timeout=10,
    ) as connection:
        snapshot_cursor = await connection.execute(
            "SELECT s.id, s.completed_at FROM inventory_active a "
            "JOIN inventory_snapshot s ON s.id=a.snapshot_id WHERE a.singleton=TRUE"
        )
        snapshot = await snapshot_cursor.fetchone()
        if snapshot is None:
            raise RuntimeError("active inventory snapshot is unavailable")
        resource_cursor = await connection.execute(
            "SELECT resource_id, resource_type, props FROM inventory_snapshot_resource "
            "WHERE snapshot_id=%s ORDER BY resource_id LIMIT 1001",
            (snapshot["id"],),
        )
        resource_rows = list(await resource_cursor.fetchall())
        link_cursor = await connection.execute(
            "SELECT from_id, link_type, to_id FROM inventory_snapshot_link "
            "WHERE snapshot_id=%s AND link_type=ANY(%s::text[]) "
            "ORDER BY from_id, link_type, to_id LIMIT 8001",
            (snapshot["id"], ["contains", "attached_to", "depends_on", "peered_with"]),
        )
        link_rows = list(await link_cursor.fetchall())

    payload = _operator_inventory_payload(
        snapshot_at=snapshot["completed_at"],
        resource_rows=resource_rows,
        link_rows=link_rows,
    )
    await state_store.write_state("operator-projection:operations:inventory.graph", payload)


def _operator_inventory_payload(
    *,
    snapshot_at: datetime,
    resource_rows: list[dict[str, object]],
    link_rows: list[dict[str, object]],
) -> dict[str, object]:
    """Build the bounded Console graph from one promoted authoritative snapshot."""
    truncated = len(resource_rows) > 1000 or len(link_rows) > 8000
    resource_rows = resource_rows[:1000]
    link_rows = link_rows[:8000]
    resource_ids = {str(row["resource_id"]) for row in resource_rows}
    parents = {
        str(row["to_id"]): str(row["from_id"])
        for row in link_rows
        if row["link_type"] == "contains"
        and str(row["from_id"]) in resource_ids
        and str(row["to_id"]) in resource_ids
    }
    resources: list[dict[str, object]] = []
    for row in resource_rows:
        resource_id = str(row["resource_id"])
        raw_props = row["props"]
        props = raw_props if isinstance(raw_props, dict) else json.loads(str(raw_props))
        name = props.get("name")
        status = props.get("status")
        resources.append(
            {
                "id": resource_id,
                "type": str(row["resource_type"]),
                "name": name if isinstance(name, str) and name else resource_id.rsplit("/", 1)[-1],
                "status": status if isinstance(status, str) and status else "unknown",
                **({"parent_id": parents[resource_id]} if resource_id in parents else {}),
            }
        )
    links = [
        {
            "source": str(row["from_id"]),
            "target": str(row["to_id"]),
            "type": str(row["link_type"]),
        }
        for row in link_rows
        if str(row["from_id"]) in resource_ids and str(row["to_id"]) in resource_ids
    ]
    return {
        "snapshot_at": snapshot_at.astimezone(UTC).isoformat(),
        "freshness": "fresh",
        "source": "azure-cli-local",
        "scope": None,
        "root": None,
        "depth": 8,
        "limit": 1000,
        "included_link_types": ["contains", "attached_to", "depends_on", "peered_with"],
        "resources": resources,
        "links": links,
        "truncated": truncated,
        "truncation_reasons": ["resource_or_link_cap"] if truncated else [],
        "cursor": None,
        "cache": {"status": "fresh", "age_seconds": 0, "persistent": True},
        "realtime": {"pending_changes": 0, "latest_at": None},
        "views": [],
    }


def main() -> int:
    """Run one authoritative local refresh and print only aggregate evidence."""
    try:
        result = asyncio.run(refresh())
    except InventorySourcesExhaustedError as exc:
        codes = ",".join(sorted({failure.code.value for failure in exc.failures}))
        print(f"authoritative local inventory unavailable: {codes or 'source_unavailable'}")
        return 0
    print(
        "authoritative local inventory refreshed: "
        f"resources={result.object_count} links={result.link_count} complete={result.complete}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
