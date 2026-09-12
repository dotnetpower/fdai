"""PostgreSQL append-only independent effect observation store tests.

The database-backed cases are skipped without a DSN, so the fake-connection
cases below carry the contract that matters offline: the store never claims
a retained receipt it did not read back, and it refuses a different receipt
at an occupied sequence position instead of overwriting it.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai.core.executor.effect_observation import (
    IndependentEffectObservationBinding,
    IndependentEffectObservationReceipt,
    IndependentEffectOutcome,
    ObservationCompleteness,
    ObservationContainment,
    ObservationFinality,
    ObservationQuality,
)
from fdai.core.executor.effect_observation_codec import (
    observation_receipt_to_mapping,
)
from fdai.core.executor.effect_observation_ledger import (
    IndependentEffectLedger,
    IndependentEffectLedgerError,
)
from fdai.core.executor.execution_provenance import (
    SafeguardExecutionOrigin,
    SafeguardExecutionVenue,
)
from fdai.delivery.persistence.postgres_effect_observation import (
    PostgresIndependentEffectObservationStore,
    PostgresIndependentEffectObservationStoreConfig,
)

_NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
_DSN_ENV = "FDAI_TEST_EFFECT_OBSERVATION_DSN"


def _digest(seed: str) -> str:
    return "sha256:" + (seed * 64)[:64]


def _binding(
    *,
    identity_digest: str | None = None,
) -> IndependentEffectObservationBinding:
    return IndependentEffectObservationBinding.create(
        action_id="00000000-0000-0000-0000-000000000001",
        action_payload_digest=_digest("a"),
        target_digest=_digest("b"),
        source_revision="commit:" + "c" * 40,
        execution_path="direct_api",
        execution_origin=SafeguardExecutionOrigin.CORE,
        execution_venue=SafeguardExecutionVenue.ISOLATED_EXECUTOR,
        safeguard_bundle_digest=_digest("d"),
        evidence_identity_digest=identity_digest or _digest("e"),
        evidence_record_digest=_digest("f"),
        evidence_record_revision=1,
        executor_receipt_digest=_digest("1"),
    )


def _receipt(
    *,
    outcome: IndependentEffectOutcome = IndependentEffectOutcome.VERIFIED,
    sequence: int = 1,
    prior: str | None = None,
    binding: IndependentEffectObservationBinding | None = None,
) -> IndependentEffectObservationReceipt:
    quality = ObservationQuality(
        schema_version="1.0.0",
        evidence_window_start=_NOW - timedelta(minutes=5),
        evidence_window_end=_NOW,
        source_recorded_at=_NOW - timedelta(minutes=1),
        max_source_age_seconds=900.0,
        finality=ObservationFinality.FINAL,
        completeness=ObservationCompleteness.COMPLETE,
        containment=ObservationContainment.WITHIN_DECLARED_TARGET,
        conflicting_source_count=0,
        synthetic=False,
    )
    return IndependentEffectObservationReceipt.create(
        observation_id=f"observation-{sequence}",
        binding=binding or _binding(),
        quality=quality,
        outcome=outcome,
        reason="focused persistence test",
        observer_instance_id="fdai.observer",
        executor_instance_id="fdai.executor",
        source_instance_id="azure.arm",
        observed_at=_NOW,
        completed_at=_NOW + timedelta(seconds=1),
        sequence=sequence,
        prior_receipt_digest=prior,
    )


def _config(dsn: str = "postgresql://fake") -> PostgresIndependentEffectObservationStoreConfig:
    return PostgresIndependentEffectObservationStoreConfig(dsn=dsn)


# -- configuration boundaries -------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"dsn": ""}, "dsn MUST NOT be empty"),
        ({"statement_timeout_ms": 0}, "statement_timeout_ms"),
        ({"connect_timeout_s": 0}, "connect_timeout_s"),
    ),
)
def test_an_unusable_configuration_is_refused(
    overrides: dict[str, Any],
    message: str,
) -> None:
    values: dict[str, Any] = {"dsn": "postgresql://fake"}
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        PostgresIndependentEffectObservationStore(
            config=PostgresIndependentEffectObservationStoreConfig(**values)
        )


@pytest.mark.asyncio
async def test_a_foreign_object_is_never_persisted() -> None:
    store = PostgresIndependentEffectObservationStore(config=_config())

    with pytest.raises(IndependentEffectLedgerError, match="exact receipt"):
        await store.append(object())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_malformed_lineage_key_is_refused_before_any_query() -> None:
    store = PostgresIndependentEffectObservationStore(config=_config())

    with pytest.raises(ValueError, match="MUST be SHA-256"):
        await store.read_lineage("not-a-digest")


# -- fake-connection behaviour ------------------------------------------------


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _Transaction:
    async def __aenter__(self) -> _Transaction:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Connection:
    """Return a scripted readback so append semantics are testable offline."""

    def __init__(self, readback: dict[str, Any] | None) -> None:
        self._readback = readback
        self.statements: list[str] = []

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(self, statement: str, params: object = None) -> _Cursor:
        del params
        self.statements.append(statement)
        if statement.startswith("SELECT"):
            return _Cursor([self._readback] if self._readback is not None else [])
        return _Cursor([])


def _bind(
    store: PostgresIndependentEffectObservationStore,
    connection: _Connection,
) -> None:
    async def _connect() -> _Connection:
        return connection

    store._connect = _connect  # type: ignore[assignment, method-assign]


@pytest.mark.asyncio
async def test_a_replayed_receipt_returns_the_retained_row() -> None:
    receipt = _receipt()
    store = PostgresIndependentEffectObservationStore(config=_config())
    _bind(store, _Connection({"receipt": observation_receipt_to_mapping(receipt)}))

    retained = await store.append(receipt)

    assert retained == receipt


@pytest.mark.asyncio
async def test_a_different_receipt_may_not_overwrite_an_occupied_position() -> None:
    retained = _receipt()
    store = PostgresIndependentEffectObservationStore(config=_config())
    _bind(store, _Connection({"receipt": observation_receipt_to_mapping(retained)}))

    conflicting = _receipt(outcome=IndependentEffectOutcome.FAILED)

    with pytest.raises(IndependentEffectLedgerError, match="already occupies"):
        await store.append(conflicting)


@pytest.mark.asyncio
async def test_a_vanished_readback_is_an_error_not_a_silent_success() -> None:
    store = PostgresIndependentEffectObservationStore(config=_config())
    _bind(store, _Connection(None))

    with pytest.raises(IndependentEffectLedgerError, match="no retained receipt"):
        await store.append(_receipt())


@pytest.mark.asyncio
async def test_the_store_never_issues_a_mutating_statement() -> None:
    receipt = _receipt()
    store = PostgresIndependentEffectObservationStore(config=_config())
    connection = _Connection({"receipt": observation_receipt_to_mapping(receipt)})
    _bind(store, connection)

    await store.append(receipt)

    joined = " ".join(connection.statements).upper()
    assert "UPDATE INDEPENDENT_EFFECT_OBSERVATION" not in joined
    assert "DELETE FROM INDEPENDENT_EFFECT_OBSERVATION" not in joined


# -- database-backed contract -------------------------------------------------


def _dsn() -> str:
    dsn = os.environ.get(_DSN_ENV, "").strip()
    if not dsn:
        pytest.skip(f"{_DSN_ENV} is not configured")
    return dsn


@pytest.mark.asyncio
async def test_the_database_retains_one_immutable_lineage() -> None:
    store = PostgresIndependentEffectObservationStore(config=_config(_dsn()))
    identity = _digest("3")
    ledger = IndependentEffectLedger(store=store)
    first = _receipt(
        outcome=IndependentEffectOutcome.UNAVAILABLE,
        binding=_binding(identity_digest=identity),
    )

    state = await ledger.record(first)
    assert state.effect_verified is False

    replayed = await ledger.record(first)
    assert replayed.observation_count == 1

    lineage = await store.read_lineage(identity)
    assert [receipt.receipt_digest for receipt in lineage] == [first.receipt_digest]


def test_the_migration_grants_no_mutation_privilege() -> None:
    migration = (
        Path(__file__).resolve().parents[4]
        / "service-migrations"
        / "branches"
        / "core-control-plane"
        / "versions"
        / "20260913_core_effect_observation.py"
    )
    text = migration.read_text(encoding="utf-8")

    assert "GRANT SELECT, INSERT ON TABLE independent_effect_observation" in text
    assert "GRANT SELECT, INSERT, UPDATE" not in text
    assert "independent_effect_observation_identities_distinct" in text


@pytest.mark.asyncio
async def test_the_lineage_read_runs_inside_a_bounded_transaction() -> None:
    """SET LOCAL is discarded outside a transaction under autocommit.

    Without the surrounding transaction the configured statement timeout
    would silently not apply to an unbounded lineage read.
    """

    class _TrackingConnection(_Connection):
        def __init__(self) -> None:
            super().__init__(None)
            self.transactions = 0

        def transaction(self) -> _Transaction:
            self.transactions += 1
            return _Transaction()

    store = PostgresIndependentEffectObservationStore(config=_config())
    connection = _TrackingConnection()
    _bind(store, connection)

    assert await store.read_lineage(_digest("e")) == ()
    assert connection.transactions == 1
    assert any(statement.startswith("SET LOCAL") for statement in connection.statements)
