"""PostgreSQL safeguard dispatch evidence store tests."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationIdentity,
)
from fdai.core.executor.safeguard_bundle_context import (
    SafeguardBundlePersistenceContext,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    ContinuityUnprovenReason,
    DispatchTransportState,
    PreReleaseOwnershipCheckpoint,
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchObservation,
    record_dispatch_observation,
    record_dispatch_start,
    record_pre_release_checkpoint,
)
from fdai.core.executor.safeguard_dispatch_store import (
    SafeguardDispatchPersistenceDecision,
    SafeguardDispatchTransitionReceipt,
)
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceRecord,
    attach_prepared_evidence,
    mark_target_fence_in_flight,
)
from fdai.delivery.persistence.postgres_safeguard_dispatch import (
    PostgresSafeguardDispatchEvidenceStore,
    PostgresSafeguardDispatchEvidenceStoreConfig,
    SafeguardDispatchCompareAndSetError,
)
from fdai.shared.providers.resource_lock import LiveLockOwnershipAssessment

from tests.core.executor.test_safeguard_dispatch_checkpoint import (
    _DIGEST,
    _NOW,
    _assessment,
    _bundle_record,
    _evidence_fixture,
    _in_flight_reservation,
)


class _Cursor:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, object] | None:
        return self._row


class _Transaction:
    async def __aenter__(self) -> _Transaction:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Connection:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, int], dict[str, object]] = {}

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(
        self,
        sql: str,
        params: tuple[object, ...] | None = None,
    ) -> _Cursor:
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT set_config"):
            return _Cursor(None)
        assert params is not None
        if normalized.startswith("SELECT record, recorded_at"):
            key = (str(params[0]), int(params[1]))
            row = self.rows.get(key)
            return _Cursor(dict(row) if row is not None else None)
        if normalized.startswith("INSERT INTO safeguard_dispatch_evidence"):
            key = (str(params[0]), int(params[1]))
            if key in self.rows:
                return _Cursor(None)
            record = json.loads(str(params[6]))
            self.rows[key] = {
                "record": record,
                "recorded_at": datetime.fromisoformat(str(record["state_changed_at"])),
            }
            return _Cursor({"recorded_at": self.rows[key]["recorded_at"]})
        if normalized.startswith("UPDATE safeguard_dispatch_evidence"):
            key = (str(params[5]), int(params[6]))
            row = self.rows.get(key)
            if row is None:
                return _Cursor(None)
            current = row["record"]
            assert isinstance(current, dict)
            if current["revision"] != params[7] or current["record_digest"] != params[8]:
                return _Cursor(None)
            record = json.loads(str(params[4]))
            row["record"] = record
            row["recorded_at"] = datetime.fromisoformat(str(record["state_changed_at"]))
            return _Cursor({"recorded_at": row["recorded_at"]})
        raise AssertionError(f"unexpected SQL: {normalized}")

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _store(
    monkeypatch: pytest.MonkeyPatch,
    connection: _Connection,
) -> PostgresSafeguardDispatchEvidenceStore:
    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    return PostgresSafeguardDispatchEvidenceStore(
        config=PostgresSafeguardDispatchEvidenceStoreConfig(
            dsn="postgresql://example",
        )
    )


def _pre_release_record(
    observed: SafeguardDispatchEvidenceRecord,
    *,
    reservation: IdempotencyReservationIdentity,
) -> tuple[SafeguardDispatchEvidenceRecord, LiveLockOwnershipAssessment]:
    assessment = _assessment(reservation)
    observation = observed.dispatch_observation
    assert observation is not None
    checkpoint = PreReleaseOwnershipCheckpoint.from_assessment(
        evidence_identity=observed.identity,
        assessment=assessment,
        not_before=observation.observed_at,
        observed_at=_NOW + timedelta(seconds=2),
    )
    return (
        record_pre_release_checkpoint(
            observed,
            checkpoint=checkpoint,
            current_lock_assessment=assessment,
            changed_at=checkpoint.observed_at,
        ),
        assessment,
    )


def _start_record(
    record: SafeguardDispatchEvidenceRecord,
    *,
    persistence_receipt: SafeguardDispatchTransitionReceipt,
    prepared: TargetDispatchFenceRecord,
    context: SafeguardBundlePersistenceContext,
    at: datetime,
) -> SafeguardDispatchEvidenceRecord:
    return record_dispatch_start(
        record,
        bundle_persistence_receipt=persistence_receipt,
        in_flight_reservation_receipt=_in_flight_reservation(context, at=at),
        prepared_fence=prepared,
        in_flight_fence=mark_target_fence_in_flight(prepared, changed_at=at),
        dispatch_started_at=at,
        changed_at=at,
    )


@pytest.mark.asyncio
async def test_generation_unique_insert_duplicate_and_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = _store(monkeypatch, connection)
    record, _reservation = _bundle_record()
    conflict = _evidence_fixture(action_name="other")[0]
    assert conflict.identity.target_digest == record.identity.target_digest
    assert conflict.identity.target_fence_generation == record.identity.target_fence_generation

    persisted = await store.persist_bundle(record)
    duplicate = await store.persist_bundle(record)
    conflicting = await store.persist_bundle(conflict)

    assert persisted.decision is SafeguardDispatchPersistenceDecision.PERSISTED
    assert persisted.transition_receipt is not None
    assert duplicate.decision is SafeguardDispatchPersistenceDecision.DUPLICATE_SAME
    assert duplicate.transition_receipt is None
    assert conflicting.decision is SafeguardDispatchPersistenceDecision.CONFLICT
    assert conflicting.observed_record == record


@pytest.mark.asyncio
async def test_exact_cas_and_restart_read_preserve_every_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = _store(monkeypatch, connection)
    bundle, reservation, _preparing, prepared, context = _evidence_fixture()
    persisted = await store.persist_bundle(bundle)
    assert persisted.transition_receipt is not None
    restarted = _store(monkeypatch, connection)
    assert (
        await restarted.read(
            bundle.identity.target_digest,
            bundle.identity.target_fence_generation,
        )
        == bundle
    )

    started = _start_record(
        bundle,
        persistence_receipt=persisted.transition_receipt,
        prepared=prepared,
        context=context,
        at=_NOW,
    )
    await restarted.compare_and_transition(
        prior_record_digest=bundle.record_digest,
        expected_revision=bundle.revision,
        record=started,
        bundle_persistence_receipt=persisted.transition_receipt,
    )
    recovered_started = await restarted.read(
        bundle.identity.target_digest,
        bundle.identity.target_fence_generation,
    )
    assert recovered_started == started
    observation = SafeguardDispatchObservation.create(
        dispatch_start_record=recovered_started,
        transport_state=DispatchTransportState.ACKNOWLEDGED,
        sink_state=AuthoritativeSinkState.ACCEPTED,
        sink_operation_reference_digest=_DIGEST,
        authoritative_status_digest=_DIGEST,
        observed_at=_NOW + timedelta(seconds=1),
    )
    observed = record_dispatch_observation(
        started,
        observation=observation,
        changed_at=observation.observed_at,
    )
    transition = await restarted.compare_and_transition(
        prior_record_digest=started.record_digest,
        expected_revision=started.revision,
        record=observed,
    )
    assert transition.prior_record == started
    assert transition.record == observed

    pre_release, assessment = _pre_release_record(
        observed,
        reservation=reservation,
    )
    await restarted.compare_and_transition(
        prior_record_digest=observed.record_digest,
        expected_revision=observed.revision,
        record=pre_release,
        current_lock_assessment=assessment,
    )
    restarted_again = _store(monkeypatch, connection)
    assert (
        await restarted_again.read(
            bundle.identity.target_digest,
            bundle.identity.target_fence_generation,
        )
        == pre_release
    )


@pytest.mark.asyncio
async def test_stale_cas_and_corrupt_readback_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = _store(monkeypatch, connection)
    bundle, _reservation, _preparing, prepared, context = _evidence_fixture()
    persisted = await store.persist_bundle(bundle)
    assert persisted.transition_receipt is not None
    started = _start_record(
        bundle,
        persistence_receipt=persisted.transition_receipt,
        prepared=prepared,
        context=context,
        at=_NOW,
    )

    with pytest.raises(SafeguardDispatchCompareAndSetError):
        await store.compare_and_transition(
            prior_record_digest="sha256:" + "0" * 64,
            expected_revision=bundle.revision,
            record=started,
            bundle_persistence_receipt=persisted.transition_receipt,
        )
    row = next(iter(connection.rows.values()))
    raw_record = row["record"]
    assert isinstance(raw_record, dict)
    row["record"] = {**raw_record, "unexpected": True}
    with pytest.raises(ValueError, match="fields are invalid"):
        await store.read(
            bundle.identity.target_digest,
            bundle.identity.target_fence_generation,
        )


@pytest.mark.asyncio
async def test_continuity_unproven_checkpoint_is_durable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = _store(monkeypatch, connection)
    bundle, _reservation, _preparing, prepared, context = _evidence_fixture()
    persisted = await store.persist_bundle(bundle)
    assert persisted.transition_receipt is not None
    started = _start_record(
        bundle,
        persistence_receipt=persisted.transition_receipt,
        prepared=prepared,
        context=context,
        at=_NOW,
    )
    await store.compare_and_transition(
        prior_record_digest=bundle.record_digest,
        expected_revision=bundle.revision,
        record=started,
        bundle_persistence_receipt=persisted.transition_receipt,
    )
    observation = SafeguardDispatchObservation.create(
        dispatch_start_record=started,
        transport_state=DispatchTransportState.UNKNOWN,
        sink_state=AuthoritativeSinkState.UNKNOWN,
        sink_operation_reference_digest=None,
        authoritative_status_digest=None,
        observed_at=_NOW + timedelta(seconds=1),
    )
    observed = record_dispatch_observation(
        started,
        observation=observation,
        changed_at=observation.observed_at,
    )
    await store.compare_and_transition(
        prior_record_digest=started.record_digest,
        expected_revision=started.revision,
        record=observed,
    )
    checkpoint = PreReleaseOwnershipCheckpoint.unproven(
        evidence_identity=bundle.identity,
        reason=ContinuityUnprovenReason.CALLBACK_FAILED,
        observed_at=observation.observed_at,
    )
    pre_release = record_pre_release_checkpoint(
        observed,
        checkpoint=checkpoint,
        changed_at=checkpoint.observed_at,
    )
    await store.compare_and_transition(
        prior_record_digest=observed.record_digest,
        expected_revision=observed.revision,
        record=pre_release,
    )

    assert (
        await store.read(
            bundle.identity.target_digest,
            bundle.identity.target_fence_generation,
        )
        == pre_release
    )


def test_config_and_read_key_reject_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresSafeguardDispatchEvidenceStore(
            config=PostgresSafeguardDispatchEvidenceStoreConfig(dsn="")
        )
    with pytest.raises(ValueError, match="statement_timeout"):
        PostgresSafeguardDispatchEvidenceStore(
            config=PostgresSafeguardDispatchEvidenceStoreConfig(
                dsn="postgresql://example",
                statement_timeout_ms=0,
            )
        )


@pytest.mark.asyncio
async def test_live_postgres_contention_restart_and_lifecycle_cas() -> None:
    dsn = os.environ.get("FDAI_TEST_SAFEGUARD_DISPATCH_DSN", "").strip()
    if not dsn:
        pytest.skip("FDAI_TEST_SAFEGUARD_DISPATCH_DSN is not configured")
    now = datetime.now(UTC)
    record, reservation, preparing, _prepared, context = _evidence_fixture(
        action_name=f"live-{os.getpid()}",
        now=now,
    )
    config = PostgresSafeguardDispatchEvidenceStoreConfig(dsn=dsn)
    first_store = PostgresSafeguardDispatchEvidenceStore(config=config)
    second_store = PostgresSafeguardDispatchEvidenceStore(config=config)

    first, second = await asyncio.gather(
        first_store.persist_bundle(record),
        second_store.persist_bundle(record),
    )
    assert {first.decision, second.decision} == {
        SafeguardDispatchPersistenceDecision.PERSISTED,
        SafeguardDispatchPersistenceDecision.DUPLICATE_SAME,
    }
    persistence_receipt = first.transition_receipt or second.transition_receipt
    assert persistence_receipt is not None
    restarted = PostgresSafeguardDispatchEvidenceStore(config=config)
    assert (
        await restarted.read(
            record.identity.target_digest,
            record.identity.target_fence_generation,
        )
        == record
    )
    start_at = persistence_receipt.recorded_at
    prepared = attach_prepared_evidence(
        preparing,
        audit_append_receipt=context.audit_append_receipt,
        safeguard_bundle_digest=record.bundle.bundle_digest,
        changed_at=start_at,
    )
    started = _start_record(
        record,
        persistence_receipt=persistence_receipt,
        prepared=prepared,
        context=context,
        at=start_at,
    )
    await restarted.compare_and_transition(
        prior_record_digest=record.record_digest,
        expected_revision=record.revision,
        record=started,
        bundle_persistence_receipt=persistence_receipt,
    )
    observation = SafeguardDispatchObservation.create(
        dispatch_start_record=started,
        transport_state=DispatchTransportState.ACKNOWLEDGED,
        sink_state=AuthoritativeSinkState.ACCEPTED,
        sink_operation_reference_digest=_DIGEST,
        authoritative_status_digest=_DIGEST,
        observed_at=start_at,
    )
    observed = record_dispatch_observation(
        started,
        observation=observation,
        changed_at=observation.observed_at,
    )
    await restarted.compare_and_transition(
        prior_record_digest=started.record_digest,
        expected_revision=started.revision,
        record=observed,
    )
    assessment = _assessment(
        reservation,
        now=start_at - timedelta(seconds=2),
    )
    checkpoint = PreReleaseOwnershipCheckpoint.from_assessment(
        evidence_identity=record.identity,
        assessment=assessment,
        not_before=observation.observed_at,
        observed_at=start_at,
    )
    pre_release = record_pre_release_checkpoint(
        observed,
        checkpoint=checkpoint,
        current_lock_assessment=assessment,
        changed_at=checkpoint.observed_at,
    )
    await restarted.compare_and_transition(
        prior_record_digest=observed.record_digest,
        expected_revision=observed.revision,
        record=pre_release,
        current_lock_assessment=assessment,
    )
    assert (
        await restarted.read(
            record.identity.target_digest,
            record.identity.target_fence_generation,
        )
        == pre_release
    )
