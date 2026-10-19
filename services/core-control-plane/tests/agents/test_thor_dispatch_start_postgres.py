"""The dispatch observation round-trips through isolated loopback PostgreSQL."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fdai.agents._framework.provider_adapters import StateStoreActionRunStore
from fdai.agents._framework.thor_dispatch_start import (
    DISPATCH_START_PREFIX,
    dispatch_start_key,
)
from fdai.agents.thor import ActionRun, ActionRunState
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

from tests.agents.test_thor_dispatch_denial import _assert_dispatch_outcome
from tests.persistence.test_postgres_state_store import saga_database as saga_database

pytestmark = pytest.mark.integration


async def test_dispatch_start_is_durable_immutable_and_atomic(saga_database: str) -> None:
    first = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    second = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    run = ActionRun(
        correlation_id="postgres-dispatch",
        action_type="example.action",
        resource_id="resource-1",
        state=ActionRunState.EXECUTING,
        verdict="auto",
    )
    at = datetime(2026, 10, 19, tzinfo=UTC)
    try:
        await asyncio.gather(
            *(
                StateStoreActionRunStore(store=backend).record_dispatch_start(
                    run, started_at=at, resource_lock_ref=None
                )
                for backend in (first, second)
            )
        )
        observed = await second.read_state(dispatch_start_key(run.correlation_id))
        assert observed is not None
        assert observed["dispatch_started_at"] == at.isoformat()
        assert observed["effect_verified"] is False and observed["history_complete"] is False
        await StateStoreActionRunStore(store=second).record_dispatch_start(
            run, started_at=at + timedelta(seconds=1), resource_lock_ref=None
        )
        rows, total = await first.read_state_page(DISPATCH_START_PREFIX, limit=10)
        assert total == 1 and rows == (observed,)
        assert await StateStoreActionRunStore(store=first).load_active() == []
    finally:
        await first.aclose()
        await second.aclose()


@pytest.mark.parametrize(
    "failure",
    [
        "record",
        "shadow",
        "development",
        "entry_authority",
        "authority_error",
        "missing_lock",
        "executor_false",
        "executor_error",
    ],
)
async def test_dispatch_denial_and_actual_recovery_on_postgres(
    saga_database: str, failure: str
) -> None:
    backend = PostgresStateStore(config=PostgresStateStoreConfig(dsn=saga_database))
    try:
        await _assert_dispatch_outcome(failure, backend)
    finally:
        await backend.aclose()
