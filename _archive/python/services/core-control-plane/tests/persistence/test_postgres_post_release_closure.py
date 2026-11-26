"""PostgreSQL atomic post-release closure store tests."""

from __future__ import annotations

import asyncio
import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fdai.core.executor.idempotency_reservation import (
    reservation_record_to_mapping,
)
from fdai.core.executor.post_release_closure import (
    PostReleaseClosureOutcome,
    ReconciliationEvidenceKind,
    ReconciliationOutcome,
    audit_closure_mapping,
    closure_outbox_mapping,
)
from fdai.core.executor.post_release_closure_codec import (
    post_release_closure_to_mapping,
)
from fdai.core.executor.post_release_closure_plan import (
    PostReleaseClosurePlan,
    build_reconciled_post_release_closure,
)
from fdai.core.executor.post_release_closure_store import (
    PostReleaseClosureWriteDecision,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import AuthoritativeSinkState
from fdai.core.executor.safeguard_dispatch_codec import (
    safeguard_dispatch_record_to_mapping,
)
from fdai.core.executor.target_dispatch_fence_codec import (
    target_dispatch_fence_to_mapping,
)
from fdai.delivery.persistence.postgres_idempotency_reservation import (
    reservation_storage_key,
)
from fdai.delivery.persistence.postgres_post_release_closure import (
    PostgresPostReleaseClosureStore,
    PostgresPostReleaseClosureStoreConfig,
    PostReleaseClosureCompareAndSetError,
)

from tests.core.executor.test_post_release_closure import (
    _NOW,
    _initial_plan,
    _reconciliation_evidence,
)


class _Cursor:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, object] | None:
        return deepcopy(self._row)


