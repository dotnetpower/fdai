"""Focused checks for durable background-task projection publication."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.delivery.persistence.postgres_background_task_projection_feed import (
    PostgresBackgroundTaskProjectionFeed,
)
from fdai.shared.providers.event_bus import PublishReceipt
from fdai_core_service.background_task_projection import (
    BackgroundTaskProjectionPublisher,
    ClaimedBackgroundTaskProjection,
)
from fdai_service_contracts.background_task_projection import (
    BACKGROUND_TASK_PROJECTION_TOPIC,
    BackgroundTaskProjectionBudget,
    BackgroundTaskProjectionEnvelope,
    BackgroundTaskProjectionUsage,
    build_background_task_progress,
    build_background_task_snapshot,
)

NOW = datetime(2026, 8, 29, 3, 0, tzinfo=UTC)


class _Outbox:
    def __init__(self, claims: tuple[ClaimedBackgroundTaskProjection, ...] = ()) -> None:
        self._claims = claims
        self.verified = 0
        self.claim_calls: list[dict[str, object]] = []
        self.acknowledged: list[tuple[str, str, datetime]] = []
        self.released: list[tuple[str, str, datetime, str]] = []

    async def verify_schema(self) -> None:
        self.verified += 1

    async def claim_batch(
        self,
        *,
        worker_id: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        limit: int,
    ) -> tuple[ClaimedBackgroundTaskProjection, ...]:
        self.claim_calls.append(
            {
                "worker_id": worker_id,
                "lease_token": lease_token,
                "now": now,
                "lease_seconds": lease_seconds,
                "limit": limit,
            }
        )
        claims, self._claims = self._claims[:limit], ()
        return claims

    async def acknowledge(
        self,
        projection_id: str,
        *,
        lease_token: str,
        published_at: datetime,
    ) -> bool:
        self.acknowledged.append((projection_id, lease_token, published_at))
        return True

    async def release(
        self,
        projection_id: str,
        *,
        lease_token: str,
        released_at: datetime,
        error_code: str,
    ) -> bool:
        self.released.append((projection_id, lease_token, released_at, error_code))
        return True


class _Bus:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.fail_on_call = fail_on_call
        self.records: list[tuple[str, str, Mapping[str, object]]] = []

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> PublishReceipt:
        call_number = len(self.records) + 1
        if self.fail_on_call == call_number:
            raise RuntimeError("broker unavailable")
        self.records.append((topic, key, payload))
        return PublishReceipt(topic=topic, partition=0, offset=len(self.records) - 1)


def _snapshot(**updates: object) -> BackgroundTaskProjectionEnvelope:
    values: dict[str, object] = {
        "task_id": "background-task-one",
        "owner_principal_id": "principal-one",
        "attempt_id": "background-task-one:1",
        "task_kind": "read_only_investigation",
        "status": "queued",
        "revision": 1,
        "created_at": NOW,
        "updated_at": NOW,
        "retention_until": NOW + timedelta(days=30),
        "recorded_at": NOW,
        "budget": BackgroundTaskProjectionBudget(
            max_wall_seconds=300,
            max_tokens=4096,
            max_cost_microusd=500000,
            max_tool_calls=5,
            max_progress_events=32,
        ),
        "usage": BackgroundTaskProjectionUsage(),
        "request_summary": "Inspect the projected resource state.",
        "accountable_agent": "Heimdall",
    }
    values.update(updates)
    return build_background_task_snapshot(**values)  # type: ignore[arg-type]


def _progress(**updates: object) -> BackgroundTaskProjectionEnvelope:
    values: dict[str, object] = {
        "task_id": "background-task-one",
        "owner_principal_id": "principal-one",
        "attempt_id": "background-task-one:1",
        "progress_sequence": 0,
        "progress_order": 1,
        "progress_kind": "investigation.progress",
        "progress_message": "Collected the authoritative state.",
        "progress_at": NOW + timedelta(seconds=1),
        "retention_until": NOW + timedelta(days=30),
        "usage": BackgroundTaskProjectionUsage(tokens=2),
    }
    values.update(updates)
    return build_background_task_progress(**values)  # type: ignore[arg-type]


def _claim(
    record: BackgroundTaskProjectionEnvelope,
    *,
    outbox_sequence: int,
) -> ClaimedBackgroundTaskProjection:
    return ClaimedBackgroundTaskProjection(
        outbox_sequence=outbox_sequence,
        projection_id=record.projection_id,
        task_id=record.task_id,
        attempt_id=record.attempt_id,
        record=record,
    )


async def test_publisher_claims_and_acknowledges_a_bounded_batch() -> None:
    progress = _progress()
    snapshot = _snapshot(
        status="succeeded",
        revision=4,
        updated_at=NOW + timedelta(seconds=2),
        recorded_at=NOW + timedelta(seconds=2),
        usage=BackgroundTaskProjectionUsage(tokens=4),
        result_summary="Completed.",
        terminal_reason="completed",
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=2),
        completion_state="pending",
        completion_attempt_count=0,
        progress_watermark=1,
    )
    outbox = _Outbox((_claim(snapshot, outbox_sequence=2), _claim(progress, outbox_sequence=1)))
    bus = _Bus()
    publisher = BackgroundTaskProjectionPublisher(
        outbox=outbox,
        worker_id="core-one-background-task-projection",
        clock=lambda: NOW,
        lease_token_factory=lambda: "lease-one",
    )

    published = await publisher.run_once(bus=bus)  # type: ignore[arg-type]

    assert published is True
    assert outbox.claim_calls == [
        {
            "worker_id": "core-one-background-task-projection",
            "lease_token": "lease-one",
            "now": NOW,
            "lease_seconds": 120,
            "limit": 100,
        }
    ]
    assert [topic for topic, _, _ in bus.records] == [
        BACKGROUND_TASK_PROJECTION_TOPIC,
        BACKGROUND_TASK_PROJECTION_TOPIC,
    ]
    assert [
        BackgroundTaskProjectionEnvelope.model_validate(payload).record_kind
        for _, _, payload in bus.records
    ] == ["progress", "snapshot"]
    assert [item[0] for item in outbox.acknowledged] == [
        progress.projection_id,
        snapshot.projection_id,
    ]
    assert outbox.released == []


async def test_publisher_releases_failed_and_unprocessed_claims() -> None:
    first = _progress()
    second = _progress(progress_sequence=1, progress_order=2)
    third = _snapshot(
        status="running",
        revision=3,
        updated_at=NOW + timedelta(seconds=2),
        recorded_at=NOW + timedelta(seconds=2),
    )
    outbox = _Outbox(
        (
            _claim(first, outbox_sequence=1),
            _claim(second, outbox_sequence=2),
            _claim(third, outbox_sequence=3),
        )
    )
    bus = _Bus(fail_on_call=2)
    publisher = BackgroundTaskProjectionPublisher(
        outbox=outbox,
        clock=lambda: NOW,
        lease_token_factory=lambda: "lease-two",
    )

    published = await publisher.run_once(bus=bus)  # type: ignore[arg-type]

    assert published is True
    assert [item[0] for item in outbox.acknowledged] == [first.projection_id]
    assert outbox.released == [
        (second.projection_id, "lease-two", NOW, "publish_failed"),
        (third.projection_id, "lease-two", NOW, "publish_failed"),
    ]


async def test_publisher_run_verifies_schema_before_waiting() -> None:
    outbox = _Outbox()
    bus = _Bus()
    publisher = BackgroundTaskProjectionPublisher(
        outbox=outbox,
        idle_seconds=0.01,
    )
    stop = asyncio.Event()

    task = asyncio.create_task(publisher.run(bus=bus, stop=stop))  # type: ignore[arg-type]
    for _ in range(100):
        if outbox.verified:
            break
        await asyncio.sleep(0.001)
    stop.set()
    await task

    assert outbox.verified == 1


async def test_postgres_outbox_schema_probe_queries_transport_tables(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        calls.append((statement, parameters))
        return []

    outbox = PostgresBackgroundTaskProjectionFeed(fetch_all=fetch_all)
    await outbox.verify_schema()

    assert len(calls) == 3
    assert "FROM background_task_projection_outbox LIMIT 0" in calls[0][0]
    assert "progress_watermark FROM background_task_completion" in calls[1][0]
    assert "append_order FROM background_task_progress" in calls[2][0]
