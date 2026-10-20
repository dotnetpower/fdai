"""Consumed attempts leave canonical evidence without claiming scheduler completeness."""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.core.control_loop import _canary
from fdai.delivery.canary_cli import build_canary_event
from fdai.shared.providers.stage_publisher import StageName
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 10, 20, tzinfo=UTC)


def _host(store: InMemoryStateStore, emit: Any) -> SimpleNamespace:
    return SimpleNamespace(
        _event_ingest=SimpleNamespace(ingest=lambda event: event),
        _correlate_incident_id=lambda event: None,
        _emit_stage=emit,
        _audit_store=store,
    )


def _entries(store: InMemoryStateStore) -> list[Mapping[str, Any]]:
    return [row["entry"] for row in store.audit_entries]


@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_or_cancelled_consumption_has_durable_begin_and_terminal(
    cancelled: bool,
) -> None:
    store = InMemoryStateStore()
    error = asyncio.CancelledError() if cancelled else RuntimeError("private provider detail")

    async def emit(**kwargs: Any) -> None:
        assert [entry["outcome"] for entry in _entries(store)] == ["started"]
        raise error

    with pytest.raises(type(error)) as raised:
        await _canary.process_canary(
            _host(store, emit), build_canary_event(slot="example-slot", now=NOW)
        )
    assert raised.value is error
    entries = _entries(store)
    assert [entry["outcome"] for entry in entries] == [
        "started",
        "cancelled" if cancelled else "failure",
    ]
    assert entries[0]["attempt_id"] == entries[1]["attempt_id"]
    assert entries[0]["started_at"] == entries[1]["started_at"]
    assert entries[1]["error_type"] == type(error).__name__
    assert "private provider detail" not in str(entries)
    assert all(entry["action_kind"] == "control_loop.canary.attempt" for entry in entries)


async def test_notification_failure_does_not_retract_persisted_success() -> None:
    store = InMemoryStateStore()

    async def emit(**kwargs: Any) -> None:
        if kwargs["stage"] is StageName.AUDIT:
            assert [entry["outcome"] for entry in _entries(store)] == ["started", "success"]
            raise RuntimeError("notification unavailable")
        assert [entry["outcome"] for entry in _entries(store)] == ["started"]

    with pytest.raises(RuntimeError, match="notification unavailable"):
        await _canary.process_canary(
            _host(store, emit), build_canary_event(slot="example-slot", now=NOW)
        )
    entries = _entries(store)
    assert [entry["outcome"] for entry in entries] == ["started", "success"]
    assert entries[0]["attempt_id"] == entries[1]["attempt_id"]
    assert entries[1]["action_kind"] == "control_loop.canary"


async def test_terminal_write_failure_preserves_original_error_and_unresolved_start(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingTerminalStore(InMemoryStateStore):
        async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
            if entry["outcome"] != "started":
                raise OSError("private database detail")
            await super().append_audit_entry(entry)

    store = FailingTerminalStore()
    error = RuntimeError("original failure")

    async def emit(**kwargs: Any) -> None:
        raise error

    with pytest.raises(RuntimeError) as raised:
        await _canary.process_canary(
            _host(store, emit), build_canary_event(slot="example-slot", now=NOW)
        )
    assert raised.value is error
    assert [entry["outcome"] for entry in _entries(store)] == ["started"]
    assert "canary_terminal_audit_unavailable" in caplog.text
    assert "private database detail" not in caplog.text


async def test_cancelled_task_records_cancellation_before_propagating() -> None:
    store = InMemoryStateStore()
    entered = asyncio.Event()

    async def emit(**kwargs: Any) -> None:
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        _canary.process_canary(
            _host(store, emit), build_canary_event(slot="cancelled-task", now=NOW)
        )
    )
    async with asyncio.timeout(1):
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert [entry["outcome"] for entry in _entries(store)] == ["started", "cancelled"]


async def test_uncertain_success_write_does_not_append_contradictory_failure() -> None:
    class UncertainStore(InMemoryStateStore):
        async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
            await super().append_audit_entry(entry)
            if entry["outcome"] == "success":
                raise OSError("commit acknowledgement lost")

    store = UncertainStore()

    async def emit(**kwargs: Any) -> None:
        return None

    with pytest.raises(OSError, match="commit acknowledgement lost"):
        await _canary.process_canary(
            _host(store, emit), build_canary_event(slot="uncertain-write", now=NOW)
        )
    assert [entry["outcome"] for entry in _entries(store)] == ["started", "success"]


async def test_terminal_timeout_leaves_unresolved_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StalledStore(InMemoryStateStore):
        async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
            if entry["outcome"] != "started":
                await asyncio.Event().wait()
            await super().append_audit_entry(entry)

    store = StalledStore()
    monkeypatch.setattr(_canary, "_AUDIT_TIMEOUT_SECONDS", 0.01)

    async def emit(**kwargs: Any) -> None:
        raise RuntimeError("stage failed")

    async with asyncio.timeout(1):
        with pytest.raises(RuntimeError, match="stage failed"):
            await _canary.process_canary(
                _host(store, emit), build_canary_event(slot="stalled-write", now=NOW)
            )
    assert [entry["outcome"] for entry in _entries(store)] == ["started"]
