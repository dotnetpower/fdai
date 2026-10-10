"""Supervise bounded code-security request and revision-check batches."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.shared.providers.state_store import StateStore

WORKER_STATUS_KEY = "runtime:code-security-worker:v1"
Batch = Callable[[], Awaitable[Sequence[Mapping[str, object]]]]
Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CodeSecurityWorkerServiceConfig:
    request_interval_seconds: int = 5
    schedule_interval_seconds: int = 300

    def __post_init__(self) -> None:
        if not 1 <= self.request_interval_seconds <= 60:
            raise ValueError("request_interval_seconds MUST be in [1, 60]")
        if not 60 <= self.schedule_interval_seconds <= 86_400:
            raise ValueError("schedule_interval_seconds MUST be in [60, 86400]")


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


async def _write_status(
    store: StateStore,
    *,
    config: CodeSecurityWorkerServiceConfig,
    state: str,
    phase: str,
    now: datetime,
    next_schedule_at: datetime,
    request_processed: int,
    schedule_outcomes: Sequence[Mapping[str, object]],
) -> None:
    if state not in {"running", "ready"} or phase not in {"requests", "schedule", "idle"}:
        raise ValueError("worker status is invalid")
    await store.write_state(
        WORKER_STATUS_KEY,
        {
            "kind": "code-security-worker-status",
            "schema_version": "1.0.0",
            "state": state,
            "phase": phase,
            "recorded_at": _timestamp(now),
            "request_interval_seconds": config.request_interval_seconds,
            "schedule_interval_seconds": config.schedule_interval_seconds,
            "next_request_at": _timestamp(now + timedelta(seconds=config.request_interval_seconds)),
            "next_schedule_at": _timestamp(next_schedule_at),
            "request_processed": request_processed,
            "schedule_checked": len(schedule_outcomes),
            "schedule_scanned": sum(
                outcome.get("status") == "published" for outcome in schedule_outcomes
            ),
            "schedule_unchanged": sum(
                outcome.get("status") == "unchanged" for outcome in schedule_outcomes
            ),
            "schedule_failed": sum(
                outcome.get("status") == "failed" for outcome in schedule_outcomes
            ),
        },
    )


async def _run_with_heartbeat(
    store: StateStore,
    *,
    batch: Batch,
    config: CodeSecurityWorkerServiceConfig,
    phase: str,
    next_schedule_at: datetime,
    schedule_outcomes: Sequence[Mapping[str, object]],
    clock: Clock,
    sleep: Sleep,
) -> Sequence[Mapping[str, object]]:
    async def heartbeat() -> None:
        while True:
            await sleep(config.request_interval_seconds)
            await _write_status(
                store,
                config=config,
                state="running",
                phase=phase,
                now=clock(),
                next_schedule_at=next_schedule_at,
                request_processed=0,
                schedule_outcomes=schedule_outcomes,
            )

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        return await batch()
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


async def run_worker_service(
    store: StateStore,
    *,
    request_batch: Batch,
    schedule_batch: Batch,
    config: CodeSecurityWorkerServiceConfig | None = None,
    stop: asyncio.Event | None = None,
    clock: Clock = lambda: datetime.now(UTC),
    sleep: Sleep = asyncio.sleep,
    max_cycles: int | None = None,
) -> None:
    """Run serialized bounded batches until stopped; ``max_cycles`` exists for focused tests."""
    if max_cycles is not None and max_cycles < 1:
        raise ValueError("max_cycles MUST be positive")
    resolved_config = config or CodeSecurityWorkerServiceConfig()
    next_schedule_at = clock()
    last_schedule_outcomes: Sequence[Mapping[str, object]] = ()
    cycle = 0
    while stop is None or not stop.is_set():
        now = clock()
        await _write_status(
            store,
            config=resolved_config,
            state="running",
            phase="requests",
            now=now,
            next_schedule_at=next_schedule_at,
            request_processed=0,
            schedule_outcomes=last_schedule_outcomes,
        )
        request_outcomes = await _run_with_heartbeat(
            store,
            batch=request_batch,
            config=resolved_config,
            phase="requests",
            next_schedule_at=next_schedule_at,
            schedule_outcomes=last_schedule_outcomes,
            clock=clock,
            sleep=sleep,
        )
        now = clock()
        if now >= next_schedule_at:
            await _write_status(
                store,
                config=resolved_config,
                state="running",
                phase="schedule",
                now=now,
                next_schedule_at=next_schedule_at,
                request_processed=len(request_outcomes),
                schedule_outcomes=last_schedule_outcomes,
            )
            last_schedule_outcomes = await _run_with_heartbeat(
                store,
                batch=schedule_batch,
                config=resolved_config,
                phase="schedule",
                next_schedule_at=next_schedule_at,
                schedule_outcomes=last_schedule_outcomes,
                clock=clock,
                sleep=sleep,
            )
            now = clock()
            next_schedule_at = now + timedelta(seconds=resolved_config.schedule_interval_seconds)
        await _write_status(
            store,
            config=resolved_config,
            state="ready",
            phase="idle",
            now=now,
            next_schedule_at=next_schedule_at,
            request_processed=len(request_outcomes),
            schedule_outcomes=last_schedule_outcomes,
        )
        cycle += 1
        if max_cycles is not None and cycle >= max_cycles:
            return
        if stop is None:
            await sleep(resolved_config.request_interval_seconds)
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=resolved_config.request_interval_seconds)
        except TimeoutError:
            pass


__all__ = [
    "WORKER_STATUS_KEY",
    "CodeSecurityWorkerServiceConfig",
    "run_worker_service",
]
