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
    configuration_delivery_pending,
)
from fdai.delivery.inventory_semantic_digest import (
    inventory_semantic_digest,
    inventory_subject_semantic_digest,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.persistence.postgres_inventory_observation_records import (
    confirmed_relationship_tombstone as _confirmed_relationship_tombstone,
)
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
    covered_ontology_projection_watermark as _covered_ontology_projection_watermark,
)
from fdai.delivery.persistence.postgres_inventory_projection_checkpoints import (
    global_projection_watermark as _global_projection_watermark,
)
from fdai.delivery.persistence.postgres_inventory_projection_replay import (
    MAX_ACTIVE_PROJECTION_OBSERVATIONS,
    InventoryProjectionReplayInput,
    build_projection_replay_observation,
    projection_freshness_ceiling,
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
from fdai.delivery.persistence.postgres_inventory_snapshot_membership import (
    load_previous_snapshot_members as _load_previous_snapshot_members,
)
from fdai.delivery.persistence.postgres_inventory_snapshot_membership import (
    load_snapshot_generation_records as _load_snapshot_generation_records,
)
from fdai.delivery.persistence.postgres_inventory_snapshot_membership import (
    load_snapshot_history_records as _load_snapshot_history_records,
)
from fdai.delivery.persistence.postgres_inventory_snapshot_membership import (
    store_snapshot_membership as _store_snapshot_membership,
)
from fdai.delivery.persistence.postgres_inventory_snapshot_recovery import (
    rebase_recovery_metadata as _rebase_recovery_metadata,
)
from fdai.delivery.persistence.postgres_inventory_snapshot_recovery import (
    reusable_journal_generation as _reusable_journal_generation,
)
from fdai.delivery.persistence.postgres_inventory_snapshot_recovery import (
    snapshot_recovery_observation as _snapshot_recovery_observation,
)
from fdai.delivery.persistence.postgres_observation_lifecycle import (
    bind_observation_lifecycle,
    close_observation_corrections,
)
from fdai.shared.providers.inventory_observation import (
    InventoryObservationKind,
    InventoryObservationSubjectKind,
    NormalizedInventoryObservation,
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
        """Advance the overlay fence and any ontology fence the active generation covers."""

        await _update_watermark_state(connection, overlay_watermark=watermark)
        covered = await _covered_ontology_projection_watermark(connection)
        if covered is not None:
            generation, projection_watermark = covered
            await advance_ontology_projection(
                connection,
                generation=generation,
                watermark=projection_watermark,
            )

    async def load_object_observations(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        resource_id: str,
        after: datetime,
    ) -> tuple[NormalizedInventoryObservation, ...]:
        cursor = await connection.execute(
            _SELECT_OBJECT_HISTORY_OBSERVATIONS,
            (resource_id, after, _MAX_REPLAY_OBSERVATIONS + 1),
        )
        rows = await cursor.fetchall()
        if len(rows) > _MAX_REPLAY_OBSERVATIONS:
            raise ValueError("inventory observation replay exceeds its per-resource bound")
        observations = [_observation(row) for row in rows]
        observations.extend(
            await _load_snapshot_history_records(
                connection,
                resource_id=resource_id,
                after=after,
                limit=_MAX_REPLAY_OBSERVATIONS,
            )
        )
        if len(observations) > _MAX_REPLAY_OBSERVATIONS:
            raise ValueError("inventory observation replay exceeds its per-resource bound")
        observations.sort(
            key=lambda item: (
                item.effective_at,
                item.observation_kind is InventoryObservationKind.TOMBSTONE,
                item.source_event_id,
                item.content_digest,
            )
        )
        return tuple(observations)

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
                membership_records: tuple[NormalizedInventoryObservation, ...] | None = None
                rows: Sequence[Mapping[str, Any]] = ()
                if metadata.get("journal_replay_schema_version") == 2:
                    membership_records = await _load_snapshot_generation_records(
                        connection,
                        generation_id=generation,
                        limit=MAX_ACTIVE_PROJECTION_OBSERVATIONS,
                    )
                    if membership_records is None:
                        raise ValueError("active inventory snapshot membership is unavailable")
                    rows = ()
                else:
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
        records = (
            membership_records
            if membership_records is not None
            else tuple(_observation(row) for row in rows)
        )
        if not records:
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
            records=records,
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
                scope_refs = tuple(str(value) for value in snapshot["scopes"])
                snapshot_records = _snapshot_records(observation, scope_refs=scope_refs)
                links_complete = observation.complete and not observation.relationship_drops
                history_visible = reused_journal_generation is None
                coverage_scope = metadata.get("coverage_scope")
                if coverage_scope is not None and not isinstance(coverage_scope, str):
                    raise ValueError("inventory snapshot coverage scope is malformed")
                metadata["semantic_content_digest"] = semantic_digest
                metadata["journal_source_generation"] = journal_source_generation
                metadata["journal_replay_schema_version"] = 2
                await connection.execute(
                    "UPDATE inventory_snapshot SET metadata=%s::jsonb WHERE id=%s",
                    (json.dumps(metadata, sort_keys=True), observation.generation),
                )
                records: tuple[NormalizedInventoryObservation, ...]
                if reused_journal_generation is not None:
                    records = ()
                else:
                    previous = await _load_previous_snapshot_members(
                        connection,
                        source=str(snapshot["source"]),
                        observation_kind=str(snapshot["observation_kind"]),
                        scopes=scope_refs,
                        resource_types=tuple(str(value) for value in snapshot["resource_types"]),
                        coverage_scope=metadata.get("coverage_scope"),
                    )
                    previous_members, previous_links_complete = (
                        previous if previous is not None else ({}, False)
                    )
                    current_by_key = {
                        (item.subject_kind.value, item.subject_ref): item
                        for item in snapshot_records
                    }
                    changed_records = tuple(
                        item
                        for item in snapshot_records
                        if (
                            (
                                prior := previous_members.get(
                                    (item.subject_kind.value, item.subject_ref)
                                )
                            )
                            is None
                            or str(prior["semantic_digest"])
                            != inventory_subject_semantic_digest(item)
                        )
                    )
                    relation_tombstones: tuple[NormalizedInventoryObservation, ...] = ()
                    if coverage_scope not in (None, "full_provider_scope"):
                        raise ValueError("inventory snapshot coverage scope is malformed")
                    if (
                        coverage_scope == "full_provider_scope"
                        and links_complete
                        and previous_links_complete
                        and previous is not None
                    ):
                        relation_tombstones = tuple(
                            _confirmed_relationship_tombstone(
                                prior,
                                generation=observation.generation,
                                confirmed_at=snapshot["started_at"],
                                recorded_at=observation.recorded_at,
                            )
                            for (subject_kind, subject_ref), prior in previous_members.items()
                            if subject_kind == InventoryObservationSubjectKind.RELATIONSHIP.value
                            and (subject_kind, subject_ref) not in current_by_key
                        )
                    records = (*changed_records, *relation_tombstones)
                result = await _append_records(connection, records)
                if records:
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
                await _store_snapshot_membership(
                    connection,
                    generation_id=observation.generation,
                    source=str(snapshot["source"]),
                    observation_kind=str(snapshot["observation_kind"]),
                    scopes=scope_refs,
                    resource_types=covered_types,
                    coverage_scope=metadata.get("coverage_scope"),
                    semantic_content_digest=semantic_digest,
                    journal_high_watermark=high_watermark,
                    recorded_at=observation.recorded_at,
                    history_visible=history_visible,
                    links_complete=links_complete,
                    records=snapshot_records,
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


_SELECT_OBSERVATIONS = (
    "SELECT observation_id, content_digest, idempotency_key, subject_kind, "
    "observation_kind, mutation_kind, subject_ref, subject_type, properties, "
    "property_mask, properties_complete, links_complete, tombstone_confirmed, "
    "provider_ref, scope_ref, operation, operation_status, source_identity, source_event_id, "
    "source_revision, effective_at, observed_at, evidence_cutoff, recorded_at, ingested_at, "
    "provider_event_at, "
    "from_id, from_type, link_type, to_id, to_type FROM inventory_observation_journal"
)
_SELECT_OBJECT_HISTORY_OBSERVATIONS = (
    "SELECT observation_id, content_digest, idempotency_key, subject_kind, "
    "observation_kind, mutation_kind, subject_ref, subject_type, properties, "
    "property_mask, properties_complete, links_complete, tombstone_confirmed, "
    "provider_ref, scope_ref, operation, operation_status, source_identity, source_event_id, "
    "source_revision, effective_at, observed_at, evidence_cutoff, recorded_at, ingested_at, "
    "provider_event_at, from_id, from_type, link_type, to_id, to_type "
    "FROM inventory_observation_journal "
    "WHERE subject_kind='object' AND subject_ref=%s AND effective_at>%s "
    "AND NOT (source_identity='inventory.reconciliation' "
    "AND source_event_id LIKE 'snapshot:%%' AND EXISTS ("
    "SELECT 1 FROM inventory_observation_snapshot_generation AS generation "
    "WHERE generation.generation_id=source_revision)) "
    "ORDER BY effective_at, "
    "(observation_kind='tombstone')::int, source_event_id, content_digest "
    "LIMIT %s"
)


__all__ = [
    "INVENTORY_OBSERVATION_WATERMARK_KEY",
    "InventoryObservationAppendResult",
    "InventoryProjectionReplayInput",
    "InventorySnapshotObservationAppendResult",
    "PostgresInventoryObservationJournal",
]