class _Transaction:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection
        self._snapshot: tuple[dict[str, object], ...] | None = None

    async def __aenter__(self) -> _Transaction:
        self._snapshot = self._connection.snapshot()
        return self

    async def __aexit__(
        self,
        exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> bool:
        if exc_type is not None:
            assert self._snapshot is not None
            self._connection.restore(self._snapshot)
        return False


class _Connection:
    def __init__(self) -> None:
        self.closures: dict[str, dict[str, object]] = {}
        self.reservations: dict[str, dict[str, object]] = {}
        self.fences: dict[str, dict[str, object]] = {}
        self.pre_releases: dict[tuple[str, int], dict[str, object]] = {}
        self.audits: dict[tuple[str, int], dict[str, object]] = {}
        self.outbox: dict[str, dict[str, object]] = {}
        self.fail_on: str | None = None

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    def snapshot(self) -> tuple[dict[str, object], ...]:
        return (
            deepcopy(self.closures),
            deepcopy(self.reservations),
            deepcopy(self.fences),
            deepcopy(self.pre_releases),
            deepcopy(self.audits),
            deepcopy(self.outbox),
        )

    def restore(self, snapshot: tuple[dict[str, object], ...]) -> None:
        (
            self.closures,
            self.reservations,
            self.fences,
            self.pre_releases,
            self.audits,
            self.outbox,
        ) = deepcopy(snapshot)

    async def execute(
        self,
        sql: str,
        params: tuple[object, ...] | None = None,
    ) -> _Cursor:
        normalized = " ".join(sql.split())
        if self.fail_on is not None and normalized.startswith(self.fail_on):
            raise RuntimeError("injected transaction failure")
        if normalized.startswith(("SELECT set_config", "SELECT pg_advisory_xact_lock")):
            return _Cursor(None)
        assert params is not None
        if normalized.startswith("SELECT record, recorded_at, clock_timestamp()"):
            row = self.closures.get(str(params[0]))
            return _Cursor(deepcopy(row) if row is not None else None)
        if normalized.startswith("SELECT record, recorded_at FROM safeguard_dispatch_evidence"):
            row = self.pre_releases.get((str(params[0]), int(params[1])))
            return _Cursor(deepcopy(row) if row is not None else None)
        if normalized.startswith(
            "SELECT result, recorded_at FROM executor_idempotency_reservation"
        ):
            row = self.reservations.get(str(params[0]))
            return _Cursor(deepcopy(row) if row is not None else None)
        if normalized.startswith("SELECT record, recorded_at FROM target_dispatch_fence"):
            row = self.fences.get(str(params[0]))
            return _Cursor(deepcopy(row) if row is not None else None)
        if normalized.startswith("UPDATE executor_idempotency_reservation"):
            key = str(params[1])
            row = self.reservations.get(key)
            if row is None or row["result"] != json.loads(str(params[2])):
                return _Cursor(None)
            row["result"] = json.loads(str(params[0]))
            row["recorded_at"] = _NOW + timedelta(seconds=7)
            return _Cursor({"recorded_at": row["recorded_at"]})
        if normalized.startswith("UPDATE target_dispatch_fence"):
            key = str(params[6])
            row = self.fences.get(key)
            if row is None:
                return _Cursor(None)
            current = row["record"]
            assert isinstance(current, dict)
            if current["revision"] != params[7] or current["record_digest"] != params[8]:
                return _Cursor(None)
            row["record"] = json.loads(str(params[5]))
            row["recorded_at"] = _NOW + timedelta(seconds=7)
            return _Cursor({"recorded_at": row["recorded_at"]})
        if normalized.startswith("INSERT INTO executor_post_release_closure"):
            key = str(params[0])
            if key in self.closures:
                return _Cursor(None)
            self.closures[key] = {
                "record": json.loads(str(params[9])),
                "recorded_at": _NOW + timedelta(seconds=7),
                "read_back_at": _NOW + timedelta(seconds=7),
            }
            return _Cursor({"recorded_at": self.closures[key]["recorded_at"]})
        if normalized.startswith("UPDATE executor_post_release_closure"):
            key = str(params[4])
            row = self.closures.get(key)
            if row is None:
                return _Cursor(None)
            current = row["record"]
            assert isinstance(current, dict)
            if current["revision"] != params[5] or current["record_digest"] != params[6]:
                return _Cursor(None)
            row["record"] = json.loads(str(params[3]))
            row["recorded_at"] = _NOW + timedelta(seconds=7)
            row["read_back_at"] = _NOW + timedelta(seconds=7)
            return _Cursor({"recorded_at": row["recorded_at"]})
        if normalized.startswith("INSERT INTO executor_audit_closure"):
            key = (str(params[0]), int(params[1]))
            self.audits.setdefault(
                key,
                {"record": json.loads(str(params[4]))},
            )
            return _Cursor(None)
        if normalized.startswith("SELECT record FROM executor_audit_closure"):
            row = self.audits.get((str(params[0]), int(params[1])))
            return _Cursor(deepcopy(row) if row is not None else None)
        if normalized.startswith("INSERT INTO executor_post_release_outbox"):
            key = str(params[0])
            self.outbox.setdefault(
                key,
                {"payload": json.loads(str(params[4]))},
            )
            return _Cursor(None)
        if normalized.startswith("SELECT payload FROM executor_post_release_outbox"):
            row = self.outbox.get(str(params[0]))
            return _Cursor(deepcopy(row) if row is not None else None)
        raise AssertionError(f"unexpected SQL: {normalized}")

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _store(
    monkeypatch: pytest.MonkeyPatch,
    connection: _Connection,
) -> PostgresPostReleaseClosureStore:
    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    return PostgresPostReleaseClosureStore(
        config=PostgresPostReleaseClosureStoreConfig(
            dsn="postgresql://example",
        )
    )


def _seed(connection: _Connection, plan: PostReleaseClosurePlan) -> None:
    identity = plan.record.identity
    connection.pre_releases[(identity.target_digest, identity.target_fence_generation)] = {
        "record": safeguard_dispatch_record_to_mapping(plan.pre_release_record),
        "recorded_at": plan.pre_release_record.state_changed_at,
    }
    connection.reservations[
        reservation_storage_key(plan.prior_reservation_record.identity.idempotency_key)
    ] = {
        "result": reservation_record_to_mapping(plan.prior_reservation_record),
        "recorded_at": plan.prior_reservation_record.state_changed_at,
    }
    connection.fences[identity.target_digest] = {
        "record": target_dispatch_fence_to_mapping(plan.prior_fence_record),
        "recorded_at": plan.prior_fence_record.state_changed_at,
    }


@pytest.mark.asyncio
async def test_atomic_write_replay_restart_and_outbox_dedupe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _initial_plan(sink_state=AuthoritativeSinkState.COMMITTED)
    connection = _Connection()
    _seed(connection, plan)
    store = _store(monkeypatch, connection)

    applied = await store.write(plan)
    duplicate = await store.write(plan)
    restarted = _store(monkeypatch, connection)

    assert applied.decision is PostReleaseClosureWriteDecision.APPLIED
    assert duplicate.decision is PostReleaseClosureWriteDecision.DUPLICATE_SAME
    assert await restarted.read(plan.record.identity.closure_key) == plan.record
    assert len(connection.audits) == 1
    assert len(connection.outbox) == 1
    assert next(iter(connection.audits.values()))["record"] == audit_closure_mapping(plan.record)
    assert next(iter(connection.outbox.values()))["payload"] == closure_outbox_mapping(plan.record)


@pytest.mark.asyncio
async def test_transaction_failure_rolls_back_every_terminal_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _initial_plan(sink_state=AuthoritativeSinkState.COMMITTED)
    connection = _Connection()
    _seed(connection, plan)
    before = connection.snapshot()
    connection.fail_on = "INSERT INTO executor_audit_closure"
    store = _store(monkeypatch, connection)

    with pytest.raises(RuntimeError, match="injected transaction failure"):
        await store.write(plan)

    assert connection.snapshot() == before


@pytest.mark.asyncio
async def test_conflicting_same_attempt_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _initial_plan(sink_state=AuthoritativeSinkState.COMMITTED)
    conflict = _initial_plan(sink_state=AuthoritativeSinkState.ACCEPTED)
    connection = _Connection()
    _seed(connection, plan)
    store = _store(monkeypatch, connection)
    await store.write(plan)

    with pytest.raises(
        PostReleaseClosureCompareAndSetError,
        match="predecessor changed",
    ):
        await store.write(conflict)


@pytest.mark.asyncio
async def test_quarantine_reconciliation_updates_same_closure_and_dedupes_each_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = _initial_plan(sink_state=AuthoritativeSinkState.ACCEPTED)
    evidence = _reconciliation_evidence(
        initial,
        kind=ReconciliationEvidenceKind.AUTHORITATIVE_SINK_STATUS,
        outcome=ReconciliationOutcome.SINK_IRREVOCABLY_NOT_ACCEPTED,
    )
    reconciled = build_reconciled_post_release_closure(
        prior_closure=initial.record,
        pre_release_record=initial.pre_release_record,
        reservation_record=initial.reservation_record,
        quarantined_fence=initial.fence_record,
        release_receipt=initial.release_receipt,
        evidence=evidence,
        reconciled_at=_NOW + timedelta(seconds=6),
    )
    connection = _Connection()
    _seed(connection, initial)
    store = _store(monkeypatch, connection)

    first = await store.write(initial)
    second = await store.write(reconciled)
    duplicate = await store.write(reconciled)

    assert first.record.outcome is PostReleaseClosureOutcome.QUARANTINED
    assert second.record.outcome is PostReleaseClosureOutcome.RESOLVED
    assert duplicate.decision is PostReleaseClosureWriteDecision.DUPLICATE_SAME
    assert len(connection.audits) == 2
    assert len(connection.outbox) == 2


@pytest.mark.asyncio
async def test_duplicate_readback_rejects_corrupt_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _initial_plan(sink_state=AuthoritativeSinkState.COMMITTED)
    connection = _Connection()
    _seed(connection, plan)
    store = _store(monkeypatch, connection)
    await store.write(plan)
    connection.outbox[plan.record.outbox_event_id]["payload"] = {"corrupt": True}

    with pytest.raises(ValueError, match="outbox readback mismatched"):
        await store.write(plan)


@pytest.mark.asyncio
async def test_duplicate_readback_does_not_repair_missing_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _initial_plan(sink_state=AuthoritativeSinkState.COMMITTED)
    connection = _Connection()
    _seed(connection, plan)
    store = _store(monkeypatch, connection)
    await store.write(plan)
    connection.audits.clear()

    with pytest.raises(ValueError, match="audit closure readback mismatched"):
        await store.write(plan)

    assert connection.audits == {}


@pytest.mark.asyncio
async def test_write_rejects_stale_pre_release_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _initial_plan(sink_state=AuthoritativeSinkState.COMMITTED)
    connection = _Connection()
    _seed(connection, plan)
    key = (
        plan.record.identity.target_digest,
        plan.record.identity.target_fence_generation,
    )
    connection.pre_releases[key]["record"] = post_release_closure_to_mapping(plan.record)
    store = _store(monkeypatch, connection)

    with pytest.raises(
        (PostReleaseClosureCompareAndSetError, ValueError),
    ):
        await store.write(plan)


@pytest.mark.asyncio
async def test_live_postgres_atomic_replay_and_readback() -> None:
    dsn = os.environ.get("FDAI_TEST_POST_RELEASE_CLOSURE_DSN", "").strip()
    if not dsn:
        pytest.skip("FDAI_TEST_POST_RELEASE_CLOSURE_DSN is not configured")
    now = datetime.now(UTC) - timedelta(seconds=10)
    plan = _initial_plan(
        sink_state=AuthoritativeSinkState.ACCEPTED,
        action_name=f"live-post-release-{os.getpid()}",
        idempotency_key=f"live-post-release-{os.getpid()}",
        target_resource_ref=f"resource/live-post-release-{os.getpid()}",
        now=now,
    )
    config = PostgresPostReleaseClosureStoreConfig(dsn=dsn)
    store = PostgresPostReleaseClosureStore(config=config)
    identity = plan.record.identity
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=False) as connection:
        async with connection.transaction():
            await connection.execute(
                "INSERT INTO safeguard_dispatch_evidence "
                "(target_digest, generation, revision, state, "
                "evidence_identity_digest, record_digest, record) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)",
                (
                    identity.target_digest,
                    identity.target_fence_generation,
                    plan.pre_release_record.revision,
                    plan.pre_release_record.state.value,
                    identity.evidence_identity_digest,
                    plan.pre_release_record.record_digest,
                    json.dumps(
                        safeguard_dispatch_record_to_mapping(plan.pre_release_record),
                        sort_keys=True,
                    ),
                ),
            )
            await connection.execute(
                "INSERT INTO executor_idempotency_reservation "
                "(idempotency_key, result) VALUES (%s, %s::jsonb)",
                (
                    reservation_storage_key(plan.prior_reservation_record.identity.idempotency_key),
                    json.dumps(
                        reservation_record_to_mapping(plan.prior_reservation_record),
                        sort_keys=True,
                    ),
                ),
            )
            await connection.execute(
                "INSERT INTO target_dispatch_fence "
                "(target_digest, generation, revision, state, identity_digest, "
                "record_digest, record) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)",
                (
                    identity.target_digest,
                    identity.target_fence_generation,
                    plan.prior_fence_record.revision,
                    plan.prior_fence_record.state.value,
                    plan.prior_fence_record.identity.identity_digest,
                    plan.prior_fence_record.record_digest,
                    json.dumps(
                        target_dispatch_fence_to_mapping(plan.prior_fence_record),
                        sort_keys=True,
                    ),
                ),
            )

    first, second = await asyncio.gather(
        store.write(plan),
        store.write(plan),
    )
    restarted = PostgresPostReleaseClosureStore(config=config)

    assert {
        first.decision,
        second.decision,
    } == {
        PostReleaseClosureWriteDecision.APPLIED,
        PostReleaseClosureWriteDecision.DUPLICATE_SAME,
    }
    assert await restarted.read(identity.closure_key) == plan.record
    evidence = _reconciliation_evidence(
        plan,
        kind=ReconciliationEvidenceKind.AUTHORITATIVE_SINK_STATUS,
        outcome=ReconciliationOutcome.SINK_IRREVOCABLY_NOT_ACCEPTED,
        now=now,
    )
    reconciled = build_reconciled_post_release_closure(
        prior_closure=plan.record,
        pre_release_record=plan.pre_release_record,
        reservation_record=plan.reservation_record,
        quarantined_fence=plan.fence_record,
        release_receipt=plan.release_receipt,
        evidence=evidence,
        reconciled_at=now + timedelta(seconds=6),
    )
    reconciliation_receipt = await restarted.write(reconciled)
    assert reconciliation_receipt.record.outcome is PostReleaseClosureOutcome.RESOLVED
    assert await restarted.read(identity.closure_key) == reconciled.record
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        audit_count = await (
            await connection.execute(
                "SELECT count(*) FROM executor_audit_closure WHERE closure_key = %s",
                (identity.closure_key,),
            )
        ).fetchone()
        outbox_count = await (
            await connection.execute(
                "SELECT count(*) FROM executor_post_release_outbox WHERE closure_key = %s",
                (identity.closure_key,),
            )
        ).fetchone()
    assert audit_count == (2,)
    assert outbox_count == (2,)
