"""Read committed generation-specific Resource delivery without provider I/O."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.inventory_configuration_events import (
    INVENTORY_CONFIGURATION_DELIVERY_PREFIX,
    configuration_delivery_key,
    configuration_delivery_pending,
    configuration_delivery_record,
    configuration_projection_record,
)
from fdai.delivery.inventory_sync_models import PromotedInventoryObservation
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.inventory import ResourceRecord


def verified_delivery_observation(
    *,
    key: str,
    pending: Mapping[str, Any],
    publication: Mapping[str, Any],
    recorded_at: datetime | None,
    resources: Sequence[ResourceRecord],
) -> PromotedInventoryObservation:
    generation = pending.get("generation")
    if (
        not isinstance(generation, str)
        or key != configuration_delivery_key(generation)
        or not configuration_delivery_pending(pending, generation=generation)
        or recorded_at is None
        or recorded_at.tzinfo is None
        or len(resources) > 50_000
        or len({record.resource_id for record in resources}) != len(resources)
    ):
        raise ValueError("inventory delivery recovery identity is invalid")
    observation = PromotedInventoryObservation(
        generation=generation,
        resources=tuple(resources),
        links=(),
        complete=True,
        recorded_at=recorded_at,
    )
    expected_publication = configuration_projection_record(
        observation,
        ontology_release_digest=str(publication.get("ontology_release_digest", "")),
        manifest_digest=str(publication.get("manifest_digest", "")),
    )
    if (
        pending != configuration_delivery_record(observation)
        or publication != expected_publication
        or publication.get("execution_authority") is not False
        or type(publication.get("resource_count")) is not int
    ):
        raise ValueError("inventory delivery recovery content is not the committed observation")
    if any(record.props.get("_truncated") is True for record in resources):
        raise ValueError("inventory delivery recovery contains truncated properties")
    return observation


class PostgresInventoryDeliveryReader:
    """Recover the oldest pending generation only after its atomic graph publication."""

    def __init__(
        self, *, config: PostgresInventorySnapshotStoreConfig, scope_refs: tuple[str, ...]
    ) -> None:
        if not scope_refs or any(not value or value != value.strip() for value in scope_refs):
            raise ValueError("inventory delivery recovery requires exact configured scopes")
        self._config = config
        self._scope_refs = tuple(sorted(set(scope_refs)))

    async def load_next(self) -> PromotedInventoryObservation | None:
        async with asyncio.timeout(30):
            async with await psycopg.AsyncConnection.connect(
                self._config.dsn,
                row_factory=dict_row,
                connect_timeout=self._config.connect_timeout_s,
            ) as connection:
                await connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._config.statement_timeout_ms),),
                )
                cursor = await connection.execute(
                    "SELECT delivery.key, delivery.value AS pending, "
                    "publication.value AS publication, "
                    "snapshot.completed_at, snapshot.scopes "
                    "FROM state_kv delivery JOIN state_kv publication "
                    "ON publication.key=delivery.key || ':projection' "
                    "LEFT JOIN inventory_snapshot snapshot "
                    "ON snapshot.id=delivery.value->>'generation' "
                    "WHERE starts_with(delivery.key, %s) AND delivery.value->>'status'='pending' "
                    "ORDER BY delivery.updated_at, delivery.key LIMIT 1",
                    (INVENTORY_CONFIGURATION_DELIVERY_PREFIX,),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                scopes = row["scopes"]
                if (
                    not isinstance(scopes, list)
                    or any(not isinstance(value, str) for value in scopes)
                    or tuple(sorted(scopes)) != self._scope_refs
                ):
                    raise ValueError("inventory delivery recovery scope changed")
                pending = row["pending"]
                publication = row["publication"]
                if not isinstance(pending, Mapping) or not isinstance(publication, Mapping):
                    raise ValueError("inventory delivery recovery record is malformed")
                cursor = await connection.execute(
                    "SELECT resource_id, resource_type, props, provider_ref, last_seen "
                    "FROM inventory_snapshot_resource WHERE snapshot_id=%s "
                    "ORDER BY resource_id LIMIT 50001",
                    (pending.get("generation"),),
                )
                resources = tuple(
                    ResourceRecord(
                        resource_id=str(item["resource_id"]),
                        type=str(item["resource_type"]),
                        props=item["props"],
                        provider_ref=item["provider_ref"],
                        last_seen=(
                            item["last_seen"].isoformat() if item["last_seen"] is not None else None
                        ),
                    )
                    for item in await cursor.fetchall()
                )
        return verified_delivery_observation(
            key=str(row["key"]),
            pending=pending,
            publication=publication,
            recorded_at=row["completed_at"],
            resources=resources,
        )
