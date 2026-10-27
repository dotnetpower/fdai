"""Loopback PostgreSQL checks for immutable dialogue-state snapshot retention.

Run through ``scripts/automation/with-local-test-database.py``; the tests skip without
``FDAI_DATABASE_URL`` and each owns a new throwaway database.
"""

from __future__ import annotations

import asyncio
import os
import runpy
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from fdai_operator_service.postgres_dialogue_snapshot import (
    DialogueSnapshotStoreError,
    PostgresDialogueSnapshotConfig,
    PostgresDialogueSnapshotStore,
    dialogue_snapshot_id,
)
from fdai_service_contracts.dialogue_state import (
    DialogueRole,
    DialogueState,
    DialogueTurn,
    compact_dialogue,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

pytestmark = pytest.mark.integration

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "service-migrations/branches/operator-service/versions"
    / "20261028_operator_dialogue_state_snapshot.py"
)
NOW = datetime(2026, 10, 28, tzinfo=UTC)


def _state(count: int = 6, keep_recent: int = 2) -> DialogueState:
    return compact_dialogue(
        [
            DialogueTurn(turn_id=f"t{index}", role=DialogueRole.USER, content=f"고혈압 {index} 🚀")
            for index in range(count)
        ],
        keep_recent=keep_recent,
    )


@pytest.fixture
def snapshot_dsn() -> Iterator[str]:
    dsn = os.environ.get("FDAI_DATABASE_URL")
    if not dsn:
        pytest.skip("FDAI_DATABASE_URL is unset; use with-local-test-database.py")
    parts = conninfo_to_dict(dsn.replace("postgresql+psycopg://", "postgresql://"))
    if parts.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("dialogue snapshot tests require a loopback PostgreSQL")
    upgrade: list[str] = []
    with patch("alembic.op.execute", side_effect=upgrade.append):
        runpy.run_path(str(MIGRATION))["upgrade"]()
    name = "fdai_dialogue_" + uuid4().hex[:12]
    admin = make_conninfo(**{**parts, "dbname": "postgres"})
    database = make_conninfo(**{**parts, "dbname": name})
    with psycopg.connect(admin, autocommit=True, connect_timeout=5) as connection:
        connection.execute(
            """DO $roles$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fdai_operator') THEN
                CREATE ROLE fdai_operator NOLOGIN NOSUPERUSER NOBYPASSRLS;
            END IF;
            END; $roles$"""
        )
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        with psycopg.connect(database, autocommit=True, connect_timeout=5) as connection:
            for statement in upgrade:
                connection.execute(statement)  # type: ignore[arg-type]
        yield database
    finally:
        with psycopg.connect(admin, autocommit=True, connect_timeout=5) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


def _store(dsn: str) -> PostgresDialogueSnapshotStore:
    return PostgresDialogueSnapshotStore(PostgresDialogueSnapshotConfig(dsn=dsn))


def test_snapshot_round_trips_and_is_principal_scoped(snapshot_dsn: str) -> None:
    store = _store(snapshot_dsn)
    state = _state()

    async def run() -> tuple[bool, object, object, object]:
        written = await store.append(
            principal_id="alice", conversation_id="c1", state=state, recorded_at=NOW
        )
        return (
            written,
            await store.latest(principal_id="alice", conversation_id="c1"),
            await store.latest(principal_id="bob", conversation_id="c1"),
            await store.latest(principal_id="alice", conversation_id="other"),
        )

    written, mine, other_principal, other_conversation = asyncio.run(run())

    assert written is True
    assert mine == state
    assert other_principal is None and other_conversation is None


def test_duplicate_range_is_idempotent_and_a_longer_range_is_a_new_row(snapshot_dsn: str) -> None:
    store = _store(snapshot_dsn)
    first, slid, longer = _state(6), _state(6), _state(7)
    assert dialogue_snapshot_id(first) == dialogue_snapshot_id(slid)
    assert dialogue_snapshot_id(first) != dialogue_snapshot_id(longer)

    async def run() -> tuple[bool, bool, bool, object]:
        args = {"principal_id": "alice", "conversation_id": "c1"}
        a = await store.append(**args, state=first, recorded_at=NOW)
        b = await store.append(**args, state=slid, recorded_at=NOW + timedelta(seconds=1))
        c = await store.append(**args, state=longer, recorded_at=NOW + timedelta(seconds=2))
        return a, b, c, await store.latest(**args)

    first_written, duplicate_written, longer_written, latest = asyncio.run(run())

    assert (first_written, duplicate_written, longer_written) == (True, False, True)
    assert latest == longer


def test_nothing_is_written_when_no_turn_was_compacted(snapshot_dsn: str) -> None:
    store = _store(snapshot_dsn)

    async def run() -> bool:
        return await store.append(
            principal_id="alice",
            conversation_id="c1",
            state=_state(count=2, keep_recent=8),
            recorded_at=NOW,
        )

    assert asyncio.run(run()) is False


def test_rows_are_immutable_and_inputs_are_validated(snapshot_dsn: str) -> None:
    store = _store(snapshot_dsn)
    asyncio.run(
        store.append(principal_id="alice", conversation_id="c1", state=_state(), recorded_at=NOW)
    )
    with psycopg.connect(snapshot_dsn, autocommit=True) as connection:
        with pytest.raises(psycopg.Error, match="immutable"):
            connection.execute("UPDATE conversation_dialogue_snapshot SET tier = 'T1'")
        with pytest.raises(psycopg.Error, match="immutable"):
            connection.execute("DELETE FROM conversation_dialogue_snapshot")
    with pytest.raises(ValueError, match="principal and conversation"):
        asyncio.run(
            store.append(principal_id="", conversation_id="c1", state=_state(), recorded_at=NOW)
        )


def test_unreachable_database_raises_a_typed_error() -> None:
    store = _store("postgresql://127.0.0.1:1/none")

    with pytest.raises(DialogueSnapshotStoreError):
        asyncio.run(store.latest(principal_id="alice", conversation_id="c1"))
