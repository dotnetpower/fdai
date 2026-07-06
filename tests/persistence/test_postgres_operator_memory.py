"""PostgresOperatorMemoryStore - unit + integration tests.

The database-touching paths are gated on ``AIOPSPILOT_DATABASE_URL`` and
mirror the skip pattern established by
``tests/persistence/test_postgres_state_store.py``. The offline unit
tests below exercise config validation, the shared policy validator,
and the ``_row_to_entry`` coercion helper so the adapter has coverage
even without a live DB.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aiopspilot.core.operator_memory import (
    InMemoryOperatorMemoryStore,
    OperatorMemoryEntry,
    OperatorMemoryPolicyError,
)
from aiopspilot.core.operator_memory.types import (
    MemoryCategory,
    MemorySource,
    ScopeKind,
)
from aiopspilot.delivery.persistence import (
    PostgresOperatorMemoryStore,
    PostgresOperatorMemoryStoreConfig,
)
from aiopspilot.delivery.persistence.postgres_operator_memory import (
    _coerce_uuid,
    _coerce_uuid_optional,
    _row_to_entry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _valid_entry(
    *,
    body: str = "operator note - do not scale below 3 replicas",
    scope_kind: ScopeKind = ScopeKind.RESOURCE_GROUP,
    scope_ref: str = "rg-example",
    author: str = "alice@example.com",
    approved_by: str = "bob@example.com",
    ttl_seconds: int | None = None,
    entry_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> OperatorMemoryEntry:
    return OperatorMemoryEntry(
        id=entry_id or uuid.uuid4(),
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        category=MemoryCategory.PREFERENCE,
        body=body,
        source_event=MemorySource.HIL_REJECT,
        source_ref="hil.reject:evt-1",
        author=author,
        approved_by=approved_by,
        created_at=created_at or datetime.now(tz=UTC),
        ttl_seconds=ttl_seconds,
    )


# ---------------------------------------------------------------------------
# Offline unit tests - no database required.
# ---------------------------------------------------------------------------


def test_config_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresOperatorMemoryStore(config=PostgresOperatorMemoryStoreConfig(dsn=""))


def test_config_rejects_zero_statement_timeout() -> None:
    with pytest.raises(ValueError, match="statement_timeout_ms"):
        PostgresOperatorMemoryStore(
            config=PostgresOperatorMemoryStoreConfig(
                dsn="postgresql://placeholder",
                statement_timeout_ms=0,
            )
        )


@pytest.mark.asyncio
async def test_append_rejects_policy_violation_before_touching_db() -> None:
    """Policy validation runs BEFORE psycopg tries to connect; a
    placeholder DSN would otherwise raise OperationalError. Proving
    ``OperatorMemoryPolicyError`` surfaces means the DB was never
    contacted for an invalid entry."""

    store = PostgresOperatorMemoryStore(
        config=PostgresOperatorMemoryStoreConfig(dsn="postgresql://placeholder")
    )
    with pytest.raises(OperatorMemoryPolicyError) as info:
        await store.append(_valid_entry(body="   "))
    assert info.value.code == "empty_body"


@pytest.mark.asyncio
async def test_append_rejects_self_approval_before_touching_db() -> None:
    store = PostgresOperatorMemoryStore(
        config=PostgresOperatorMemoryStoreConfig(dsn="postgresql://placeholder")
    )
    with pytest.raises(OperatorMemoryPolicyError) as info:
        await store.append(_valid_entry(author="alice", approved_by="alice"))
    assert info.value.code == "self_approval"


def test_coerce_uuid_accepts_uuid_and_str() -> None:
    value = uuid.uuid4()
    assert _coerce_uuid(value) is value
    assert _coerce_uuid(str(value)) == value


def test_coerce_uuid_optional_none_short_circuits() -> None:
    assert _coerce_uuid_optional(None) is None


def test_row_to_entry_coerces_naive_timestamp_to_utc() -> None:
    """A row with a naive ``created_at`` (no tzinfo) MUST be coerced to
    UTC so equality against a Python ``datetime.now(tz=UTC)`` value
    holds. Real psycopg 3 rows carry tz-aware timestamps, but the
    coercion path exists to make round-tripping through JSON exports
    safe."""

    row_id = uuid.uuid4()
    row: dict[str, object] = {
        "id": str(row_id),
        "scope_kind": "resource-group",
        "scope_ref": "rg-example",
        "category": "preference",
        "body": "hi",
        "source_event": "hil.reject",
        "source_ref": "hil.reject:evt",
        "author": "alice",
        "approved_by": "bob",
        # naive - no tzinfo
        "created_at": datetime(2026, 7, 6, 12, 0, 0),
        "superseded_by": None,
        "ttl_seconds": None,
    }
    entry = _row_to_entry(row)
    assert entry.id == row_id
    assert entry.created_at.tzinfo is UTC
    assert entry.scope_kind is ScopeKind.RESOURCE_GROUP
    assert entry.category is MemoryCategory.PREFERENCE
    assert entry.source_event is MemorySource.HIL_REJECT
    assert entry.superseded_by is None


def test_row_to_entry_parses_iso_string_timestamps_and_uuid_string() -> None:
    """JSON export/import paths deliver ``created_at`` as a string and
    UUID columns as strings; the coercion helper MUST accept both
    representations without losing precision."""

    row_id = uuid.uuid4()
    superseded_by = uuid.uuid4()
    row: dict[str, object] = {
        "id": str(row_id),
        "scope_kind": "resource",
        "scope_ref": "rg-example/vm-01",
        "category": "forbidden-action",
        "body": "no scale-in during business hours",
        "source_event": "override.create",
        "source_ref": "override.create:v42",
        "author": "alice",
        "approved_by": "bob",
        "created_at": "2026-07-06T12:00:00+00:00",
        "superseded_by": str(superseded_by),
        "ttl_seconds": 3600,
    }
    entry = _row_to_entry(row)
    assert entry.id == row_id
    assert entry.superseded_by == superseded_by
    assert entry.ttl_seconds == 3600
    assert entry.category is MemoryCategory.FORBIDDEN_ACTION
    assert entry.source_event is MemorySource.OVERRIDE_CREATE
    assert entry.created_at == datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_parity_with_in_memory_store_on_shared_policy_codes() -> None:
    """Both stores MUST reject the same policy violations with the same
    ``code`` on ``OperatorMemoryPolicyError`` so the composer and the
    HIL pipeline are backend-agnostic.

    Validation runs before any I/O so the placeholder DSN is never
    contacted - if the DB were reached this test would OperationalError
    instead of asserting on the policy code.
    """

    pg_store = PostgresOperatorMemoryStore(
        config=PostgresOperatorMemoryStoreConfig(dsn="postgresql://placeholder")
    )
    mem_store = InMemoryOperatorMemoryStore()

    cases = [
        ("empty_body", _valid_entry(body="")),
        ("self_approval", _valid_entry(author="alice", approved_by="alice")),
        ("invalid_ttl", _valid_entry(ttl_seconds=0)),
    ]
    for expected_code, entry in cases:
        with pytest.raises(OperatorMemoryPolicyError) as pg_info:
            await pg_store.append(entry)
        assert pg_info.value.code == expected_code
        with pytest.raises(OperatorMemoryPolicyError) as mem_info:
            await mem_store.append(entry)
        assert mem_info.value.code == expected_code


# ---------------------------------------------------------------------------
# Integration tests - require a live Postgres.
# ---------------------------------------------------------------------------

pytestmark_integration = pytest.mark.integration


def _requires_live_db() -> str:
    url = os.environ.get("AIOPSPILOT_DATABASE_URL")
    if not url:
        pytest.skip("AIOPSPILOT_DATABASE_URL is unset")
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_append_and_list_active_for_scope_round_trip() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresOperatorMemoryStore(config=PostgresOperatorMemoryStoreConfig(dsn=dsn))
    # Use a fresh scope_ref so tests can run repeatedly without needing a
    # per-test truncate.
    scope_ref = f"rg-it-{uuid.uuid4()}"
    entry = _valid_entry(scope_ref=scope_ref)
    stored = await store.append(entry)
    assert stored.id == entry.id
    listed = await store.list_active_for_scope(
        scope_kind=ScopeKind.RESOURCE_GROUP, scope_ref=scope_ref
    )
    assert len(listed) == 1
    got = listed[0]
    assert got.id == entry.id
    assert got.body == entry.body
    assert got.author == entry.author
    assert got.approved_by == entry.approved_by
    assert got.category is MemoryCategory.PREFERENCE
    assert got.source_event is MemorySource.HIL_REJECT


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_id_maps_to_policy_error() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresOperatorMemoryStore(config=PostgresOperatorMemoryStoreConfig(dsn=dsn))
    scope_ref = f"rg-it-{uuid.uuid4()}"
    entry = _valid_entry(scope_ref=scope_ref)
    await store.append(entry)
    with pytest.raises(OperatorMemoryPolicyError) as info:
        await store.append(entry)
    assert info.value.code == "duplicate_id"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_supersede_hides_original_from_active_query() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresOperatorMemoryStore(config=PostgresOperatorMemoryStoreConfig(dsn=dsn))
    scope_ref = f"rg-it-{uuid.uuid4()}"
    original = _valid_entry(scope_ref=scope_ref)
    replacement = _valid_entry(scope_ref=scope_ref)
    await store.append(original)
    await store.append(replacement)
    await store.supersede(entry_id=original.id, superseded_by=replacement.id)
    listed = await store.list_active_for_scope(
        scope_kind=ScopeKind.RESOURCE_GROUP, scope_ref=scope_ref
    )
    listed_ids = {e.id for e in listed}
    assert original.id not in listed_ids
    assert replacement.id in listed_ids
    # Double supersede is rejected with ``already_superseded``.
    with pytest.raises(OperatorMemoryPolicyError) as info:
        await store.supersede(entry_id=original.id, superseded_by=replacement.id)
    assert info.value.code == "already_superseded"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expired_entries_are_filtered_from_active_query() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresOperatorMemoryStore(config=PostgresOperatorMemoryStoreConfig(dsn=dsn))
    scope_ref = f"rg-it-{uuid.uuid4()}"
    # created_at set to two hours ago + ttl 60s -> already expired.
    expired = _valid_entry(
        scope_ref=scope_ref,
        ttl_seconds=60,
        created_at=datetime.now(tz=UTC) - timedelta(hours=2),
    )
    live = _valid_entry(scope_ref=scope_ref)
    await store.append(expired)
    await store.append(live)
    listed = await store.list_active_for_scope(
        scope_kind=ScopeKind.RESOURCE_GROUP, scope_ref=scope_ref
    )
    listed_ids = {e.id for e in listed}
    assert expired.id not in listed_ids
    assert live.id in listed_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_supersede_unknown_id_raises_lookup_error() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresOperatorMemoryStore(config=PostgresOperatorMemoryStoreConfig(dsn=dsn))
    with pytest.raises(LookupError):
        await store.supersede(entry_id=uuid.uuid4(), superseded_by=uuid.uuid4())
