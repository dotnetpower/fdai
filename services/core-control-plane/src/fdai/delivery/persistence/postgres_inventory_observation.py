"""PostgreSQL dual-write adapter for normalized inventory observations."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.inventory_configuration_events import (
    INVENTORY_CONFIGURATION_DELIVERY_KEY,
    configuration_delivery_key,
    configuration_delivery_pending,
)
from fdai.delivery.inventory_semantic_digest import inventory_semantic_digest
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.persistence.postgres_inventory_observation_records import (
    confirmed_tombstone as _confirmed_tombstone,
)
from fdai.delivery.persistence.postgres_inventory_observation_records import mapping as _mapping
from fdai.delivery.persistence.postgres_inventory_observation_records import (
    observation_from_row as _observation,
)
from fdai.delivery.persistence.postgres_inventory_observation_records import (
    observation_params,
)
from fdai.delivery.persistence.postgres_inventory_observation_records import (
    snapshot_records as _snapshot_records,
)
from fdai.delivery.persistence.postgres_inventory_observation_write import (
    _INSERT_OBSERVATION_SQL as _WRITE_INSERT_OBSERVATION_SQL,
)
from fdai.delivery.persistence.postgres_inventory_observation_write import (
    INVENTORY_OBSERVATION_WATERMARK_KEY,
    InventoryObservationAppendResult,
)
from fdai.delivery.persistence.postgres_inventory_observation_write import (
    append_records as _append_records,
)
from fdai.delivery.persistence.postgres_inventory_observation_write import (
    update_watermark_state as _update_watermark_state,
)
from fdai.delivery.persistence.postgres_inventory_projection_checkpoints import (
    active_scope_projection_watermark as _active_scope_projection_watermark,
)
from fdai.delivery.persistence.postgres_inventory_projection_checkpoints import (
    global_projection_watermark as _global_projection_watermark,
)
from fdai.delivery.persistence.postgres_inventory_projection_replay import (
    MAX_ACTIVE_PROJECTION_OBSERVATIONS,
    InventoryProjectionReplayInput,
    build_projection_replay_observation,
    projection_freshness_ceiling,
    projection_replay_drops,
)
from fdai.delivery.persistence.postgres_inventory_projection_replay import (
    manifest_watermarks as _manifest_watermarks,
)
from fdai.delivery.persistence.postgres_inventory_projection_replay import (
    nonnegative_watermark as _nonnegative_int,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    _PROMOTION_LOCK,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_observation_lifecycle import (
    bind_observation_lifecycle,
    close_observation_corrections,
)
from fdai.shared.providers.inventory import (
    LinkRecord,
    RelationshipDrop,
    RelationshipDropReason,
    ResourceRecord,
)
from fdai.shared.providers.inventory_observation import (
    InventoryObservationKind,
    InventoryObservationSubjectKind,
    NormalizedInventoryObservation,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
)

_INSERT_OBSERVATION_SQL = _WRITE_INSERT_OBSERVATION_SQL
_observation_params = observation_params
_MAX_REPLAY_OBSERVATIONS = 4096
_MAX_CHANGE_BATCH = 1024


@dataclass(frozen=True, slots=True)
class InventorySnapshotObservationAppendResult:
    """Global retention and active-scope graph checkpoints for one promoted snapshot."""

    journal_high_watermark: int
    projection_high_watermark: int
    active_scope_projection_watermark: int | None = None
    active_scope_refs: tuple[str, ...] = ()
    reused_journal_generation: str | None = None


class PostgresInventoryObservationJournal:
    """Append immutable observations and maintain rebuildable shadow projections."""

    def __init__(
        self,
        *,
        config: PostgresInventorySnapshotStoreConfig,
        allow_oi16_synthetic: bool = False,
    ) -> None:
        self._config = config
        self._allow_oi16_synthetic = allow_oi16_synthetic

    async def append_change(
        self,
        connection: psycopg.AsyncConnection[Any],
        observations: Sequence[NormalizedInventoryObservation],
    ) -> InventoryObservationAppendResult:
        """Append one normalized change inside the caller's overlay transaction."""

        result = await _append_records(connection, observations)
        replayed = await bind_observation_lifecycle(
            connection,
            observations,
            allow_oi16_synthetic=self._allow_oi16_synthetic,
        )
        for item in observations:
            if (
                item.subject_kind is InventoryObservationSubjectKind.OBJECT
                and item.observation_kind is InventoryObservationKind.TOMBSTONE
                and not item.tombstone_confirmed
                and item.observation_id not in replayed
            ):
                await connection.execute(
                    "INSERT INTO inventory_observation_pending_tombstone "
                    "(resource_id, resource_type, scope_ref, observation_id, "
                    "observed_at, recorded_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (resource_id) DO UPDATE SET "
                    "resource_type=EXCLUDED.resource_type, "
                    "scope_ref=EXCLUDED.scope_ref, "
                    "observation_id=EXCLUDED.observation_id, "
                    "observed_at=EXCLUDED.observed_at, recorded_at=EXCLUDED.recorded_at "
                    "WHERE inventory_observation_pending_tombstone.observed_at "
                    "< EXCLUDED.observed_at OR ("
                    "inventory_observation_pending_tombstone.observed_at = EXCLUDED.observed_at "
                    "AND inventory_observation_pending_tombstone.observation_id "
                    "< EXCLUDED.observation_id)",
                    (
                        item.subject_ref,
                        item.subject_type,
                        item.scope_ref,
                        item.observation_id,
                        item.observed_at,
                        item.recorded_at,
                    ),
                )
        return result

    async def append_history_only(
        self,
        connection: psycopg.AsyncConnection[Any],
        observations: Sequence[NormalizedInventoryObservation],
    ) -> InventoryObservationAppendResult:
        """Append observations that a newer active snapshot already covers."""

        return await _append_records(connection, observations)

    async def append_change_batch(
        self,
        observations: Sequence[NormalizedInventoryObservation],
    ) -> InventoryObservationAppendResult:
        """Append one bounded normalized change inside its own transaction.

        :meth:`append_change` deliberately joins the caller's overlay transaction. A
        caller that owns no overlay still MUST NOT reach the journal tables directly,
        so this method opens exactly one transaction and delegates every write and
        every replay check to the same append path the overlay uses.
        """

        if len(observations) > _MAX_CHANGE_BATCH:
            raise ValueError("inventory observation change batch exceeds its bound")
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                return await self.append_change(connection, observations)

    async def mark_overlay_projected(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        watermark: int,
    ) -> None:
        await _update_watermark_state(connection, overlay_watermark=watermark)

    async def load_object_observations(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        resource_id: str,
        after: datetime,
    ) -> tuple[NormalizedInventoryObservation, ...]:
        cursor = await connection.execute(
            _SELECT_OBSERVATIONS
            + " WHERE subject_kind='object' AND subject_ref=%s AND effective_at>%s "
            "ORDER BY effective_at, "
            "(observation_kind='tombstone')::int, source_event_id, content_digest "
            "LIMIT %s",
            (resource_id, after, _MAX_REPLAY_OBSERVATIONS + 1),
        )
        rows = await cursor.fetchall()
        if len(rows) > _MAX_REPLAY_OBSERVATIONS:
            raise ValueError("inventory observation replay exceeds its per-resource bound")
        return tuple(_observation(row) for row in rows)

    async def load_active_projection_replay(
        self,
        *,
        journal_high_watermark: int | None = None,
        projection_high_watermark: int | None = None,
    ) -> InventoryProjectionReplayInput:
        """Rebuild the active observation at an optional monotonic journal fence."""

        if (journal_high_watermark is None) != (projection_high_watermark is None):
            raise ValueError("inventory projection replay watermarks MUST be supplied together")

        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute(
                    "SELECT pg_advisory_xact_lock_shared(%s)", (_PROMOTION_LOCK,)
                )
                snapshot_cursor = await connection.execute(
                    "SELECT s.id, s.completed_at, s.metadata "
                    "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                    "WHERE a.singleton=TRUE AND s.status='active'"
                )
                snapshot = await snapshot_cursor.fetchone()
                if snapshot is None or snapshot["completed_at"] is None:
                    raise ValueError("active inventory snapshot is unavailable for replay")
                generation = str(snapshot["id"])
                metadata = dict(_mapping(snapshot["metadata"]))
                journal_generation = str(metadata.get("journal_source_generation") or generation)
                cursor = await connection.execute(
                    _SELECT_OBSERVATIONS + " WHERE source_identity='inventory.reconciliation' "
                    "AND source_revision=%s AND source_event_id=%s "
                    "AND observation_kind='full' AND mutation_kind='upsert' "
                    "ORDER BY subject_kind, subject_ref "
                    "LIMIT %s",
                    (
                        journal_generation,
                        f"snapshot:{journal_generation}",
                        MAX_ACTIVE_PROJECTION_OBSERVATIONS + 1,
                    ),
                )
                rows = await cursor.fetchall()
                if len(rows) > MAX_ACTIVE_PROJECTION_OBSERVATIONS:
                    raise ValueError("active inventory projection replay exceeds its bound")
                state_cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key=%s",
                    (INVENTORY_OBSERVATION_WATERMARK_KEY,),
                )
                state_row = await state_cursor.fetchone()
                manifest_cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key='inventory-ontology:manifest'"
                )
                manifest_row = await manifest_cursor.fetchone()
        if not rows:
            raise ValueError("active inventory snapshot has no replayable journal records")
        state = _mapping(state_row["value"]) if state_row is not None else {}
        if manifest_row is None:
            raise ValueError("inventory projection replay manifest is unavailable")
        manifest = _mapping(manifest_row["value"])
        if manifest.get("generation") != generation:
            raise ValueError("inventory projection replay manifest generation changed")
        observation = build_projection_replay_observation(
            generation=generation,
            recorded_at=snapshot["completed_at"],
            metadata=metadata,
            prior_manifest=manifest,
            records=tuple(_observation(row) for row in rows),
        )
        prior_journal_watermark, prior_projection_watermark = _manifest_watermarks(manifest)
        target_journal_watermark = (
            prior_journal_watermark if journal_high_watermark is None else journal_high_watermark
        )
        target_projection_watermark = (
            prior_projection_watermark
            if projection_high_watermark is None
            else projection_high_watermark
        )
        if target_projection_watermark > target_journal_watermark:
            raise ValueError("inventory projection replay watermark exceeds journal")
        if (
            target_journal_watermark < prior_journal_watermark
            or target_projection_watermark < prior_projection_watermark
        ):
            raise ValueError("inventory projection replay watermark regressed")
        if target_journal_watermark > _nonnegative_int(state.get("journal_high_watermark")) or (
            prior_projection_watermark
            > _nonnegative_int(state.get("ontology_projection_watermark"))
        ):
            raise ValueError("inventory projection replay manifest exceeds live watermarks")
        state_generation = state.get("ontology_generation")
        legacy_bootstrap = (
            state_generation is None
            and journal_high_watermark is not None
            and prior_journal_watermark == 0
            and prior_projection_watermark == 0
        )
        if state_generation != generation and not legacy_bootstrap:
            raise ValueError("inventory projection replay generation is not durably fenced")
        return InventoryProjectionReplayInput(
            observation=observation,
            journal_high_watermark=target_journal_watermark,
            projection_high_watermark=target_projection_watermark,
            freshness_ceiling_seconds=projection_freshness_ceiling(manifest),
        )

    async def load_pending_promoted_snapshot(self) -> PromotedInventoryObservation | None:
        """Rebuild an active generation whose ontology projection did not complete."""

        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute(
                    "SELECT pg_advisory_xact_lock_shared(%s)", (_PROMOTION_LOCK,)
                )
                snapshot_cursor = await connection.execute(
                    "SELECT s.id, s.completed_at, s.metadata "
                    "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                    "WHERE a.singleton=TRUE AND s.status='active'"
                )
                snapshot = await snapshot_cursor.fetchone()
                if snapshot is None or snapshot["completed_at"] is None:
                    return None
                metadata = _mapping(snapshot["metadata"])
                generation = str(snapshot["id"])
                state_cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key=%s",
                    (INVENTORY_OBSERVATION_WATERMARK_KEY,),
                )
                state_row = await state_cursor.fetchone()
                state = _mapping(state_row["value"]) if state_row is not None else {}
                manifest_cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key='inventory-ontology:manifest'"
                )
                manifest_row = await manifest_cursor.fetchone()
                manifest = _mapping(manifest_row["value"]) if manifest_row is not None else {}
                delivery_cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key=%s",
                    (INVENTORY_CONFIGURATION_DELIVERY_KEY,),
                )
                delivery_row = await delivery_cursor.fetchone()
                delivery_pending = delivery_row is not None and configuration_delivery_pending(
                    _mapping(delivery_row["value"]), generation=generation
                )
                if "state_base_generation" not in metadata and not delivery_pending:
                    return None
                if state.get("ontology_generation") == generation:
                    if manifest.get("generation") != generation:
                        raise ValueError("inventory ontology completion fence is inconsistent")
                    if not delivery_pending:
                        return None
                elif manifest.get("generation") == generation:
                    raise ValueError(
                        "inventory ontology manifest advanced without its atomic watermark"
                    )
                else:
                    metadata = _rebase_recovery_metadata(metadata, manifest)
                resource_cursor = await connection.execute(
                    "SELECT resource_id, resource_type, props, provider_ref, last_seen "
                    "FROM inventory_snapshot_resource WHERE snapshot_id=%s "
                    "ORDER BY resource_id LIMIT %s",
                    (generation, MAX_ACTIVE_PROJECTION_OBSERVATIONS + 1),
                )
                resource_rows = await resource_cursor.fetchall()
                link_cursor = await connection.execute(
                    "SELECT from_id, from_type, link_type, to_id, to_type, props "
                    "FROM inventory_snapshot_link WHERE snapshot_id=%s "
                    "ORDER BY from_id, link_type, to_id LIMIT %s",
                    (generation, MAX_ACTIVE_PROJECTION_OBSERVATIONS + 1),
                )
                link_rows = await link_cursor.fetchall()
        prior_manifest = manifest or {"object_content": [], "dropped_reasons": []}
        return _snapshot_recovery_observation(
            generation=generation,
            recorded_at=snapshot["completed_at"],
            metadata=metadata,
            prior_manifest=prior_manifest,
            resource_rows=resource_rows,
            link_rows=link_rows,
        )

    async def append_promoted_snapshot(
        self,
        observation: PromotedInventoryObservation,
    ) -> InventorySnapshotObservationAppendResult:
        """Dual-write one promoted full snapshot and confirm covered tombstones."""

        if not observation.complete:
            raise ValueError("incomplete inventory observation cannot confirm a snapshot")
        if any(resource.props.get("_truncated") is True for resource in observation.resources):
            raise ValueError("truncated inventory properties cannot confirm a full snapshot")
        if observation.recorded_at is None:
            raise ValueError("promoted inventory observation recorded_at MUST be supplied")
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute("SELECT pg_advisory_xact_lock(%s)", (_PROMOTION_LOCK,))
                snapshot_cursor = await connection.execute(
                    "SELECT s.id, s.source, s.observation_kind, s.started_at, s.scopes, "
                    "s.resource_types, s.metadata "
                    "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                    "WHERE a.singleton=TRUE AND s.status='active' AND s.id=%s",
                    (observation.generation,),
                )
                snapshot = await snapshot_cursor.fetchone()
                if snapshot is None:
                    raise ValueError("promoted inventory observation is not the active snapshot")
                metadata = dict(_mapping(snapshot["metadata"]))
                semantic_digest = inventory_semantic_digest(observation)
                reused_journal_generation = await _reusable_journal_generation(
                    connection,
                    snapshot=snapshot,
                    semantic_digest=semantic_digest,
                )
                journal_source_generation = reused_journal_generation or observation.generation
                metadata["semantic_content_digest"] = semantic_digest
                metadata["journal_source_generation"] = journal_source_generation
                await connection.execute(
                    "UPDATE inventory_snapshot SET metadata=%s::jsonb WHERE id=%s",
                    (json.dumps(metadata, sort_keys=True), observation.generation),
                )
                records = (
                    ()
                    if reused_journal_generation is not None
                    else _snapshot_records(
                        observation,
                        scope_refs=tuple(str(value) for value in snapshot["scopes"]),
                    )
                )
                result = await _append_records(connection, records)
                await bind_observation_lifecycle(
                    connection,
                    records,
                    allow_oi16_synthetic=self._allow_oi16_synthetic,
                )
                high_watermark = result.high_watermark
                covered_types = tuple(str(value) for value in snapshot["resource_types"])
                if metadata.get("coverage_scope") == "full_provider_scope":
                    pending_cursor = await connection.execute(
                        "SELECT resource_id, resource_type, scope_ref, "
                        "observation_id, observed_at "
                        "FROM inventory_observation_pending_tombstone "
                        "WHERE scope_ref=ANY(%s::text[]) "
                        "AND resource_type=ANY(%s::text[]) AND observed_at<=%s "
                        "ORDER BY resource_id",
                        (
                            list(snapshot["scopes"]),
                            list(covered_types),
                            snapshot["started_at"],
                        ),
                    )
                    pending = await pending_cursor.fetchall()
                    present = {item.resource_id for item in observation.resources}
                    confirmations = tuple(
                        _confirmed_tombstone(
                            row,
                            generation=observation.generation,
                            confirmed_at=snapshot["started_at"],
                            recorded_at=observation.recorded_at,
                        )
                        for row in pending
                        if str(row["resource_id"]) not in present
                    )
                    if confirmations:
                        confirmed = await _append_records(connection, confirmations)
                        await bind_observation_lifecycle(
                            connection,
                            confirmations,
                            allow_oi16_synthetic=self._allow_oi16_synthetic,
                        )
                        high_watermark = max(high_watermark, confirmed.high_watermark)
                    if pending:
                        await connection.execute(
                            "DELETE FROM inventory_observation_pending_tombstone "
                            "WHERE scope_ref=ANY(%s::text[]) "
                            "AND resource_type=ANY(%s::text[]) AND observed_at<=%s",
                            (
                                list(snapshot["scopes"]),
                                list(covered_types),
                                snapshot["started_at"],
                            ),
                        )
                high_watermark = max(
                    high_watermark,
                    await _retained_generation_watermark(
                        connection,
                        generation=observation.generation,
                    ),
                )
                await _update_watermark_state(
                    connection,
                    journal_watermark=high_watermark,
                )
                state_cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key=%s",
                    (INVENTORY_OBSERVATION_WATERMARK_KEY,),
                )
                state_row = await state_cursor.fetchone()
                state = _mapping(state_row["value"]) if state_row is not None else {}
                current_projection = _nonnegative_int(state.get("ontology_projection_watermark"))
                projection_watermark = await _global_projection_watermark(
                    connection,
                    high_watermark=high_watermark,
                    current_projection=current_projection,
                    generation=observation.generation,
                    snapshot_started_at=snapshot["started_at"],
                    scope_refs=tuple(str(value) for value in snapshot["scopes"]),
                )
                active_scope_refs = tuple(sorted(str(value) for value in snapshot["scopes"]))
                active_scope_projection_watermark = await _active_scope_projection_watermark(
                    connection,
                    high_watermark=high_watermark,
                    generation=observation.generation,
                    snapshot_started_at=snapshot["started_at"],
                    scope_refs=active_scope_refs,
                )
        return InventorySnapshotObservationAppendResult(
            journal_high_watermark=high_watermark,
            projection_high_watermark=projection_watermark,
            active_scope_projection_watermark=active_scope_projection_watermark,
            active_scope_refs=active_scope_refs,
            reused_journal_generation=reused_journal_generation,
        )

    async def mark_ontology_projected(self, *, generation: str, watermark: int) -> None:
        """Advance the ontology watermark only after its atomic graph commit."""

        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await advance_ontology_projection(
                    connection,
                    generation=generation,
                    watermark=watermark,
                )

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


