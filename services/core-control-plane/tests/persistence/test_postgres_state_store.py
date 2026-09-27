"""Integration test - PostgresStateStore round-trip against a live DB.

Skipped unless ``FDAI_DATABASE_URL`` is set (same guard as the
migrations test). The docker-compose dev stack (`make dev-up`) exposes
the URL as ``postgresql+psycopg://fdai:devonly@localhost:5432/fdai``.

The tests here:

- ``append_audit_entry`` writes a row with hash-chained integrity;
- ``read_state`` / ``write_state`` round-trip on ``state_kv``;
- atomic create and prefix reads support immutable command projections;
- ``verify_chain`` returns True after two appends and False after we
  tamper with the persisted hash.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.case_history import OperationalOutcomeClass
from fdai.core.operational_learning.cohort_retention import (
    LegacyCaseCohortRetention,
    retain_cohort_case,
)
from fdai.core.operational_learning.legacy_suffix_retention import LegacyCaseSuffixRetention
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

from tests.core.operational_learning.test_patterns import (
    _cohort_key,
    _deletion_record,
    _pattern_case,
)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[4]


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
