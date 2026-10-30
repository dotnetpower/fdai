"""Integration test - PostgresStateStore round-trip against a live DB.

Skipped unless ``FDAI_DATABASE_URL`` is set. Run through
``scripts/automation/with-local-test-database.py`` to select the isolated
loopback validation database on port 5433 rather than the runtime database.

The tests here:

- ``append_audit_entry`` writes a row with hash-chained integrity;
- ``read_state`` / ``write_state`` round-trip on ``state_kv``;
- atomic create and prefix reads support immutable command projections;
- ``verify_chain`` returns True after two appends and False after we
  tamper with the persisted hash.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fdai.agents import StateStoreAuditChainAdapter
from fdai.core.case_history import OperationalOutcomeClass
from fdai.core.operational_learning.cohort_retention import (
    LegacyCaseCohortRetention,
    retain_cohort_case,
)
from fdai.core.operational_learning.legacy_suffix_retention import LegacyCaseSuffixRetention
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tests.core.operational_learning.test_patterns import (
    _cohort_key,
    _deletion_record,
    _pattern_case,
)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[4]
AUDIT_CHECKPOINT_KEY = "pantheon/saga/audit-chain/verified-head"


@pytest.fixture
async def saga_database() -> AsyncIterator[str]:
    dsn = _plain_dsn(_requires_live_db())
    connection_info = conninfo_to_dict(dsn)
    if (
        connection_info.get("host") not in {"127.0.0.1", "localhost", "::1"}
        or str(connection_info.get("port", "5432")) != "5433"
    ):
        pytest.fail("Saga integration requires the isolated loopback validation database")
    _upgrade_head()
    schema = f"saga_audit_test_{uuid.uuid4().hex}"
    async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as connection:
        await connection.execute("SET statement_timeout = '15s'")
        await connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        for table in ("audit_log", "state_kv"):
            await connection.execute(
                sql.SQL("CREATE TABLE {}.{} (LIKE public.{} INCLUDING ALL)").format(
                    sql.Identifier(schema), sql.Identifier(table), sql.Identifier(table)
                )
            )
    try:
        yield make_conninfo(dsn, options=f"-c search_path={schema}")
    finally:
        async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as connection:
            await connection.execute("SET statement_timeout = '15s'")
            await connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


async def test_identical_state_write_reuses_large_value_and_refreshes_timestamp(
    saga_database: str,
) -> None:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    value = {"payload": "unchanged-state-" * 8192}
    try:
        async with await psycopg.AsyncConnection.connect(
            saga_database, autocommit=True, connect_timeout=5
        ) as connection:
            await connection.execute("SET statement_timeout = '15s'")
            await connection.execute("ALTER TABLE state_kv ALTER COLUMN value SET STORAGE EXTERNAL")
            await store.write_state("test:unchanged-large-state", value)
            await connection.execute(
                "UPDATE state_kv SET updated_at='2000-01-01T00:00:00Z' "
                "WHERE key='test:unchanged-large-state'"
            )
            size_query = (
                "SELECT pg_relation_size(reltoastrelid) FROM pg_class "
                "WHERE oid='state_kv'::regclass"
            )
            before = await (await connection.execute(size_query)).fetchone()
            assert before is not None
            for _iteration in range(5):
                await store.write_state("test:unchanged-large-state", dict(value))
            after = await (await connection.execute(size_query)).fetchone()
            assert after is not None
            assert after[0] <= before[0] + 8192
            timestamp_row = await (
                await connection.execute(
                    "SELECT updated_at > '2000-01-01T00:00:00Z'::timestamptz "
                    "FROM state_kv WHERE key='test:unchanged-large-state'"
                )
            ).fetchone()
            assert timestamp_row == (True,)
            assert await store.read_state("test:unchanged-large-state") == value
            changed = {"payload": "changed"}
            await store.write_state("test:unchanged-large-state", changed)
            assert await store.read_state("test:unchanged-large-state") == changed
            await store.write_state("test:unchanged-large-state", {"number": 1})
            await store.write_state("test:unchanged-large-state", {"number": 1.0})
            numeric = await store.read_state("test:unchanged-large-state")
            assert numeric is not None
            assert isinstance(numeric["number"], float)
    finally:
        await store.aclose()


async def test_saga_shared_chain_and_bounded_reader_on_postgres(saga_database: str) -> None:
    first_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    second_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        assert await first_store.read_audit_entries(limit=2) == ((), False)
        for invalid_limit in (0, 513, True):
            with pytest.raises(ValueError, match="limit must be"):
                await first_store.read_audit_entries(limit=invalid_limit)
        first = StateStoreAuditChainAdapter(first_store)
        second = StateStoreAuditChainAdapter(second_store)

        async def append(chain: StateStoreAuditChainAdapter):
            return await chain.append(
                principal="Saga", topic="object.audit-entry", correlation_id="postgres", payload={}
            )

        alternating = [await append(chain) for chain in (first, second, first)]
        assert [entry.seq for entry in alternating] == [0, 1, 2]
        overlapping = await asyncio.gather(append(first), append(second))
        assert sorted(entry.seq for entry in overlapping) == [3, 4]
        restarted = StateStoreAuditChainAdapter(second_store)
        assert (await append(restarted)).seq == 5
        restarted.verify()
        rows, truncated = await first_store.read_audit_entries(limit=2)
        assert [entry["seq"] for entry in rows] == [0, 1]
        assert truncated
        rows[0]["payload"]["changed"] = True
        assert (await second_store.read_audit_entries(limit=1))[0][0]["payload"] == {}
        evidence, truncated = await first_store.list_incident_evidence(
            correlation_id="postgres", limit=2
        )
        assert truncated
        assert [record["entry"]["seq"] for record in evidence] == [4, 5]
        assert all(record["actor"] == "Saga" for record in evidence)
        assert all(record["action_kind"] == "audit.record" for record in evidence)
        assert all(isinstance(record["recorded_at"], str) for record in evidence)
        for correlation_id, limit in (("", 1), ("postgres", 0), ("postgres", 501)):
            with pytest.raises(ValueError, match="incident evidence"):
                await first_store.list_incident_evidence(correlation_id=correlation_id, limit=limit)
        assert await first_store.verify_chain()
    finally:
        await first_store.aclose()
        await second_store.aclose()


async def test_state_pair_audit_writer_commits_atomically_without_time_window(
    saga_database: str,
) -> None:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        await store.write_state("saga:aggregate:pending", {"revision": 1, "groups": {}})
        await store.write_state("saga:audit:checkpoint", {"revision": 1, "head": "before"})
        audit_entry = {"actor": "Saga", "action_kind": "audit.aggregate"}
        assert await store.compare_and_set_state_pair_with_audit(
            "saga:aggregate:pending",
            {"revision": 2, "groups": {"a": {"count": 1}}},
            expected_revision=1,
            second_key="saga:audit:checkpoint",
            second_value={"revision": 2, "head": "after"},
            expected_second_revision=1,
            audit_entry=audit_entry,
        )
        assert await store.read_state("saga:aggregate:pending") == {
            "revision": 2,
            "groups": {"a": {"count": 1}},
        }
        assert await store.read_state("saga:audit:checkpoint") == {
            "revision": 2,
            "head": "after",
        }
        records, _ = await store.read_audit_entries(limit=10)
        assert records[-1] == audit_entry

        assert not await store.compare_and_set_state_pair_with_audit(
            "saga:aggregate:pending",
            {"revision": 3, "groups": {}},
            expected_revision=2,
            second_key="saga:audit:checkpoint",
            second_value={"revision": 3, "head": "conflict"},
            expected_second_revision=1,
            audit_entry={"actor": "Saga", "action_kind": "audit.must_not_append"},
        )
        assert await store.read_state("saga:aggregate:pending") == {
            "revision": 2,
            "groups": {"a": {"count": 1}},
        }
        assert await store.read_state("saga:audit:checkpoint") == {
            "revision": 2,
            "head": "after",
        }
        records, _ = await store.read_audit_entries(limit=10)
        assert records == (audit_entry,)
    finally:
        await store.aclose()


@pytest.mark.integration
async def test_temporal_state_pair_linearizes_before_expiry(saga_database: str) -> None:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    now = datetime.now(tz=UTC)
    try:
        await store.write_state("upgrade:source", {"revision": 1, "state": "v1"})

        assert await store.compare_and_set_state_with_audit_and_insert_before(
            "upgrade:source",
            {"revision": 2, "state": "fenced"},
            expected_revision=1,
            insert_key="upgrade:target",
            insert_value={"revision": 1, "state": "v2"},
            not_before=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=1),
            audit_entry={
                "actor": "Mimir",
                "action_kind": "rule_activation.identity-upgraded",
            },
        )
        assert await store.read_state("upgrade:source") == {
            "revision": 2,
            "state": "fenced",
        }
        assert await store.read_state("upgrade:target") == {
            "revision": 1,
            "state": "v2",
        }
        assert await store.compare_and_set_state_pair_with_audit_before(
            "upgrade:source",
            {"revision": 3, "state": "v2-next"},
            expected_revision=2,
            second_key="upgrade:binding",
            second_value={"revision": 1, "state": "binding-v1"},
            expected_second_revision=0,
            not_before=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=1),
            audit_entry={
                "actor": "Mimir",
                "action_kind": "rule_activation.revision-changed",
            },
        )
        assert await store.compare_and_set_state_pair_with_audit_before(
            "upgrade:source",
            {"revision": 4, "state": "v2-next-2"},
            expected_revision=3,
            second_key="upgrade:binding",
            second_value={"revision": 2, "state": "binding-v2"},
            expected_second_revision=1,
            not_before=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=1),
            audit_entry={
                "actor": "Mimir",
                "action_kind": "rule_activation.revision-changed",
            },
        )
        assert await store.read_state("upgrade:source") == {
            "revision": 4,
            "state": "v2-next-2",
        }
        assert await store.read_state("upgrade:binding") == {
            "revision": 2,
            "state": "binding-v2",
        }
        await store.write_state("upgrade:retention-epoch", {"revision": 1})
        assert await store.compare_and_set_state_pair_with_audit_before(
            "upgrade:source",
            {"revision": 5, "state": "v2-next-3"},
            expected_revision=4,
            second_key="upgrade:binding",
            second_value={"revision": 3, "state": "binding-v3"},
            expected_second_revision=2,
            not_before=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=1),
            insert_key="upgrade:rollback-eligibility",
            insert_value={"revision": 1, "state": "eligible"},
            guard_key="upgrade:retention-epoch",
            guard_value={"revision": 2},
            expected_guard_revision=1,
            audit_entry={
                "actor": "Mimir",
                "action_kind": "rule_activation.revision-changed",
            },
        )
        assert await store.read_state("upgrade:retention-epoch") == {"revision": 2}
        assert await store.read_state("upgrade:rollback-eligibility") == {
            "revision": 1,
            "state": "eligible",
        }

        await store.write_state("upgrade:expired-source", {"revision": 1, "state": "v1"})
        assert not await store.compare_and_set_state_with_audit_and_insert_before(
            "upgrade:expired-source",
            {"revision": 2, "state": "fenced"},
            expected_revision=1,
            insert_key="upgrade:expired-target",
            insert_value={"revision": 1, "state": "v2"},
            not_before=now - timedelta(minutes=2),
            expires_at=now - timedelta(minutes=1),
            audit_entry={
                "actor": "Mimir",
                "action_kind": "rule_activation.identity-upgraded",
            },
        )
        assert await store.read_state("upgrade:expired-source") == {
            "revision": 1,
            "state": "v1",
        }
        assert await store.read_state("upgrade:expired-target") is None
        assert await store.verify_chain()
    finally:
        await store.aclose()


async def test_saga_postgres_chain_starts_after_unrelated_audit_rows_exceed_the_bound(
    saga_database: str,
) -> None:
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        for index in range(600):
            await store.append_audit_entry({"action_kind": "unrelated.record", "index": index})
        # A plain bounded read is truncated by other writers' rows, the chain reader is not.
        assert (await store.read_audit_entries(limit=512))[1] is True
        assert await store.read_audit_chain_entries(limit=512) == ((), False)
        entry = await StateStoreAuditChainAdapter(store).append(
            principal="Saga", topic="object.audit-entry", correlation_id="first", payload={}
        )
        assert entry.seq == 0 and entry.prev_hash == "0" * 64
        assert await store.read_state(AUDIT_CHECKPOINT_KEY) is not None
        chain_rows, truncated = await store.read_audit_chain_entries(limit=512)
        assert [row["seq"] for row in chain_rows] == [0] and truncated is False
        assert await store.verify_chain()
    finally:
        await store.aclose()


@pytest.mark.parametrize("checkpoint", [False, True])
async def test_saga_postgres_migrates_complete_legacy_without_rewriting_audit(
    saga_database: str, checkpoint: bool
) -> None:
    seed = InMemoryStateStore()
    entry = await StateStoreAuditChainAdapter(seed).append(
        principal="Saga", topic="object.audit-entry", correlation_id="legacy", payload={}
    )
    record = dict(next(iter(seed.audit_entries))["entry"])
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        await store.append_audit_entry({"action_kind": "unrelated.record"})
        await store.append_audit_entry(record)
        if checkpoint:
            await store.write_state(
                AUDIT_CHECKPOINT_KEY,
                {"schema_version": "1.0.0", "length": 1, "head_hash": entry.entry_hash},
            )
        rows_before, truncated = await store.read_audit_entries(limit=512)
        assert not truncated
        chain = StateStoreAuditChainAdapter(store)
        resumed = await chain.append(
            principal="Saga", topic="object.audit-entry", correlation_id="resumed", payload={}
        )
        assert resumed.seq == 1
        assert resumed.prev_hash == entry.entry_hash
        assert (await store.read_audit_entries(limit=512))[0][:2] == rows_before
        chain.verify(full=True)
        assert await store.verify_chain()
    finally:
        await store.aclose()


@pytest.mark.parametrize("canceled", [False, True])
async def test_saga_postgres_head_and_audit_rollback_together(
    saga_database: str, canceled: bool
) -> None:
    class _FailingStore(PostgresStateStore):
        async def _append_audit_in_transaction(
            self, conn: psycopg.AsyncConnection[Any], payload: Mapping[str, Any]
        ) -> None:
            await super()._append_audit_in_transaction(conn, payload)
            if canceled:
                raise asyncio.CancelledError
            raise RuntimeError("injected PostgreSQL audit transaction failure")

    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    failing_store = _FailingStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        initial = StateStoreAuditChainAdapter(store)
        await initial.append(
            principal="Saga", topic="object.audit-entry", correlation_id="ok", payload={}
        )
        head_before = await store.read_state(AUDIT_CHECKPOINT_KEY)
        rows_before = await store.read_audit_entries(limit=512)
        failing = StateStoreAuditChainAdapter(failing_store)
        with pytest.raises(asyncio.CancelledError if canceled else RuntimeError):
            await failing.append(
                principal="Saga", topic="object.audit-entry", correlation_id="failed", payload={}
            )
        assert await store.read_state(AUDIT_CHECKPOINT_KEY) == head_before
        assert await store.read_audit_entries(limit=512) == rows_before
        assert failing.entries == []
        assert await store.verify_chain()
    finally:
        await failing_store.aclose()
        await store.aclose()


@pytest.mark.asyncio
async def test_assurance_twin_source_and_target_transition_atomically() -> None:
    url = _requires_live_db()
    _upgrade_head()
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=_plain_dsn(url)))
    identity = uuid.uuid4().hex
    source_key = f"assurance-twin-source-{identity}"
    target_key = f"assurance-twin-target-{identity}"
    source = {
        "revision": 1,
        "fresh_until": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        "writer_status": "pending",
    }
    target = {"revision": 1, "source_confirmed": False}
    assert await store.write_state_with_audit_if_absent(
        source_key, source, {"action_kind": "assurance_twin.source_test"}
    )
    assert await store.write_state_with_audit_if_absent(
        target_key, target, {"action_kind": "assurance_twin.target_test"}
    )
    confirmed_source = {**source, "revision": 2, "writer_status": "confirmed"}
    confirmed_target = {**target, "revision": 2, "source_confirmed": True}
    assert await store.confirm_assurance_twin_source(
        source_key=source_key,
        source_value=confirmed_source,
        expected_source_revision=1,
        target_key=target_key,
        target_value=confirmed_target,
        expected_target_revision=1,
        require_fresh=True,
        audit_entry={"action_kind": "assurance_twin.confirmed_test"},
    )
    assert await store.read_state(source_key) == confirmed_source
    assert await store.read_state(target_key) == confirmed_target
    conflicted_source = {**confirmed_source, "revision": 3, "conflict": True}
    conflicted_target = {**confirmed_target, "revision": 3, "conflict": True}
    assert await store.conflict_assurance_twin_source(
        source_key=source_key,
        source_value=conflicted_source,
        expected_source_revision=2,
        target_key=target_key,
        target_value=conflicted_target,
        expected_target_revision=2,
        audit_entry={"action_kind": "assurance_twin.conflict_test"},
    )
    assert await store.read_state(source_key) == conflicted_source
    assert await store.read_state(target_key) == conflicted_target


@pytest.mark.asyncio
async def test_keyset_state_keys_stay_stable_after_audited_cas() -> None:
    url = _requires_live_db()
    _upgrade_head()
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=_plain_dsn(url)))
    prefix = f"case-history-keyset-{uuid.uuid4().hex}:"
    keys = (f"{prefix}a", f"{prefix}b", f"{prefix}c")
    for key in keys:
        assert await store.write_state_with_audit_if_absent(
            key, {"revision": 1}, {"action_kind": "case_history.keyset_test"}
        )
    assert await store.read_state_keys(prefix, limit=2) == keys[:2]
    assert await store.compare_and_set_state_with_audit(
        keys[0],
        {"revision": 2},
        expected_revision=1,
        audit_entry={"action_kind": "case_history.keyset_test"},
    )
    assert await store.read_state_keys(prefix, after=keys[1], limit=2) == keys[2:]
    assert await store.read_state_keys(prefix, after=keys[2]) == ()


@pytest.mark.asyncio
async def test_legacy_suffix_cleanup_on_real_postgres_preserves_peer_and_audit() -> None:
    url = _requires_live_db()
    _upgrade_head()
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=_plain_dsn(url)))
    deleted = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    peer = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)
    assert deleted is not None and peer is not None
    key = _cohort_key(deleted)
    for case in (deleted, peer):
        await retain_cohort_case(
            store,
            key=key,
            case=case,
            access_scope_digest="a" * 64,
            purpose="operational-learning",
            recorded_at=case.event_time_cutoff,
        )
    cohort = await store.read_state(key)
    assert cohort is not None
    digest = hashlib.sha256(
        json.dumps(cohort["cases"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    snapshot_key = f"{key}:snapshot:{digest}"
    assert await store.write_state_with_audit_if_absent(
        snapshot_key, cohort, {"action_kind": "case_history.snapshot_test"}
    )
    await LegacyCaseCohortRetention(store=store).purge(_deletion_record(deleted))
    for _ in range(12):
        try:
            await LegacyCaseSuffixRetention(store=store).purge(_deletion_record(deleted))
            break
        except RuntimeError as exc:
            assert "pending" in str(exc)
    else:
        pytest.fail("PostgreSQL suffix cleanup did not finish its audited keyset scan")
    observed = await store.read_state(snapshot_key)
    assert observed is not None and observed["retired"] is True
    assert [row["case"]["case_id"] for row in observed["cases"]] == [peer.case_id]
    assert await store.write_state_if_absent(snapshot_key, cohort) is False
    assert await store.verify_chain() is True


@pytest.mark.parametrize("field", ["status", "delivery.status"])
async def test_filtered_retention_preserves_unpublished_audit_on_postgres(field: str) -> None:
    url = _requires_live_db()
    _upgrade_head()
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=_plain_dsn(url)))
    prefix = f"retention_{uuid.uuid4().hex}%:"
    keys = tuple(f"{prefix}{index}" for index in range(6))
    try:
        for index, status in enumerate(
            ("pending", "published", "publishing", "published", "published")
        ):
            await store.write_state(
                keys[index], {"index": index, "status": status, "delivery": {"status": status}}
            )
        await store.write_state(keys[5], {"index": 5})
        assert (
            await store.delete_states_beyond(
                prefix, retain_newest=1, field=field, value="published"
            )
            == 2
        )
        assert {row["index"] for row in await store.read_states(prefix, limit=10)} == {0, 2, 4, 5}
        assert await store.delete_states_beyond(prefix, retain_newest=1) == 3
        assert [row["index"] for row in await store.read_states(prefix, limit=10)] == [5]
    finally:
        for key in keys:
            await store.delete_state(key)
        await store.aclose()


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _plain_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.mark.asyncio
async def test_append_audit_entry_writes_hash_chained_row() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    event_id = str(uuid.uuid4())
    await store.append_audit_entry(
        {
            "event_id": event_id,
            "actor": "integration-test",
            "action_kind": "smoke",
            "mode": "shadow",
            "reason": "hash-chain-check",
        }
    )
    # A second entry inherits the first's hash - verify_chain confirms.
    await store.append_audit_entry(
        {
            "event_id": str(uuid.uuid4()),
            "actor": "integration-test",
            "action_kind": "smoke",
            "mode": "shadow",
            "reason": "second",
        }
    )
    assert await store.verify_chain() is True


@pytest.mark.asyncio
async def test_incident_evidence_read_is_correlation_scoped_and_bounded() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    correlation_id = f"incident-integration-{uuid.uuid4().hex}"
    for index in range(3):
        await store.append_audit_entry(
            {
                "event_id": str(uuid.uuid4()),
                "correlation_id": correlation_id if index < 2 else "other-incident",
                "actor": "integration-test",
                "action_kind": "incident.evidence",
                "mode": "shadow",
                "recorded_at": datetime(2026, 8, 14, 9, index, tzinfo=UTC).isoformat(),
            }
        )

    rows, truncated = await store.list_incident_evidence(
        correlation_id=correlation_id,
        limit=1,
    )

    assert truncated is True
    assert len(rows) == 1
    assert rows[0]["correlation_id"] == correlation_id


@pytest.mark.asyncio
async def test_incident_evidence_keeps_the_newest_records_in_ascending_order() -> None:
    """The answer calls the bounded set the latest N, and reads it oldest-first."""
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    correlation_id = f"incident-order-{uuid.uuid4().hex}"
    for index in range(4):
        await store.append_audit_entry(
            {
                "event_id": str(uuid.uuid4()),
                "correlation_id": correlation_id,
                "actor": f"actor-{index}",
                "action_kind": "incident.evidence",
                "mode": "shadow",
                "recorded_at": datetime(2026, 8, 14, 9, index, tzinfo=UTC).isoformat(),
            }
        )

    rows, truncated = await store.list_incident_evidence(
        correlation_id=correlation_id,
        limit=2,
    )

    assert truncated is True
    assert [row["actor"] for row in rows] == ["actor-2", "actor-3"]
    assert [row["seq"] for row in rows] == sorted(row["seq"] for row in rows)


@pytest.mark.asyncio
async def test_state_kv_round_trip() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    key = f"integration-test-{uuid.uuid4()}"
    await store.write_state(key, {"a": 1, "nested": {"b": 2}})
    got = await store.read_state(key)
    assert got == {"a": 1, "nested": {"b": 2}}
    # Idempotent overwrite - no history row explosion.
    await store.write_state(key, {"a": 2})
    assert await store.read_state(key) == {"a": 2}
    assert await store.read_state("unknown-key") is None


@pytest.mark.asyncio
async def test_state_kv_atomic_create_and_prefix_read() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    prefix = f"integration-prefix-{uuid.uuid4()}:"

    assert await store.write_state_if_absent(f"{prefix}one", {"value": 1}) is True
    assert await store.write_state_if_absent(f"{prefix}one", {"value": 99}) is False
    assert await store.write_state_if_absent(f"{prefix}two", {"value": 2}) is True

    rows = await store.read_states(prefix, limit=10)
    assert {row["value"] for row in rows} == {1, 2}
    assert await store.read_state(f"{prefix}one") == {"value": 1}


@pytest.mark.asyncio
async def test_state_kv_audited_cas_accepts_existing_revision_zero() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    key = f"integration-cas-{uuid.uuid4()}"
    initial_audit = {
        "event_id": str(uuid.uuid4()),
        "actor": "integration-test",
        "action_kind": "state.created",
        "mode": "shadow",
    }
    assert await store.write_state_with_audit_if_absent(
        key,
        {"status": "pending", "revision": 0},
        initial_audit,
    )

    transition_audit = {
        "event_id": str(uuid.uuid4()),
        "actor": "integration-test",
        "action_kind": "state.transitioned",
        "mode": "shadow",
    }
    assert await store.compare_and_set_state_with_audit(
        key,
        {"status": "approved", "revision": 1},
        expected_revision=0,
        audit_entry=transition_audit,
    )
    assert await store.read_state(key) == {"status": "approved", "revision": 1}
    assert not await store.compare_and_set_state_with_audit(
        key,
        {"status": "rejected", "revision": 2},
        expected_revision=0,
        audit_entry={**transition_audit, "event_id": str(uuid.uuid4())},
    )
    assert await store.verify_chain()


@pytest.mark.asyncio
async def test_append_audit_rejects_invalid_mode() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    with pytest.raises(ValueError, match="mode"):
        await store.append_audit_entry(
            {
                "event_id": str(uuid.uuid4()),
                "actor": "integration-test",
                "action_kind": "smoke",
                "mode": "invalid",
            }
        )


def test_config_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresStateStore(config=PostgresStateStoreConfig(dsn=""))


def test_config_rejects_bad_timeout() -> None:
    with pytest.raises(ValueError, match="timeout"):
        PostgresStateStore(
            config=PostgresStateStoreConfig(dsn="postgresql://x", statement_timeout_ms=0)
        )
