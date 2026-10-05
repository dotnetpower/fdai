"""Tests for the bounded development PostgreSQL power window."""

from __future__ import annotations

import json
import stat
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts.deployment.azure import postgres_power_window as window

_SERVER_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example"
    "/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-example"
)
_FAST = window.WindowTiming(open_deadline_seconds=60.0, close_deadline_seconds=60.0, poll_seconds=1)


class _Azure:
    """Scripted Azure CLI double: each `show` pops the next power state."""

    def __init__(self, *states: str) -> None:
        self.states = list(states)
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, arguments: Sequence[str], timeout: float) -> str:
        assert timeout > 0
        self.calls.append(tuple(arguments))
        if arguments[2] == "show":
            return self.states.pop(0)
        return ""

    def verbs(self) -> list[str]:
        return [call[2] for call in self.calls]


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def _open(azure: _Azure, record: Path, clock: _Clock | None = None) -> dict[str, object]:
    clock = clock or _Clock()
    return window.open_window(
        _SERVER_ID,
        record,
        runner=azure,
        timing=_FAST,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        now=lambda: datetime(2026, 10, 5, tzinfo=UTC),
    )


def _close(azure: _Azure, record: Path, clock: _Clock | None = None) -> str:
    clock = clock or _Clock()
    return window.close_window(
        record, runner=azure, timing=_FAST, monotonic=clock.monotonic, sleep=clock.sleep
    )


def test_ready_server_is_left_running(tmp_path: Path) -> None:
    record = tmp_path / "window.json"
    azure = _Azure("Ready")

    opened = _open(azure, record)

    assert opened["started_by_run"] is False
    assert azure.verbs() == ["show"]
    assert _close(_Azure(), record) == "left-ready"


def test_stopped_server_is_claimed_before_start_and_restored(tmp_path: Path) -> None:
    record = tmp_path / "window.json"
    azure = _Azure("Stopped", "Starting", "Ready")

    opened = _open(azure, record)

    assert opened["started_by_run"] is True
    assert azure.verbs() == ["show", "start", "show", "show"]
    assert stat.S_IMODE(record.stat().st_mode) == 0o600
    persisted = json.loads(record.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == window.SCHEMA_VERSION
    assert persisted["initial_state"] == "Stopped"

    closing = _Azure("Ready", "Stopping", "Stopped")
    assert _close(closing, record) == "stopped"
    assert closing.verbs() == ["show", "stop", "show", "show"]
    assert ("--ids", _SERVER_ID) == closing.calls[1][3:5]


def test_claim_survives_a_start_that_never_becomes_ready(tmp_path: Path) -> None:
    record = tmp_path / "window.json"
    azure = _Azure("Stopped", *(["Starting"] * 100))

    with pytest.raises(window.PowerWindowError, match="past the deadline"):
        _open(azure, record)

    assert json.loads(record.read_text(encoding="utf-8"))["started_by_run"] is True
    closing = _Azure("Ready", "Stopped")
    assert _close(closing, record) == "stopped"


def test_server_stopping_at_open_is_awaited_then_started(tmp_path: Path) -> None:
    record = tmp_path / "window.json"
    azure = _Azure("Stopping", "Stopped", "Ready")

    opened = _open(azure, record)

    assert opened["initial_state"] == "Stopped"
    assert azure.verbs() == ["show", "show", "start", "show"]


def test_close_does_not_stop_an_already_stopped_server(tmp_path: Path) -> None:
    record = tmp_path / "window.json"
    _open(_Azure("Stopped", "Ready"), record)
    closing = _Azure("Stopped")

    assert _close(closing, record) == "already-stopped"
    assert closing.verbs() == ["show"]


def test_close_without_an_opened_window_is_a_no_op(tmp_path: Path) -> None:
    azure = _Azure()

    assert _close(azure, tmp_path / "absent.json") == "not-opened"
    assert azure.calls == []


@pytest.mark.parametrize("state", ["Disabled", "Dropping", ""])
def test_unsupported_states_fail_closed_without_a_start(tmp_path: Path, state: str) -> None:
    azure = _Azure(state)

    with pytest.raises(window.PowerWindowError):
        _open(azure, tmp_path / "window.json")

    assert "start" not in azure.verbs()


def test_existing_record_is_never_reused(tmp_path: Path) -> None:
    record = tmp_path / "window.json"
    record.write_text("{}", encoding="utf-8")
    azure = _Azure("Stopped")

    with pytest.raises(window.PowerWindowError, match="already exists"):
        _open(azure, record)

    assert azure.calls == []


@pytest.mark.parametrize(
    "server_id",
    [
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg"
        "/providers/Microsoft.DBforMySQL/flexibleServers/mysql-example",
        "psql-example",
        _SERVER_ID + "/databases/fdai",
    ],
)
def test_only_postgres_flexible_server_ids_are_accepted(tmp_path: Path, server_id: str) -> None:
    with pytest.raises(window.PowerWindowError, match="PostgreSQL Flexible Server id"):
        window.open_window(server_id, tmp_path / "window.json", runner=_Azure())


def test_malformed_record_fails_closed(tmp_path: Path) -> None:
    record = tmp_path / "window.json"
    record.write_text(json.dumps({"schema_version": "other"}), encoding="utf-8")

    with pytest.raises(window.PowerWindowError, match="malformed"):
        _close(_Azure(), record)


def test_cli_reports_failure_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = tmp_path / "window.json"
    record.write_text(json.dumps({"schema_version": "other"}), encoding="utf-8")

    assert window.main(["close", "--record", str(record)]) == 1
    assert "database power window failed" in capsys.readouterr().err
