"""Standalone scheduler Job entrypoint tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.scheduler.models import ScheduledTask
from fdai.core.scheduler.run_ledger import InMemoryScheduleRunLedger
from fdai.core.scheduler.service import SchedulerRunReport
from fdai.core.scheduler.store import InMemoryScheduleStore
from fdai.delivery import scheduler_tick_cli
from fdai.delivery.scheduler_tick_cli import (
    SchedulerJobConfigurationError,
    SchedulerJobSettings,
    execute_scheduler_tick,
    report_summary,
)
from fdai.shared.providers.event_bus import PublishReceipt

_NOW = datetime(2026, 8, 29, 2, 0, tzinfo=UTC)


class _Bus:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(self, topic: str, key: str, payload: dict[str, Any]) -> PublishReceipt:
        if self.fail:
            raise RuntimeError("provider detail that must not be printed")
        self.published.append((topic, key, payload))
        return PublishReceipt(topic=topic, partition=0, offset=0)

    def subscribe(self, topic: str, group_id: str):  # pragma: no cover - unused
        raise NotImplementedError

    async def dead_letter(self, topic, key, payload, reason) -> None:  # pragma: no cover
        raise NotImplementedError


def _settings() -> SchedulerJobSettings:
    return SchedulerJobSettings(
        dsn="postgresql://example.invalid/fdai",
        bootstrap_servers="event-bus.example.invalid:9093",
        topic="fdai.events",
    )


def _task() -> ScheduledTask:
    return ScheduledTask(
        task_id="schedule-one",
        name="Example schedule",
        interval_seconds=300,
        event_type="example.tick",
        created_by="00000000-0000-0000-0000-000000000000",
    )


def test_settings_require_secret_and_event_bus_bindings() -> None:
    for environ, expected in (
        ({}, "FDAI_SCHEDULE_STORE_DSN"),
        ({"FDAI_SCHEDULE_STORE_DSN": "postgresql://example"}, "KAFKA_BOOTSTRAP_SERVERS"),
        (
            {
                "FDAI_SCHEDULE_STORE_DSN": "postgresql://example",
                "KAFKA_BOOTSTRAP_SERVERS": "event-bus.example.invalid:9093",
            },
            "FDAI_SCHEDULER_TOPIC or KAFKA_TOPIC_EVENTS",
        ),
    ):
        with pytest.raises(SchedulerJobConfigurationError, match=expected):
            SchedulerJobSettings.from_environ(environ)


async def test_tick_uses_durable_claim_to_suppress_duplicate_delivery() -> None:
    class _NonAdvancingStore(InMemoryScheduleStore):
        async def mark_run(self, task_id: str, at: datetime) -> ScheduledTask:
            return await self.get(task_id)

    store = _NonAdvancingStore()
    await store.create(_task())
    ledger = InMemoryScheduleRunLedger()
    bus = _Bus()

    first = await execute_scheduler_tick(
        settings=_settings(),
        store=store,
        run_ledger=ledger,
        event_bus=bus,  # type: ignore[arg-type]
        now=_NOW,
    )
    duplicate = await execute_scheduler_tick(
        settings=_settings(),
        store=store,
        run_ledger=ledger,
        event_bus=bus,  # type: ignore[arg-type]
        now=_NOW,
    )

    assert first.fired == 1
    assert duplicate.fired == 0
    assert duplicate.duplicates_suppressed == 1
    assert len(bus.published) == 1


async def test_publish_failure_is_retryable_and_summary_is_sanitized() -> None:
    store = InMemoryScheduleStore()
    await store.create(_task())

    report = await execute_scheduler_tick(
        settings=_settings(),
        store=store,
        run_ledger=InMemoryScheduleRunLedger(),
        event_bus=_Bus(fail=True),  # type: ignore[arg-type]
        now=_NOW,
    )
    summary = report_summary(report)

    assert report.fired == 0
    assert summary == {
        "status": "publish_failed",
        "fired": 0,
        "duplicates_suppressed": 0,
        "publish_error_count": 1,
        "publish_error_kinds": ["RuntimeError"],
        "execution_authority": False,
    }
    assert "schedule-one" not in json.dumps(summary)
    assert "provider detail" not in json.dumps(summary)


def test_main_returns_sanitized_exit_codes(monkeypatch, capsys) -> None:
    async def completed():
        return SchedulerRunReport(fired=2, duplicates_suppressed=1)

    monkeypatch.setattr(scheduler_tick_cli, "run_once", completed)
    assert scheduler_tick_cli.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "completed",
        "fired": 2,
        "duplicates_suppressed": 1,
        "publish_error_count": 0,
        "publish_error_kinds": [],
        "execution_authority": False,
    }

    assert scheduler_tick_cli.main(["unexpected"]) == 2
    assert json.loads(capsys.readouterr().out) == {"status": "invalid_arguments"}


def test_main_reports_missing_configuration_without_values(monkeypatch, capsys) -> None:
    monkeypatch.setattr(scheduler_tick_cli.os, "environ", {})

    assert scheduler_tick_cli.main([]) == 2
    assert json.loads(capsys.readouterr().out) == {"status": "configuration_required"}