async def advance_ontology_projection(
    connection: psycopg.AsyncConnection[Any],
    *,
    generation: str,
    watermark: int,
) -> None:
    """Advance the ontology fence and close covered corrections in one transaction."""

    await _update_watermark_state(
        connection,
        ontology_watermark=watermark,
        ontology_generation=generation,
    )
    await close_observation_corrections(
        connection,
        generation=generation,
        projection_watermark=watermark,
        closed_at=datetime.now(tz=UTC),
    )


async def _retained_generation_watermark(
    connection: psycopg.AsyncConnection[Any],
    *,
    generation: str,
) -> int:
    cursor = await connection.execute(
        "SELECT COALESCE(MAX(watermark), 0) AS watermark "
        "FROM inventory_observation_journal "
        "WHERE source_revision=%s AND source_event_id=%s",
        (generation, f"snapshot:{generation}"),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("inventory generation watermark is unavailable")
    return _nonnegative_int(row["watermark"])


def _snapshot_recovery_observation(
    *,
    generation: str,
    recorded_at: datetime,
    metadata: Mapping[str, Any],
    prior_manifest: Mapping[str, Any],
    resource_rows: Sequence[Mapping[str, Any]],
    link_rows: Sequence[Mapping[str, Any]],
) -> PromotedInventoryObservation:
    if len(resource_rows) + len(link_rows) > MAX_ACTIVE_PROJECTION_OBSERVATIONS:
        raise ValueError("pending inventory snapshot replay exceeds its bound")
    resources = tuple(
        ResourceRecord(
            resource_id=str(row["resource_id"]),
            type=str(row["resource_type"]),
            props=_mapping(row["props"]),
            provider_ref=str(row["provider_ref"]) if row["provider_ref"] is not None else None,
            last_seen=(row["last_seen"].isoformat() if row["last_seen"] is not None else None),
        )
        for row in resource_rows
    )
    links: list[LinkRecord] = []
    relationship_drops = list(projection_replay_drops(metadata, prior_manifest))
    for row in link_rows:
        properties = dict(_mapping(row["props"]))
        raw_observation = properties.pop(LINK_OBSERVATION_METADATA_PROPERTY, None)
        if not isinstance(raw_observation, Mapping):
            relationship_drops.append(
                RelationshipDrop(reason=RelationshipDropReason.UNVERIFIED_METADATA)
            )
            continue
        links.append(
            LinkRecord(
                from_id=str(row["from_id"]),
                from_type=str(row["from_type"]),
                link_type=str(row["link_type"]),
                to_id=str(row["to_id"]),
                to_type=str(row["to_type"]),
                link_props=properties,
                observation_metadata=LinkObservationMetadata.from_mapping(raw_observation),
            )
        )
    return PromotedInventoryObservation(
        generation=generation,
        resources=resources,
        links=tuple(links),
        complete=True,
        relationship_drops=tuple(relationship_drops),
        recorded_at=recorded_at,
        state_base_generation=(
            str(metadata["state_base_generation"])
            if metadata.get("state_base_generation") is not None
            else None
        ),
        state_base_generation_checked="state_base_generation" in metadata,
    )


async def _reusable_journal_generation(
    connection: psycopg.AsyncConnection[Any],
    *,
    snapshot: Mapping[str, Any],
    semantic_digest: str,
) -> str | None:
    cursor = await connection.execute(
        "SELECT s.id, s.metadata FROM inventory_snapshot s "
        "WHERE s.id<>%s AND s.status='superseded' AND s.source=%s "
        "AND s.observation_kind=%s AND s.scopes=%s::jsonb "
        "AND s.resource_types=%s::jsonb "
        "AND s.metadata->>'semantic_content_digest'=%s "
        "AND s.metadata->>'projection_complete'='true' "
        "ORDER BY s.completed_at DESC, s.id DESC LIMIT 1",
        (
            str(snapshot["id"]),
            str(snapshot["source"]),
            str(snapshot["observation_kind"]),
            json.dumps(snapshot["scopes"]),
            json.dumps(snapshot["resource_types"]),
            semantic_digest,
        ),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    metadata = _mapping(row["metadata"])
    prior_generation = str(row["id"])
    delivery_cursor = await connection.execute(
        "SELECT value FROM state_kv WHERE key=%s",
        (configuration_delivery_key(prior_generation),),
    )
    delivery_row = await delivery_cursor.fetchone()
    if delivery_row is None:
        return None
    delivery = _mapping(delivery_row["value"])
    configuration_delivery_pending(delivery, generation=prior_generation)
    if delivery.get("generation") != prior_generation or delivery.get("status") != "completed":
        return None
    source_generation = metadata.get("journal_source_generation") or row["id"]
    if (
        not isinstance(source_generation, str)
        or not source_generation.strip()
        or len(source_generation) > 256
    ):
        raise ValueError("inventory journal source generation is malformed")
    retained = await connection.execute(
        "SELECT 1 FROM inventory_observation_journal "
        "WHERE source_revision=%s AND source_event_id=%s LIMIT 1",
        (source_generation, f"snapshot:{source_generation}"),
    )
    return source_generation if await retained.fetchone() is not None else None


def _rebase_recovery_metadata(
    metadata: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    rebased = dict(metadata)
    expected_base = metadata.get("state_base_generation")
    actual_base = manifest.get("generation")
    if actual_base == expected_base:
        return rebased
    if not isinstance(actual_base, str) or not actual_base.strip():
        raise ValueError("pending inventory ontology base generation changed")
    rebased["state_base_generation"] = actual_base
    return rebased


_SELECT_OBSERVATIONS = (
    "SELECT observation_id, content_digest, idempotency_key, subject_kind, "
    "observation_kind, mutation_kind, subject_ref, subject_type, properties, "
    "property_mask, properties_complete, links_complete, tombstone_confirmed, "
    "provider_ref, scope_ref, operation, operation_status, source_identity, source_event_id, "
    "source_revision, effective_at, observed_at, evidence_cutoff, recorded_at, ingested_at, "
    "provider_event_at, "
    "from_id, from_type, link_type, to_id, to_type FROM inventory_observation_journal"
)


__all__ = [
    "INVENTORY_OBSERVATION_WATERMARK_KEY",
    "InventoryObservationAppendResult",
    "InventoryProjectionReplayInput",
    "InventorySnapshotObservationAppendResult",
    "PostgresInventoryObservationJournal",
]
