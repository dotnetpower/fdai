"""Trial activation writer tests.

The writer is the only path that opens a Trial window. These pin that it opens the
window at the installation's anchored time, never at the time of the run, keeps a
retained record exactly as stored, and refuses a record bound to another
installation without changing it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fdai.core.licensing.trial import TRIAL_DURATION
from fdai.delivery.persistence.postgres_licensing_trial import Connect
from fdai.runtime import licensing_trial_activation as activation

_ANCHOR = datetime(2026, 9, 1, 8, 30, tzinfo=UTC)
_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
_INSTALLATION = "e" * 64
_DEPLOYMENT = "f" * 64
_DSN = "postgresql://fdai:not-a-secret@db.invalid/fdai"


class _Cursor:
    def __init__(self, table: dict[str, Any]) -> None:
        self._table = table
        self._result: tuple[Any, ...] | None = None

    async def __aenter__(self) -> _Cursor:
        return self

    async def __aexit__(self, *exception: object) -> None:
        return None

    async def execute(self, statement: str, parameters: tuple[Any, ...] = ()) -> None:
        text = " ".join(statement.split())
        if text.startswith("INSERT"):
            self._table["inserts"] = self._table.get("inserts", 0) + 1
            if self._table.get("row") is None:
                self._table["row"] = parameters
            return
        if text.startswith("SELECT"):
            self._result = self._table.get("row")
            return
        raise AssertionError(f"unexpected statement: {text}")

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._result


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exception: object) -> None:
        return None


class _Connection:
    def __init__(self, row: tuple[Any, ...] | None = None) -> None:
        self.table: dict[str, Any] = {"row": row}
        self.statements: list[str] = []
        self.closed = False

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *exception: object) -> None:
        self.closed = True

    def transaction(self) -> _Transaction:
        return _Transaction()

    def cursor(self) -> _Cursor:
        return _Cursor(self.table)

    async def execute(self, statement: str) -> None:
        self.statements.append(statement)


def _connector(connection: _Connection, calls: list[str]) -> Connect:
    async def connect(dsn: str, **options: object) -> _Connection:
        calls.append(dsn)
        return connection

    return connect


def _retained(
    *,
    installation: str = _INSTALLATION,
    activated: datetime = _ANCHOR,
    observed: datetime | None = None,
) -> tuple[Any, ...]:
    return (installation, _DEPLOYMENT, activated, observed or activated, 1, False)


def _run(
    connection: _Connection,
    *,
    calls: list[str] | None = None,
    activated_at: str = "2026-09-01T08:30:00Z",
    installation: str = _INSTALLATION,
    environ: dict[str, str] | None = None,
) -> int:
    return activation.main(
        [
            "--installation-binding",
            installation,
            "--deployment-binding",
            _DEPLOYMENT,
            "--activated-at",
            activated_at,
        ],
        environ={"FDAI_STATE_STORE_DSN": _DSN} if environ is None else environ,
        clock=lambda: _NOW,
        connect=_connector(connection, [] if calls is None else calls),
    )


def test_a_missing_record_opens_the_window_at_the_anchored_time(
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _Connection()

    assert _run(connection) == 0

    row = connection.table["row"]
    assert row[2] == _ANCHOR
    assert row[3] == _ANCHOR
    assert connection.closed is True
    assert connection.statements == ["SET LOCAL statement_timeout = 5000"]
    receipt = json.loads(capsys.readouterr().out)
    assert receipt == {
        "schema_version": "fdai.trial-activation.v1",
        "outcome": "retained",
        "activated_at": _ANCHOR.isoformat(),
        "expires_at": (_ANCHOR + TRIAL_DURATION).isoformat(),
        "window_ended": False,
        "clock_blocked": False,
    }


def test_a_retained_record_is_never_restarted(capsys: pytest.CaptureFixture[str]) -> None:
    earlier = _ANCHOR - timedelta(days=40)
    connection = _Connection(_retained(activated=earlier))

    assert _run(connection) == 0

    assert connection.table["row"] == _retained(activated=earlier)
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["activated_at"] == earlier.isoformat()
    assert receipt["window_ended"] is True


def test_a_record_for_another_installation_is_refused_and_untouched(
    capsys: pytest.CaptureFixture[str],
) -> None:
    foreign = _retained(installation="0" * 64)
    connection = _Connection(foreign)

    assert _run(connection) == activation.EXIT_REFUSED

    assert connection.table["row"] == foreign
    failure = json.loads(capsys.readouterr().err)
    assert failure["outcome"] == "failed"
    assert "another installation" in failure["reason"]


@pytest.mark.parametrize(
    ("activated_at", "installation"),
    [
        ("2026-09-01T08:30:00", _INSTALLATION),
        ("2026-09-01T17:30:00+09:00", _INSTALLATION),
        ("2026-09-04T00:00:00Z", _INSTALLATION),
        ("yesterday", _INSTALLATION),
        ("2026-09-01T08:30:00Z", "E" * 64),
        ("2026-09-01T08:30:00Z", "e" * 63),
    ],
)
def test_invalid_input_writes_nothing(
    capsys: pytest.CaptureFixture[str], activated_at: str, installation: str
) -> None:
    connection = _Connection()

    assert (
        _run(connection, activated_at=activated_at, installation=installation)
        == activation.EXIT_INVALID
    )

    assert connection.table.get("inserts", 0) == 0
    assert json.loads(capsys.readouterr().err)["outcome"] == "failed"


def test_a_missing_dsn_attempts_no_connection(capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[str] = []

    assert _run(_Connection(), calls=calls, environ={}) == activation.EXIT_INVALID

    assert calls == []
    assert "FDAI_STATE_STORE_DSN" in json.loads(capsys.readouterr().err)["reason"]


@pytest.mark.parametrize("error", [OSError("refused"), psycopg.OperationalError("down")])
def test_unavailable_storage_fails_without_echoing_the_dsn(
    capsys: pytest.CaptureFixture[str], error: Exception
) -> None:
    async def unreachable(dsn: str, **options: object) -> _Connection:
        raise error

    code = activation.main(
        [
            "--installation-binding",
            _INSTALLATION,
            "--deployment-binding",
            _DEPLOYMENT,
            "--activated-at",
            "2026-09-01T08:30:00Z",
        ],
        environ={"FDAI_STATE_STORE_DSN": _DSN},
        clock=lambda: _NOW,
        connect=unreachable,
    )

    assert code == activation.EXIT_UNAVAILABLE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not-a-secret" not in captured.err
    assert "db.invalid" not in captured.err
