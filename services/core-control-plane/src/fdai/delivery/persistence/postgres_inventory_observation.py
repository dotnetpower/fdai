"""PostgreSQL dual-write adapter for normalized inventory observations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.persistence.postgres_inventory_projection_replay import (
    MAX_ACTIVE_PROJECTION_OBSERVATIONS,
    InventoryProjectionReplayInput,
    build_projection_replay_observation,
    projection_freshness_ceiling,
    projection_replay_drops,
    required_replay_watermark,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    _PROMOTION_LOCK,
    PostgresInventorySnapshotStoreConfig,
    _snapshot_relationship_props,
)
from fdai.delivery.persistence.postgres_observation_lifecycle import (
    bind_observation_lifecycle,
    close_observation_corrections,
)
from fdai.shared.providers.inventory import LinkRecord, ResourceRecord
from fdai.shared.providers.inventory_observation import (
    INVENTORY_OBSERVATION_SCHEMA_VERSION,
    InventoryMutationKind,
    InventoryObservationKind,
    InventoryObservationSubjectKind,
    NormalizedInventoryObservation,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
)

INVENTORY_OBSERVATION_WATERMARK_KEY: Final[str] = "inventory-observation:watermarks"
_MAX_REPLAY_OBSERVATIONS = 4096
_MAX_CHANGE_BATCH = 1024
_WRITE_BATCH_SIZE = 1000


@dataclass(frozen=True, slots=True)
class InventoryObservationAppendResult:
    """Result of one atomic journal append."""

    high_watermark: int
    inserted: int


@dataclass(frozen=True, slots=True)
class InventorySnapshotObservationAppendResult:
    """Journal and contiguous projection watermarks for one promoted snapshot."""

    journal_high_watermark: int
    projection_high_watermark: int


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
                cursor = await connection.execute(
                    _SELECT_OBSERVATIONS + " WHERE source_identity='inventory.reconciliation' "
                    "AND source_revision=%s AND source_event_id=%s "
                    "AND observation_kind='full' AND mutation_kind='upsert' "
                    "ORDER BY subject_kind, subject_ref "
                    "LIMIT %s",
                    (
                        generation,
                        f"snapshot:{generation}",
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
        metadata = _mapping(snapshot["metadata"])
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
                if "state_base_generation" not in metadata:
                    return None
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
                if state.get("ontology_generation") == generation:
                    if manifest.get("generation") != generation:
                        raise ValueError("inventory ontology completion fence is inconsistent")
                    return None
                if manifest.get("generation") == generation:
                    raise ValueError(
                        "inventory ontology manifest advanced without its atomic watermark"
                    )
                expected_base = metadata.get("state_base_generation")
                if manifest.get("generation") != expected_base:
                    raise ValueError("pending inventory ontology base generation changed")
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

        if observation.recorded_at is None:
            raise ValueError("promoted inventory observation recorded_at MUST be supplied")
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute("SELECT pg_advisory_xact_lock(%s)", (_PROMOTION_LOCK,))
                snapshot_cursor = await connection.execute(
                    "SELECT s.started_at, s.scopes, s.resource_types, s.metadata "
                    "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                    "WHERE a.singleton=TRUE AND s.status='active' AND s.id=%s",
                    (observation.generation,),
                )
                snapshot = await snapshot_cursor.fetchone()
                if snapshot is None:
                    raise ValueError("promoted inventory observation is not the active snapshot")
                records = _snapshot_records(
                    observation,
                    scope_refs=tuple(str(value) for value in snapshot["scopes"]),
                )
                result = await _append_records(connection, records)
                await bind_observation_lifecycle(
                    connection,
                    records,
                    allow_oi16_synthetic=self._allow_oi16_synthetic,
                )
                high_watermark = result.high_watermark
                metadata = _mapping(snapshot["metadata"])
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
                gap_cursor = await connection.execute(
                    "SELECT COALESCE(MIN(watermark) - 1, %s) AS projection_watermark "
                    "FROM inventory_observation_journal "
                    "WHERE watermark>%s AND NOT (source_revision=%s OR ("
                    "effective_at<=%s AND scope_ref=ANY(%s::text[])))",
                    (
                        high_watermark,
                        current_projection,
                        observation.generation,
                        snapshot["started_at"],
                        list(snapshot["scopes"]),
                    ),
                )
                gap = await gap_cursor.fetchone()
                if gap is None:
                    raise RuntimeError("inventory observation projection watermark is unavailable")
                projection_watermark = max(
                    current_projection,
                    int(gap["projection_watermark"]),
                )
        return InventorySnapshotObservationAppendResult(
            journal_high_watermark=high_watermark,
            projection_high_watermark=projection_watermark,
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
    for row in link_rows:
        properties = dict(_mapping(row["props"]))
        raw_observation = properties.pop(LINK_OBSERVATION_METADATA_PROPERTY, None)
        if not isinstance(raw_observation, Mapping):
            raise ValueError("pending inventory relationship has no observation metadata")
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
        relationship_drops=projection_replay_drops(metadata, prior_manifest),
        recorded_at=recorded_at,
        state_base_generation=(
            str(metadata["state_base_generation"])
            if metadata.get("state_base_generation") is not None
            else None
        ),
        state_base_generation_checked="state_base_generation" in metadata,
    )


_SELECT_OBSERVATIONS = (
    "SELECT observation_id, content_digest, idempotency_key, subject_kind, "
    "observation_kind, mutation_kind, subject_ref, subject_type, properties, "
    "property_mask, properties_complete, links_complete, tombstone_confirmed, "
    "provider_ref, scope_ref, operation, operation_status, source_identity, source_event_id, "
    "source_revision, effective_at, observed_at, evidence_cutoff, recorded_at, "
    "from_id, from_type, link_type, to_id, to_type FROM inventory_observation_journal"
)


async def _append_records(
    connection: psycopg.AsyncConnection[Any],
    observations: Sequence[NormalizedInventoryObservation],
) -> InventoryObservationAppendResult:
    if not observations:
        cursor = await connection.execute(
            "SELECT COALESCE(MAX(watermark), 0) AS high_watermark "
            "FROM inventory_observation_journal"
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("inventory observation journal high watermark is unavailable")
        return InventoryObservationAppendResult(int(row["high_watermark"]), 0)
    inserted = 0
    retained_watermarks: list[int] = []
    for offset in range(0, len(observations), _WRITE_BATCH_SIZE):
        chunk = observations[offset : offset + _WRITE_BATCH_SIZE]
        cursor = connection.cursor()
        await cursor.executemany(
            "INSERT INTO inventory_observation_journal "
            "(observation_id, content_digest, schema_version, idempotency_key, "
            "subject_kind, observation_kind, mutation_kind, subject_ref, subject_type, "
            "properties, property_mask, properties_complete, links_complete, "
            "tombstone_confirmed, provider_ref, scope_ref, operation, operation_status, "
            "source_identity, source_event_id, source_revision, effective_at, observed_at, "
            "evidence_cutoff, recorded_at, from_id, from_type, link_type, to_id, to_type) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (idempotency_key, subject_kind, subject_ref) DO NOTHING",
            [_observation_params(item) for item in chunk],
        )
        inserted += max(0, cursor.rowcount)
        keys = sorted({item.idempotency_key for item in chunk})
        retained_cursor = await connection.execute(
            "SELECT watermark, idempotency_key, subject_kind, subject_ref, content_digest "
            "FROM inventory_observation_journal WHERE idempotency_key=ANY(%s::text[])",
            (keys,),
        )
        retained = await retained_cursor.fetchall()
        retained_by_key = {
            (
                str(row["idempotency_key"]),
                str(row["subject_kind"]),
                str(row["subject_ref"]),
            ): row
            for row in retained
        }
        for item in chunk:
            key = (item.idempotency_key, item.subject_kind.value, item.subject_ref)
            row = retained_by_key.get(key)
            if row is None or str(row["content_digest"]) != item.content_digest:
                raise ValueError("inventory observation idempotency key changed content")
            retained_watermarks.append(int(row["watermark"]))
    high_watermark = max(retained_watermarks)
    await _update_watermark_state(connection, journal_watermark=high_watermark)
    return InventoryObservationAppendResult(high_watermark, inserted)


def _observation_params(item: NormalizedInventoryObservation) -> tuple[object, ...]:
    return (
        item.observation_id,
        item.content_digest,
        INVENTORY_OBSERVATION_SCHEMA_VERSION,
        item.idempotency_key,
        item.subject_kind.value,
        item.observation_kind.value,
        item.mutation_kind.value,
        item.subject_ref,
        item.subject_type,
        item.properties_json,
        list(item.property_mask),
        item.properties_complete,
        item.links_complete,
        item.tombstone_confirmed,
        item.provider_ref,
        item.scope_ref,
        item.operation,
        item.operation_status,
        item.source_identity,
        item.source_event_id,
        item.source_revision,
        item.effective_at,
        item.observed_at,
        item.evidence_cutoff,
        item.recorded_at,
        item.from_id,
        item.from_type,
        item.link_type,
        item.to_id,
        item.to_type,
    )


def _observation(row: Mapping[str, Any]) -> NormalizedInventoryObservation:
    properties = _mapping(row["properties"])
    return NormalizedInventoryObservation(
        observation_id=str(row["observation_id"]),
        content_digest=str(row["content_digest"]),
        idempotency_key=str(row["idempotency_key"]),
        subject_kind=InventoryObservationSubjectKind(str(row["subject_kind"])),
        observation_kind=InventoryObservationKind(str(row["observation_kind"])),
        mutation_kind=InventoryMutationKind(str(row["mutation_kind"])),
        subject_ref=str(row["subject_ref"]),
        subject_type=str(row["subject_type"]),
        properties_json=json.dumps(
            properties,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        property_mask=tuple(row["property_mask"]),
        properties_complete=bool(row["properties_complete"]),
        links_complete=bool(row["links_complete"]),
        tombstone_confirmed=bool(row["tombstone_confirmed"]),
        provider_ref=str(row["provider_ref"]) if row["provider_ref"] is not None else None,
        scope_ref=str(row["scope_ref"]) if row["scope_ref"] is not None else None,
        operation=str(row["operation"]) if row["operation"] is not None else None,
        operation_status=(
            str(row["operation_status"]) if row["operation_status"] is not None else None
        ),
        source_identity=str(row["source_identity"]),
        source_event_id=str(row["source_event_id"]),
        source_revision=str(row["source_revision"]),
        effective_at=row["effective_at"],
        observed_at=row["observed_at"],
        evidence_cutoff=row["evidence_cutoff"],
        recorded_at=row["recorded_at"],
        from_id=str(row["from_id"]) if row["from_id"] is not None else None,
        from_type=str(row["from_type"]) if row["from_type"] is not None else None,
        link_type=str(row["link_type"]) if row["link_type"] is not None else None,
        to_id=str(row["to_id"]) if row["to_id"] is not None else None,
        to_type=str(row["to_type"]) if row["to_type"] is not None else None,
    )


def _snapshot_records(
    observation: PromotedInventoryObservation,
    *,
    scope_refs: tuple[str, ...],
) -> tuple[NormalizedInventoryObservation, ...]:
    if observation.recorded_at is None:
        raise ValueError("promoted inventory observation recorded_at MUST be supplied")
    records: list[NormalizedInventoryObservation] = []
    scope_ref = _scope_set_ref(scope_refs)
    for resource in observation.resources:
        observed_at = _timestamp(resource.last_seen) or observation.recorded_at
        records.append(
            NormalizedInventoryObservation.create(
                idempotency_key=_snapshot_key(
                    observation.generation, "object", resource.resource_id
                ),
                subject_kind=InventoryObservationSubjectKind.OBJECT,
                observation_kind=InventoryObservationKind.FULL,
                mutation_kind=InventoryMutationKind.UPSERT,
                subject_ref=resource.resource_id,
                subject_type=resource.type,
                properties=resource.props,
                property_mask=tuple(resource.props),
                properties_complete=True,
                links_complete=observation.complete,
                tombstone_confirmed=False,
                provider_ref=resource.provider_ref,
                scope_ref=_provider_scope(resource.provider_ref) or scope_ref,
                source_identity="inventory.reconciliation",
                source_event_id=f"snapshot:{observation.generation}",
                source_revision=observation.generation,
                effective_at=observed_at,
                observed_at=observed_at,
                evidence_cutoff=observed_at,
                recorded_at=observation.recorded_at,
            )
        )
    for link in observation.links:
        subject_ref = _relationship_ref(link.from_id, link.link_type, link.to_id)
        relationship_properties = _snapshot_relationship_props(link)
        records.append(
            NormalizedInventoryObservation.create(
                idempotency_key=_snapshot_key(observation.generation, "relationship", subject_ref),
                subject_kind=InventoryObservationSubjectKind.RELATIONSHIP,
                observation_kind=InventoryObservationKind.FULL,
                mutation_kind=InventoryMutationKind.UPSERT,
                subject_ref=subject_ref,
                subject_type=link.link_type,
                properties=relationship_properties,
                property_mask=tuple(relationship_properties),
                properties_complete=True,
                links_complete=observation.complete,
                tombstone_confirmed=False,
                scope_ref=scope_ref,
                source_identity="inventory.reconciliation",
                source_event_id=f"snapshot:{observation.generation}",
                source_revision=observation.generation,
                effective_at=observation.recorded_at,
                observed_at=observation.recorded_at,
                evidence_cutoff=observation.recorded_at,
                recorded_at=observation.recorded_at,
                from_id=link.from_id,
                from_type=link.from_type,
                link_type=link.link_type,
                to_id=link.to_id,
                to_type=link.to_type,
            )
        )
    return tuple(records)


def _confirmed_tombstone(
    row: Mapping[str, Any],
    *,
    generation: str,
    confirmed_at: datetime,
    recorded_at: datetime,
) -> NormalizedInventoryObservation:
    resource_id = str(row["resource_id"])
    candidate_id = str(row["observation_id"])
    return NormalizedInventoryObservation.create(
        idempotency_key=f"inventory-tombstone-confirmation:{candidate_id}:{generation}",
        subject_kind=InventoryObservationSubjectKind.OBJECT,
        observation_kind=InventoryObservationKind.TOMBSTONE,
        mutation_kind=InventoryMutationKind.DELETE,
        subject_ref=resource_id,
        subject_type=str(row["resource_type"]),
        properties={},
        property_mask=(),
        properties_complete=False,
        links_complete=True,
        tombstone_confirmed=True,
        scope_ref=str(row["scope_ref"]) if row["scope_ref"] is not None else None,
        source_identity="inventory.reconciliation",
        source_event_id=f"snapshot:{generation}",
        source_revision=generation,
        effective_at=confirmed_at,
        observed_at=confirmed_at,
        evidence_cutoff=confirmed_at,
        recorded_at=recorded_at,
    )


async def _update_watermark_state(
    connection: psycopg.AsyncConnection[Any],
    *,
    journal_watermark: int | None = None,
    overlay_watermark: int | None = None,
    ontology_watermark: int | None = None,
    ontology_generation: str | None = None,
) -> None:
    cursor = await connection.execute(
        "SELECT value FROM state_kv WHERE key=%s FOR UPDATE",
        (INVENTORY_OBSERVATION_WATERMARK_KEY,),
    )
    row = await cursor.fetchone()
    state = _mapping(row["value"]) if row is not None else {}
    current_journal = _nonnegative_int(state.get("journal_high_watermark"))
    current_overlay = _nonnegative_int(state.get("overlay_projection_watermark"))
    current_ontology = _nonnegative_int(state.get("ontology_projection_watermark"))
    next_journal = max(current_journal, journal_watermark or 0)
    next_overlay = max(current_overlay, overlay_watermark or 0)
    next_ontology = max(current_ontology, ontology_watermark or 0)
    if next_overlay > next_journal or next_ontology > next_journal:
        raise ValueError("inventory observation projection watermark exceeds journal")
    pending_cursor = await connection.execute(
        "SELECT COUNT(*) AS pending FROM inventory_observation_pending_tombstone"
    )
    pending_row = await pending_cursor.fetchone()
    pending = int(pending_row["pending"]) if pending_row is not None else 0
    value = {
        "schema_version": "1.0.0",
        "journal_high_watermark": next_journal,
        "overlay_projection_watermark": next_overlay,
        "ontology_projection_watermark": next_ontology,
        "ontology_generation": ontology_generation or state.get("ontology_generation"),
        "pending_tombstones": pending,
        "mode": "shadow",
    }
    await connection.execute(
        "INSERT INTO state_kv (key, value, updated_at) VALUES (%s, %s::jsonb, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
        (
            INVENTORY_OBSERVATION_WATERMARK_KEY,
            json.dumps(value, sort_keys=True, separators=(",", ":")),
        ),
    )


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("inventory observation JSON value MUST be an object")
    return value


def _nonnegative_int(value: object) -> int:
    if value is None:
        return 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("inventory observation watermark MUST be a non-negative integer")
    return value


def _manifest_watermarks(manifest: Mapping[str, Any]) -> tuple[int, int]:
    journal = manifest.get("journal_high_watermark")
    projection = manifest.get("projection_high_watermark")
    if journal is None and projection is None:
        return 0, 0
    if journal is None or projection is None:
        raise ValueError("inventory projection replay manifest watermarks are incomplete")
    return (
        required_replay_watermark(manifest, "journal_high_watermark"),
        required_replay_watermark(manifest, "projection_high_watermark"),
    )


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("inventory observation timestamp MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _snapshot_key(generation: str, subject_kind: str, subject_ref: str) -> str:
    digest = hashlib.sha256(subject_ref.encode("utf-8")).hexdigest()
    return f"inventory-snapshot:{generation}:{subject_kind}:{digest}"


def _relationship_ref(from_id: str, link_type: str, to_id: str) -> str:
    digest = hashlib.sha256(f"{from_id}\0{link_type}\0{to_id}".encode()).hexdigest()
    return f"relationship:{digest}"


def _provider_scope(provider_ref: str | None) -> str | None:
    if provider_ref is None:
        return None
    parts = provider_ref.strip("/").split("/")
    for index, part in enumerate(parts[:-1]):
        if part.lower() == "subscriptions" and parts[index + 1]:
            return parts[index + 1]
    return None


def _scope_set_ref(scope_refs: tuple[str, ...]) -> str:
    scopes = tuple(sorted(set(scope_refs)))
    if not scopes:
        raise ValueError("promoted inventory observation requires source scopes")
    if len(scopes) == 1:
        return scopes[0]
    digest = hashlib.sha256("\0".join(scopes).encode()).hexdigest()
    return f"scope-set:sha256:{digest}"


__all__ = [
    "INVENTORY_OBSERVATION_WATERMARK_KEY",
    "InventoryObservationAppendResult",
    "InventoryProjectionReplayInput",
    "InventorySnapshotObservationAppendResult",
    "PostgresInventoryObservationJournal",
]
