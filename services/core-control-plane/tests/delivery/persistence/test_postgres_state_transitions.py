"""PostgreSQL operational state-transition adapter tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MethodType
from typing import Any

import pytest
from fdai.core.ontology_platform.state_transitions import (
    OperationalStateTransition,
    StateTransitionAuthority,
    StateTransitionBatch,
    StateTransitionCoverage,
    StateTransitionLane,
)
from fdai.delivery.persistence.postgres_state_transitions import (
    PostgresStateTransitionStore,
    PostgresStateTransitionStoreConfig,
)

NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[5]


class _Cursor:
    def __init__(
        self,
        rows: list[dict[str, Any]],
        many: list[tuple[str, list[tuple[object, ...]]]],
        *,
        rowcount: int = 1,
    ) -> None:
        self.rows = rows
        self.many = many
        self.rowcount = rowcount

    async def __aenter__(self) -> _Cursor:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows

    async def executemany(self, query: str, params: list[tuple[object, ...]]) -> None:
        self.many.append((query, params))


class _Context:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class _Connection:
    def __init__(
        self,
        result_sets: list[list[dict[str, Any]]] | None = None,
        *,
        replay: bool = False,
    ) -> None:
        self.result_sets = list(result_sets or [])
        self.executions: list[tuple[str, object]] = []
        self.many: list[tuple[str, list[tuple[object, ...]]]] = []
        self.replay = replay

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def transaction(self) -> _Context:
        return _Context()

    def cursor(self) -> _Cursor:
        return _Cursor([], self.many)

    async def execute(self, query: str, params: object = None) -> _Cursor:
        self.executions.append((query, params))
        rows = (
            self.result_sets.pop(0)
            if query.startswith("SELECT") and "set_config" not in query
            else []
        )
        rowcount = (
            0
            if self.replay and query.startswith("INSERT INTO operational_state_transition_batch")
            else 1
        )
        return _Cursor(rows, self.many, rowcount=rowcount)


def _transition() -> OperationalStateTransition:
    return OperationalStateTransition.create(
        idempotency_key="resource-a:power:1",
        subject_ref="resource-a",
        subject_type="Resource",
        state_type="resource.power_state",
        from_state="running",
        to_state="deallocated",
        lane=StateTransitionLane.OBSERVED,
        authority=StateTransitionAuthority.PROVIDER,
        effective_at=NOW,
        evidence_cutoff=NOW + timedelta(seconds=1),
        recorded_at=NOW + timedelta(seconds=2),
        source_identity="provider:inventory",
        source_revision="inventory:1",
        producer_id="huginn.resource-state",
        producer_version="1.0.0",
        freshness_ceiling_seconds=600,
        completeness_basis_points=10_000,
        evidence_refs=("evidence:transition",),
    )


def _coverage() -> StateTransitionCoverage:
    return StateTransitionCoverage.create(
        subject_ref="resource-a",
        state_type="resource.power_state",
        coverage_start_at=NOW - timedelta(minutes=5),
        coverage_end_at=NOW + timedelta(seconds=1),
        recorded_at=NOW + timedelta(seconds=2),
        source_identity="provider:inventory",
        source_revision="inventory:1",
        watermark="inventory:watermark:1",
        evidence_ref="evidence:coverage",
        complete=True,
    )


def _store(connection: _Connection) -> PostgresStateTransitionStore:
    store = PostgresStateTransitionStore(
        config=PostgresStateTransitionStoreConfig(dsn="postgresql://example")
    )

    async def connect(_self: object) -> _Connection:
        return connection

    store._connect = MethodType(connect, store)  # type: ignore[method-assign]
    return store


async def test_append_writes_transition_and_coverage_atomically() -> None:
    connection = _Connection()
    batch = StateTransitionBatch.create(
        transitions=(_transition(),),
        coverage=(_coverage(),),
        recorded_at=NOW + timedelta(seconds=2),
    )

    inserted = await _store(connection).append(batch)

    assert inserted is True
    assert "INSERT INTO operational_state_transition_batch" in connection.executions[1][0]
    assert len(connection.many) == 2
    assert "INSERT INTO operational_state_transition " in connection.many[0][0]
    assert "INSERT INTO operational_state_transition_coverage" in connection.many[1][0]


async def test_read_requires_positive_coverage_for_every_requested_pair() -> None:
    connection = _Connection([[], []])

    result = await _store(connection).read(
        subject_refs=("resource-a",),
        state_types=("resource.power_state",),
        to_states=("deallocated",),
        start_at=NOW - timedelta(minutes=5),
        end_at=NOW,
        known_at=NOW + timedelta(minutes=1),
        limit=10,
    )

    assert result.transitions == ()
    assert result.coverage == ()
    assert result.complete is False
    assert result.limitation == "coverage_missing"


async def test_identical_batch_replay_verifies_retained_children() -> None:
    transition = _transition()
    coverage = _coverage()
    batch = StateTransitionBatch.create(
        transitions=(transition,),
        coverage=(coverage,),
        recorded_at=NOW + timedelta(seconds=2),
    )
    connection = _Connection(
        [
            [{"batch_id": batch.batch_id, "recorded_at": batch.recorded_at}],
            [
                {
                    "transition_id": transition.transition_id,
                    "idempotency_key": transition.idempotency_key,
                    "subject_ref": transition.subject_ref,
                    "subject_type": transition.subject_type,
                    "state_type": transition.state_type,
                    "from_state": transition.from_state,
                    "to_state": transition.to_state,
                    "lane": transition.lane.value,
                    "authority": transition.authority.value,
                    "effective_at": transition.effective_at,
                    "evidence_cutoff": transition.evidence_cutoff,
                    "recorded_at": transition.recorded_at,
                    "source_identity": transition.source_identity,
                    "source_revision": transition.source_revision,
                    "producer_id": transition.producer_id,
                    "producer_version": transition.producer_version,
                    "freshness_ceiling_seconds": transition.freshness_ceiling_seconds,
                    "completeness_basis_points": transition.completeness_basis_points,
                    "evidence_refs": list(transition.evidence_refs),
                    "conflicts": list(transition.conflicts),
                    "correlation_refs": list(transition.correlation_refs),
                    "synthetic": transition.synthetic,
                    "execution_authority": False,
                }
            ],
            [
                {
                    "coverage_id": coverage.coverage_id,
                    "subject_ref": coverage.subject_ref,
                    "state_type": coverage.state_type,
                    "coverage_start_at": coverage.coverage_start_at,
                    "coverage_end_at": coverage.coverage_end_at,
                    "recorded_at": coverage.recorded_at,
                    "source_identity": coverage.source_identity,
                    "source_revision": coverage.source_revision,
                    "watermark": coverage.watermark,
                    "evidence_ref": coverage.evidence_ref,
                    "complete": coverage.complete,
                    "limitation": coverage.limitation,
                    "synthetic": coverage.synthetic,
                }
            ],
        ],
        replay=True,
    )

    inserted = await _store(connection).append(batch)

    assert inserted is False
    assert len(connection.many) == 0


async def test_batch_replay_rejects_missing_retained_children() -> None:
    batch = StateTransitionBatch.create(
        transitions=(_transition(),),
        coverage=(_coverage(),),
        recorded_at=NOW + timedelta(seconds=2),
    )
    connection = _Connection(
        [[{"batch_id": batch.batch_id, "recorded_at": batch.recorded_at}], [], []],
        replay=True,
    )

    with pytest.raises(ValueError, match="replay does not match"):
        await _store(connection).append(batch)


def test_store_rejects_unbounded_configuration() -> None:
    try:
        PostgresStateTransitionStoreConfig(dsn="")
    except ValueError as exc:
        assert "dsn" in str(exc)
    else:
        raise AssertionError("empty state transition DSN was accepted")


def test_service_migration_enforces_domain_bounds_in_executed_sql() -> None:
    migration = (
        REPO_ROOT
        / "service-migrations/branches/core-control-plane/versions"
        / "20260902_core_operational_state_transitions.py"
    ).read_text(encoding="utf-8")

    assert "_UPGRADE_SQL" not in migration
    assert "fdai_text_array_elements_bounded(evidence_refs, 64, 512)" in migration
    assert "fdai_text_array_elements_bounded(conflicts, 64, 512)" in migration
    assert "char_length(subject_ref) BETWEEN 1 AND 512" in migration
