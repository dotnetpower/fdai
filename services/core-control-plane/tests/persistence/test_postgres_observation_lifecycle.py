"""PostgreSQL correction closure and lifecycle binding tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import MethodType
from typing import Any

import pytest
from fdai.delivery.persistence import postgres_observation_lifecycle as lifecycle_module
from fdai.delivery.persistence.postgres_observation_lifecycle import (
    _fact_family,
    bind_observation_lifecycle,
    close_observation_corrections,
)
from fdai.delivery.persistence.postgres_operational_history import (
    PostgresOperationalHistoryConfig,
    PostgresOperationalHistoryStore,
)
from fdai.shared.providers.inventory_observation import (
    InventoryMutationKind,
    InventoryObservationKind,
    InventoryObservationSubjectKind,
    NormalizedInventoryObservation,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def _full_observation(
    *, scope_ref: str, resource_name: str = "resource-1"
) -> NormalizedInventoryObservation:
    return NormalizedInventoryObservation.create(
        idempotency_key=f"event:{scope_ref}:{resource_name}",
        subject_kind=InventoryObservationSubjectKind.OBJECT,
        observation_kind=InventoryObservationKind.FULL,
        mutation_kind=InventoryMutationKind.UPSERT,
        subject_ref=f"{scope_ref}/{resource_name}",
        subject_type="compute.vm",
        properties={"state": "ready"},
        property_mask=("state",),
        properties_complete=True,
        links_complete=True,
        tombstone_confirmed=False,
        source_identity="test.inventory",
        source_event_id=f"event:{scope_ref}:{resource_name}",
        source_revision="revision-1",
        effective_at=NOW,
        observed_at=NOW,
        evidence_cutoff=NOW,
        recorded_at=NOW,
        ingested_at=NOW,
        scope_ref=scope_ref,
    )


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _Connection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []

    async def execute(self, query: str, params: object = None) -> _Cursor:
        self.executions.append((query, params))
        if "inventory-ontology:manifest" in query:
            return _Cursor([{"value": {"manifest_digest": DIGEST_A}}])
        if "partition_kind='correction'" in query:
            return _Cursor([{"partition_id": DIGEST_B, "correction_of": DIGEST_A}])
        if "SELECT checkpoint_id" in query:
            return _Cursor([{"checkpoint_id": DIGEST_A}])
        return _Cursor([])

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def transaction(self) -> _Connection:
        return self


class _BoundConnection(_Connection):
    async def execute(self, query: str, params: object = None) -> _Cursor:
        self.executions.append((query, params))
        if "SELECT observation_id FROM inventory_observation_lifecycle_binding" in query:
            assert isinstance(params, tuple)
            return _Cursor([{"observation_id": value} for value in params[0]])
        raise AssertionError("retained binding replay MUST NOT recompute lifecycle state")


async def test_same_scope_day_and_policy_share_one_lifecycle_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    observations = (
        _full_observation(scope_ref="provider/subscription/example", resource_name="one"),
        _full_observation(scope_ref="provider/subscription/example", resource_name="two"),
    )
    partition_batches: list[object] = []
    binding_batches: list[object] = []

    async def existing_bindings(*_args: object) -> frozenset[str]:
        return frozenset()

    async def watermarks(*_args: object) -> dict[str, int]:
        return {
            observations[0].observation_id: 10,
            observations[1].observation_id: 11,
        }

    async def policy_digests(*_args: object) -> dict[str, str]:
        return {"full_observation": DIGEST_A}

    async def latest_times(*_args: object) -> dict[tuple[str, str], datetime]:
        return {}

    async def current_incarnations(*_args: object) -> dict[str, str]:
        return {
            observation.subject_ref: f"incarnation-{index}"
            for index, observation in enumerate(observations)
        }

    async def insert_partitions(_connection: object, values: object) -> None:
        partition_batches.append(values)

    async def insert_bindings(_connection: object, values: object) -> None:
        binding_batches.append(values)

    monkeypatch.setattr(lifecycle_module, "_existing_binding_ids", existing_bindings)
    monkeypatch.setattr(lifecycle_module, "_watermarks", watermarks)
    monkeypatch.setattr(lifecycle_module, "_policy_digests", policy_digests)
    monkeypatch.setattr(lifecycle_module, "_latest_effective_times", latest_times)
    monkeypatch.setattr(lifecycle_module, "_current_incarnations", current_incarnations)
    monkeypatch.setattr(lifecycle_module, "_insert_partitions", insert_partitions)
    monkeypatch.setattr(lifecycle_module, "_insert_bindings", insert_bindings)

    await bind_observation_lifecycle(connection, observations)  # type: ignore[arg-type]

    assert len(partition_batches) == 1
    partitions = partition_batches[0]
    assert isinstance(partitions, tuple)
    assert len(partitions) == 1
    assert partitions[0].first_watermark == 10
    assert partitions[0].last_watermark == 11
    bindings = binding_batches[0]
    assert isinstance(bindings, list)
    assert len(bindings) == 2
    assert {binding[4] for binding in bindings} == {partitions[0].partition_id}


async def test_retained_binding_replay_does_not_reclassify_late_observations() -> None:
    connection = _BoundConnection()
    observation = _full_observation(scope_ref="provider/subscription/example")

    replayed = await bind_observation_lifecycle(
        connection,  # type: ignore[arg-type]
        (observation,),
    )

    assert replayed == frozenset({observation.observation_id})
    assert connection.executions == [
        (
            "SELECT observation_id FROM inventory_observation_lifecycle_binding "
            "WHERE observation_id=ANY(%s::text[])",
            ([observation.observation_id],),
        )
    ]


async def test_projection_closes_pending_correction_with_content_addressed_receipt() -> None:
    connection = _Connection()

    await close_observation_corrections(
        connection,  # type: ignore[arg-type]
        generation="generation-2",
        projection_watermark=10,
        closed_at=NOW,
    )

    inserted = next(
        params
        for query, params in connection.executions
        if "INSERT INTO inventory_observation_correction_receipt" in query
    )
    assert isinstance(inserted, tuple)
    assert str(inserted[0]).startswith("sha256:")
    assert inserted[1] == DIGEST_B
    assert any("SET state='checkpointed'" in query for query, _ in connection.executions)


async def test_concrete_source_purger_calls_only_database_gate() -> None:
    connection = _Connection()
    store = PostgresOperationalHistoryStore(
        config=PostgresOperationalHistoryConfig(dsn="postgresql://unused")
    )

    async def connect(_self: object) -> _Connection:
        return connection

    store._connect = MethodType(connect, store)  # type: ignore[method-assign]
    original_execute = connection.execute

    async def execute(query: str, params: object = None) -> _Cursor:
        if "fdai_purge_observation_partition" in query:
            connection.executions.append((query, params))
            return _Cursor([{"deleted_rows": 1}])
        return await original_execute(query, params)

    connection.execute = execute  # type: ignore[method-assign]

    await store.purge((DIGEST_B,))

    purge_calls = [
        item for item in connection.executions if "fdai_purge_observation_partition" in item[0]
    ]
    assert purge_calls == [
        ("SELECT fdai_purge_observation_partition(%s) AS deleted_rows", (DIGEST_B,))
    ]


async def test_scope_filtered_closure_narrows_to_one_observation_scope() -> None:
    connection = _Connection()

    await close_observation_corrections(
        connection,  # type: ignore[arg-type]
        generation="generation-3",
        projection_watermark=11,
        closed_at=NOW,
        scope_ref="synthetic/oi16-certification/campaign-a",
    )

    selection = next(
        params for query, params in connection.executions if "partition_kind='correction'" in query
    )
    assert isinstance(selection, tuple)
    assert selection == (
        11,
        "synthetic/oi16-certification/campaign-a",
        "synthetic/oi16-certification/campaign-a",
    )


async def test_unscoped_closure_keeps_the_production_projection_behavior() -> None:
    connection = _Connection()

    await close_observation_corrections(
        connection,  # type: ignore[arg-type]
        generation="generation-4",
        projection_watermark=12,
        closed_at=NOW,
    )

    selection = next(
        params for query, params in connection.executions if "partition_kind='correction'" in query
    )
    assert selection == (12, None, None)


async def test_scope_correction_closure_refuses_an_empty_scope() -> None:
    store = PostgresOperationalHistoryStore(
        config=PostgresOperationalHistoryConfig(dsn="postgresql://unused")
    )

    try:
        await store.close_scope_corrections(
            scope_ref="", generation="g", projection_watermark=1, closed_at=NOW
        )
    except ValueError as error:
        assert "outside its bound" in str(error)
    else:  # pragma: no cover - defensive
        raise AssertionError("empty scope MUST be refused")


def test_only_oi16_synthetic_full_observations_select_the_purge_fact_family() -> None:
    synthetic = _full_observation(
        scope_ref="synthetic/oi16-certification/0123456789abcdef0123456789abcdef0123456789abcdef"
    )
    malformed = _full_observation(scope_ref="synthetic/oi16-certification/not-exact")
    ordinary = _full_observation(scope_ref="provider/subscription/example")

    assert _fact_family(synthetic) == "full_observation"
    assert _fact_family(synthetic, allow_oi16_synthetic=True) == "oi16_synthetic_full_observation"
    assert _fact_family(malformed, allow_oi16_synthetic=True) == "full_observation"
    assert _fact_family(ordinary) == "full_observation"
