"""PostgreSQL adapter for append-only operational state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.ontology_platform.state_transitions import (
    OperationalStateTransition,
    StateTransitionAuthority,
    StateTransitionBatch,
    StateTransitionCoverage,
    StateTransitionLane,
    StateTransitionRead,
)

_MAX_TRANSITIONS: Final[int] = 512


@dataclass(frozen=True, slots=True)
class PostgresStateTransitionStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresStateTransitionStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("state transition PostgreSQL timeouts MUST be positive")


class PostgresStateTransitionStore:
    """Atomically append facts and coverage, then read at bitemporal cutoffs."""

    def __init__(self, *, config: PostgresStateTransitionStoreConfig) -> None:
        self._config = config

    async def append(self, batch: StateTransitionBatch) -> bool:
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                inserted = await connection.execute(
                    "INSERT INTO operational_state_transition_batch "
                    "(batch_id, recorded_at) VALUES (%s, %s) "
                    "ON CONFLICT (batch_id) DO NOTHING",
                    (batch.batch_id, batch.recorded_at),
                )
                if getattr(inserted, "rowcount", 1) == 0:
                    try:
                        existing = await _read_existing_batch(
                            connection,
                            batch_id=batch.batch_id,
                        )
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            "state transition batch replay does not match retained content"
                        ) from exc
                    if existing != batch:
                        raise ValueError(
                            "state transition batch replay does not match retained content"
                        )
                    return False
                if batch.transitions:
                    async with connection.cursor() as cursor:
                        try:
                            await cursor.executemany(
                                "INSERT INTO operational_state_transition "
                                "(transition_id, batch_id, idempotency_key, subject_ref, "
                                "subject_type, state_type, from_state, to_state, lane, authority, "
                                "effective_at, evidence_cutoff, recorded_at, source_identity, "
                                "source_revision, producer_id, producer_version, "
                                "freshness_ceiling_seconds, completeness_basis_points, "
                                "evidence_refs, conflicts, correlation_refs, synthetic, "
                                "execution_authority) "
                                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                                "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)",
                                [
                                    (
                                        item.transition_id,
                                        batch.batch_id,
                                        item.idempotency_key,
                                        item.subject_ref,
                                        item.subject_type,
                                        item.state_type,
                                        item.from_state,
                                        item.to_state,
                                        item.lane.value,
                                        item.authority.value,
                                        item.effective_at,
                                        item.evidence_cutoff,
                                        item.recorded_at,
                                        item.source_identity,
                                        item.source_revision,
                                        item.producer_id,
                                        item.producer_version,
                                        item.freshness_ceiling_seconds,
                                        item.completeness_basis_points,
                                        list(item.evidence_refs),
                                        list(item.conflicts),
                                        list(item.correlation_refs),
                                        item.synthetic,
                                    )
                                    for item in batch.transitions
                                ],
                            )
                        except psycopg.errors.UniqueViolation as exc:
                            raise ValueError(
                                "state transition idempotency key changed content"
                            ) from exc
                async with connection.cursor() as cursor:
                    await cursor.executemany(
                        "INSERT INTO operational_state_transition_coverage "
                        "(coverage_id, batch_id, subject_ref, state_type, coverage_start_at, "
                        "coverage_end_at, recorded_at, source_identity, source_revision, "
                        "watermark, evidence_ref, complete, limitation, synthetic) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        [
                            (
                                item.coverage_id,
                                batch.batch_id,
                                item.subject_ref,
                                item.state_type,
                                item.coverage_start_at,
                                item.coverage_end_at,
                                item.recorded_at,
                                item.source_identity,
                                item.source_revision,
                                item.watermark,
                                item.evidence_ref,
                                item.complete,
                                item.limitation,
                                item.synthetic,
                            )
                            for item in batch.coverage
                        ],
                    )
        return True

    async def read(
        self,
        *,
        subject_refs: tuple[str, ...],
        state_types: tuple[str, ...],
        to_states: tuple[str, ...],
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
        limit: int,
    ) -> StateTransitionRead:
        _validate_read(
            subject_refs,
            state_types,
            to_states,
            start_at,
            end_at,
            known_at,
            limit,
        )
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                cursor = await connection.execute(
                    "SELECT transition_id, idempotency_key, subject_ref, subject_type, "
                    "state_type, from_state, to_state, lane, authority, effective_at, "
                    "evidence_cutoff, recorded_at, source_identity, source_revision, "
                    "producer_id, producer_version, freshness_ceiling_seconds, "
                    "completeness_basis_points, evidence_refs, conflicts, correlation_refs, "
                    "synthetic, execution_authority "
                    "FROM operational_state_transition "
                    "WHERE subject_ref = ANY(%s) AND state_type = ANY(%s) "
                    "AND to_state = ANY(%s) "
                    "AND effective_at >= %s AND effective_at <= %s AND recorded_at <= %s "
                    "ORDER BY effective_at, recorded_at, transition_id LIMIT %s",
                    (
                        list(subject_refs),
                        list(state_types),
                        list(to_states),
                        start_at,
                        end_at,
                        known_at,
                        limit + 1,
                    ),
                )
                transition_rows = await cursor.fetchall()
                coverage_cursor = await connection.execute(
                    "SELECT DISTINCT ON (subject_ref, state_type) coverage_id, subject_ref, "
                    "state_type, coverage_start_at, coverage_end_at, recorded_at, "
                    "source_identity, source_revision, watermark, evidence_ref, complete, "
                    "limitation, synthetic "
                    "FROM operational_state_transition_coverage "
                    "WHERE subject_ref = ANY(%s) AND state_type = ANY(%s) "
                    "AND coverage_start_at <= %s AND coverage_end_at >= %s "
                    "AND recorded_at <= %s "
                    "ORDER BY subject_ref, state_type, recorded_at DESC, coverage_id DESC",
                    (list(subject_refs), list(state_types), start_at, end_at, known_at),
                )
                coverage_rows = await coverage_cursor.fetchall()
        truncated = len(transition_rows) > limit
        transitions = tuple(_transition(row) for row in transition_rows[:limit])
        coverage = tuple(_coverage(row) for row in coverage_rows)
        expected = {(subject, state_type) for subject in subject_refs for state_type in state_types}
        covered = {(item.subject_ref, item.state_type) for item in coverage}
        reasons = {
            item.limitation or "coverage_incomplete"
            for item in coverage
            if not item.complete or item.synthetic
        }
        if covered != expected:
            reasons.add("coverage_missing")
        if truncated:
            reasons.add("result_limit")
        limitation = "+".join(sorted(reasons)) if reasons else None
        return StateTransitionRead(
            transitions=transitions,
            coverage=coverage,
            complete=limitation is None,
            limitation=limitation,
        )

    async def _connect(self) -> Any:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=False,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: Any) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _transition(row: dict[str, Any]) -> OperationalStateTransition:
    if row["execution_authority"] is not False:
        raise ValueError("stored state transition grants execution authority")
    return OperationalStateTransition(
        transition_id=str(row["transition_id"]),
        idempotency_key=str(row["idempotency_key"]),
        subject_ref=str(row["subject_ref"]),
        subject_type=str(row["subject_type"]),
        state_type=str(row["state_type"]),
        from_state=str(row["from_state"]),
        to_state=str(row["to_state"]),
        lane=StateTransitionLane(str(row["lane"])),
        authority=StateTransitionAuthority(str(row["authority"])),
        effective_at=row["effective_at"],
        evidence_cutoff=row["evidence_cutoff"],
        recorded_at=row["recorded_at"],
        source_identity=str(row["source_identity"]),
        source_revision=str(row["source_revision"]),
        producer_id=str(row["producer_id"]),
        producer_version=str(row["producer_version"]),
        freshness_ceiling_seconds=int(row["freshness_ceiling_seconds"]),
        completeness_basis_points=int(row["completeness_basis_points"]),
        evidence_refs=tuple(row["evidence_refs"]),
        conflicts=tuple(row["conflicts"]),
        correlation_refs=tuple(row["correlation_refs"]),
        synthetic=bool(row["synthetic"]),
        execution_authority=False,
    )


async def _read_existing_batch(connection: Any, *, batch_id: str) -> StateTransitionBatch:
    batch_cursor = await connection.execute(
        "SELECT batch_id, recorded_at FROM operational_state_transition_batch WHERE batch_id = %s",
        (batch_id,),
    )
    batch_rows = await batch_cursor.fetchall()
    transition_cursor = await connection.execute(
        "SELECT transition_id, idempotency_key, subject_ref, subject_type, "
        "state_type, from_state, to_state, lane, authority, effective_at, "
        "evidence_cutoff, recorded_at, source_identity, source_revision, "
        "producer_id, producer_version, freshness_ceiling_seconds, "
        "completeness_basis_points, evidence_refs, conflicts, correlation_refs, "
        "synthetic, execution_authority FROM operational_state_transition "
        "WHERE batch_id = %s ORDER BY transition_id",
        (batch_id,),
    )
    transition_rows = await transition_cursor.fetchall()
    coverage_cursor = await connection.execute(
        "SELECT coverage_id, subject_ref, state_type, coverage_start_at, "
        "coverage_end_at, recorded_at, source_identity, source_revision, "
        "watermark, evidence_ref, complete, limitation, synthetic "
        "FROM operational_state_transition_coverage "
        "WHERE batch_id = %s ORDER BY coverage_id",
        (batch_id,),
    )
    coverage_rows = await coverage_cursor.fetchall()
    if len(batch_rows) != 1:
        raise ValueError("retained state transition batch identity is invalid")
    return StateTransitionBatch(
        batch_id=str(batch_rows[0]["batch_id"]),
        transitions=tuple(_transition(row) for row in transition_rows),
        coverage=tuple(_coverage(row) for row in coverage_rows),
        recorded_at=batch_rows[0]["recorded_at"],
    )


def _coverage(row: dict[str, Any]) -> StateTransitionCoverage:
    return StateTransitionCoverage(
        coverage_id=str(row["coverage_id"]),
        subject_ref=str(row["subject_ref"]),
        state_type=str(row["state_type"]),
        coverage_start_at=row["coverage_start_at"],
        coverage_end_at=row["coverage_end_at"],
        recorded_at=row["recorded_at"],
        source_identity=str(row["source_identity"]),
        source_revision=str(row["source_revision"]),
        watermark=str(row["watermark"]),
        evidence_ref=str(row["evidence_ref"]),
        complete=bool(row["complete"]),
        limitation=str(row["limitation"]) if row["limitation"] is not None else None,
        synthetic=bool(row["synthetic"]),
    )


def _validate_read(
    subject_refs: tuple[str, ...],
    state_types: tuple[str, ...],
    to_states: tuple[str, ...],
    start_at: datetime,
    end_at: datetime,
    known_at: datetime,
    limit: int,
) -> None:
    if (
        not subject_refs
        or not state_types
        or not to_states
        or subject_refs != tuple(sorted(set(subject_refs)))
        or state_types != tuple(sorted(set(state_types)))
        or to_states != tuple(sorted(set(to_states)))
    ):
        raise ValueError("state transition read scope MUST be non-empty, unique, and ordered")
    timestamps = (start_at, end_at, known_at)
    if any(item.tzinfo is None or item.utcoffset() is None for item in timestamps):
        raise ValueError("state transition read times MUST include a timezone")
    if not start_at <= end_at <= known_at:
        raise ValueError("state transition read times are not causally ordered")
    if not 1 <= limit <= _MAX_TRANSITIONS:
        raise ValueError("state transition read limit is out of bounds")


__all__ = ["PostgresStateTransitionStore", "PostgresStateTransitionStoreConfig"]
