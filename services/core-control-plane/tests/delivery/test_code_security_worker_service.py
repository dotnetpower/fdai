"""Tests for code-security revision state and supervised worker cycles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.code_security_revision_state import (
    read_successful_revision,
    record_successful_revision,
    revision_state_key,
)
from fdai.delivery.code_security_worker_service import (
    WORKER_STATUS_KEY,
    CodeSecurityWorkerServiceConfig,
    run_worker_service,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def test_successful_revision_round_trips_and_malformed_state_fails() -> None:
    store = InMemoryStateStore()
    assert await read_successful_revision(store, "example-app") is None
    recorded_at = datetime(2026, 10, 10, 1, 2, 3, tzinfo=UTC)
    await record_successful_revision(store, "example-app", "a" * 40, recorded_at=recorded_at)
    assert await read_successful_revision(store, "example-app") == "a" * 40
    assert await store.read_state(revision_state_key("example-app")) == {
        "kind": "code-security-revision",
        "schema_version": "1.0.0",
        "repository_alias": "example-app",
        "revision": "a" * 40,
        "recorded_at": "2026-10-10T01:02:03+00:00",
    }
    await store.write_state(revision_state_key("example-app"), {"revision": "bad"})
    with pytest.raises(ValueError, match="revision state is malformed"):
        await read_successful_revision(store, "example-app")


@pytest.mark.parametrize(
    "config",
    [
        CodeSecurityWorkerServiceConfig(request_interval_seconds=1),
        CodeSecurityWorkerServiceConfig(schedule_interval_seconds=60),
    ],
)
def test_worker_service_accepts_bounded_intervals(config: CodeSecurityWorkerServiceConfig) -> None:
    assert config.request_interval_seconds >= 1
    assert config.schedule_interval_seconds >= 60


def test_worker_service_rejects_unbounded_intervals() -> None:
    with pytest.raises(ValueError, match="request_interval_seconds"):
        CodeSecurityWorkerServiceConfig(request_interval_seconds=0)
    with pytest.raises(ValueError, match="schedule_interval_seconds"):
        CodeSecurityWorkerServiceConfig(schedule_interval_seconds=59)


async def test_worker_service_runs_requests_each_cycle_and_schedule_when_due() -> None:
    store = InMemoryStateStore()
    current = datetime(2026, 10, 10, tzinfo=UTC)
    request_calls = 0
    schedule_calls = 0

    def clock() -> datetime:
        return current

    async def sleep(seconds: float) -> None:
        nonlocal current
        current += timedelta(seconds=seconds)

    async def request_batch() -> list[dict[str, object]]:
        nonlocal request_calls
        request_calls += 1
        return [{"status": "published"}] if request_calls == 1 else []

    async def schedule_batch() -> list[dict[str, object]]:
        nonlocal schedule_calls
        schedule_calls += 1
        return [
            {"status": "published"},
            {"status": "unchanged"},
            {"status": "failed"},
        ]

    await run_worker_service(
        store,
        request_batch=request_batch,
        schedule_batch=schedule_batch,
        config=CodeSecurityWorkerServiceConfig(
            request_interval_seconds=5,
            schedule_interval_seconds=300,
        ),
        clock=clock,
        sleep=sleep,
        max_cycles=2,
    )
    assert (request_calls, schedule_calls) == (2, 1)
    status = await store.read_state(WORKER_STATUS_KEY)
    assert status is not None
    assert status["state"] == "ready"
    assert status["phase"] == "idle"
    assert status["request_processed"] == 0
    assert status["schedule_checked"] == 3
    assert status["schedule_scanned"] == 1
    assert status["schedule_unchanged"] == 1
    assert status["schedule_failed"] == 1
    assert status["next_schedule_at"] == "2026-10-10T00:05:00+00:00"
