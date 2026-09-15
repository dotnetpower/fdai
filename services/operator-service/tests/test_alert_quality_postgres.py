"""Round 11: real loopback PostgreSQL claims, immutable results and settings revisions.

Opt in with FDAI_ALERT_TEST_POSTGRES_PORT and an environment-only PGPASSWORD for a
disposable test server. Every test owns a new database and uses fdai_operator's role;
the minimal state_kv DDL tests storage primitives, not full migration or Azure parity.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from fdai_operator_service.alert_quality_history import StateKvAlertQualityRequestSource
from fdai_operator_service.alert_quality_runtime import command_from_record
from fdai_operator_service.alert_quality_settings import (
    AlertQualityPreference,
    AlertQualityPreferenceConflictError,
    StateKvAlertQualityPreferenceStore,
)
from fdai_operator_service.alert_quality_store import StateKvAlertQualityStore
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo

from .test_alert_quality_bridge import NOW, RESULT_KEY, SCOPE, SUBJECT, bridge_fixture
from .test_alert_quality_history import (
    KEY as HISTORY_KEY,
)
from .test_alert_quality_history import (
    HistoryState,
    acceptance,
    terminal,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def alert_database() -> Iterator[str]:
    port = os.environ.get("FDAI_ALERT_TEST_POSTGRES_PORT")
    if not port:
        pytest.skip("explicit disposable alert PostgreSQL port is unset")
    if not port.isdecimal() or not 1 <= int(port) <= 65535 or not os.environ.get("PGPASSWORD"):
        raise ValueError("disposable loopback PostgreSQL configuration is incomplete")
    base = make_conninfo(host="127.0.0.1", port=port, user="postgres", dbname="postgres")
    database = "fdai_alert_test_" + uuid4().hex
    with psycopg.connect(base, autocommit=True, connect_timeout=5) as admin:
        role = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = 'fdai_operator'").fetchone()
        if role is None:
            admin.execute("CREATE ROLE fdai_operator NOLOGIN")
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            with psycopg.connect(base, dbname=database) as setup:
                setup.execute(
                    "CREATE TABLE state_kv (key TEXT PRIMARY KEY, value JSONB NOT NULL, "
                    "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()); "
                    "GRANT USAGE ON SCHEMA public TO fdai_operator; "
                    "GRANT SELECT, INSERT, UPDATE ON state_kv TO fdai_operator"
                )
            yield make_conninfo(base, dbname=database, options="-c role=fdai_operator")
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


def store(dsn: str) -> PostgresFamilyStore:
    return PostgresFamilyStore(PostgresFamilyStoreConfig(dsn=dsn))


async def seed_request(target: PostgresFamilyStore) -> str:
    fixture, _bridge, _ready, _held = bridge_fixture()
    key, record = next(iter(fixture.records.items()))
    await target.write_state(key, {**record, "dispatch_status": "pending", "attempt": 0})
    return key


async def test_claims_are_exclusive_and_stale_workers_cannot_close(alert_database: str) -> None:
    target = store(alert_database)
    with psycopg.connect(alert_database) as connection:
        assert connection.execute("SELECT current_user").fetchone() == ("fdai_operator",)
    for number in range(12):
        await target.write_state(
            f"operator-proposal:operations:claim-{number:02d}",
            {
                "operation": "alert_noise.assess",
                "dispatch_status": "pending",
                "accepted_at": (NOW + timedelta(seconds=number)).isoformat(),
            },
        )
    claims = await asyncio.gather(
        *(store(alert_database).claim_alert_quality_proposal() for _ in range(16))
    )
    claimed = [claim for claim in claims if claim is not None]
    assert len(claimed) == len({claim[0] for claim in claimed}) == 12
    for key, claim_id, record in claimed:
        assert record["attempt"] == 1
        assert not await target.mark_proposal_published(key=key, claim_id="wrong-claim")
        assert await target.mark_proposal_published(key=key, claim_id=claim_id)
    assert await target.claim_alert_quality_proposal() is None


async def test_expired_claim_restarts_with_same_command_and_new_fence(alert_database: str) -> None:
    original = store(alert_database)
    key = await seed_request(original)
    first = await original.claim_alert_quality_proposal()
    assert first is not None
    await original.write_state(
        key, {**first[2], "claim_expires_at": (NOW - timedelta(days=1)).isoformat()}
    )
    restarted = store(alert_database)
    second = await restarted.claim_alert_quality_proposal()
    assert second is not None and first[1] != second[1]
    assert command_from_record(first[2]) == command_from_record(second[2])
    assert second[2]["attempt"] == 2
    assert not await original.mark_proposal_published(key=key, claim_id=first[1])
    assert await restarted.mark_proposal_published(key=key, claim_id=second[1])


async def test_settings_cas_and_audit_survive_new_connections(alert_database: str) -> None:
    async def change(number: int):
        preferences = StateKvAlertQualityPreferenceStore(store(alert_database), clock=lambda: NOW)
        return await preferences.set_enabled(
            scope_ref=SCOPE,
            enabled=bool(number),
            expected_revision=0,
            requester_ref=f"principal:{number:064x}",
            before_commit=lambda: None,
        )

    results = await asyncio.gather(change(0), change(1), return_exceptions=True)
    winners = [result for result in results if isinstance(result, AlertQualityPreference)]
    assert len(winners) == 1
    assert sum(isinstance(result, AlertQualityPreferenceConflictError) for result in results) == 1
    restarted = StateKvAlertQualityPreferenceStore(store(alert_database), clock=lambda: NOW)
    assert await restarted.read(scope_ref=SCOPE) == winners[0]
    assert winners[0].execution_authority is False and winners[0].revision == 1


async def test_concurrent_terminal_results_cannot_mix_projection(alert_database: str) -> None:
    target = store(alert_database)
    await seed_request(target)
    _fixture, bridge, ready, held = bridge_fixture()
    bridge.store = target
    bridge.projections = StateKvAlertQualityStore(target, clock=lambda: NOW)
    results = await asyncio.gather(
        bridge.accept_result(ready), bridge.accept_result(held), return_exceptions=True
    )
    assert sum(isinstance(result, ValueError) for result in results) == 1
    winner = await store(alert_database).read_state(RESULT_KEY)
    assert winner in (ready, held)
    projection = await StateKvAlertQualityStore(store(alert_database), clock=lambda: NOW).read(
        principal_id=SUBJECT, scope_ref=SCOPE
    )
    assert (projection is not None) == (winner == ready)
    await bridge.accept_result(winner)
    assert await target.read_state(RESULT_KEY) == winner


async def test_request_history_sql_is_principal_scoped_and_survives_restart(alert_database):
    state = HistoryState()
    record = acceptance(state, subject=SUBJECT, scope=SCOPE)
    terminal(state, record, held=True)
    acceptance(state, subject="operator-other", scope=SCOPE)
    target = store(alert_database)
    for key, value in state.records.items():
        await target.write_state(key, value)
    reopened = StateKvAlertQualityRequestSource(
        store(alert_database), transport_key=HISTORY_KEY, clock=lambda: NOW
    )
    result = await reopened.read(principal_id=SUBJECT, scope_ref=SCOPE)
    assert len(result.requests) == 1 and result.requests[0].status == "held"
    exact = await reopened.read(principal_id=SUBJECT, scope_ref=SCOPE, request_key="example-key")
    assert exact == result
