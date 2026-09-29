"""Durable Trial storage tests.

These fix the two races that decide whether a Trial window can be restarted:
concurrent activation must keep the first window, and a losing observer must adopt
the winning record instead of writing one derived from its own stale read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.licensing.trial import TrialRecord
from fdai.delivery.persistence.postgres_licensing_trial import (
    activate_trial_once,
    observe_trial,
    read_trial_record,
)

_NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
_INSTALLATION = "a" * 64
_DEPLOYMENT = "b" * 64


class _Cursor:
    """One fake cursor over a single-row table with primary-key and revision races."""

    def __init__(self, table: dict[str, Any]) -> None:
        self._table = table
        self._result: tuple[Any, ...] | None = None
        self.rowcount = 0

    async def __aenter__(self) -> _Cursor:
        return self

    async def __aexit__(self, *exception: object) -> None:
        return None

    async def execute(self, statement: str, parameters: tuple[Any, ...] = ()) -> None:
        text = " ".join(statement.split())
        if text.startswith("SELECT"):
            row = self._table.get("row")
            self._result = row
            return
        if text.startswith("INSERT"):
            self._table.setdefault("inserts", 0)
            self._table["inserts"] += 1
            if self._table.get("row") is None:
                self._table["row"] = parameters[:2] + parameters[2:]
            return
        if text.startswith("UPDATE"):
            row = self._table.get("row")
            expected = parameters[3]
            if row is not None and row[4] == expected:
                self._table["row"] = row[:3] + (parameters[0], parameters[1], parameters[2])
                self.rowcount = 1
            else:
                self.rowcount = 0
            return
        raise AssertionError(f"unexpected statement: {text}")

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._result


class _Connection:
    def __init__(self, row: tuple[Any, ...] | None = None) -> None:
        self._table: dict[str, Any] = {"row": row}

    def cursor(self) -> _Cursor:
        return _Cursor(self._table)

    @property
    def row(self) -> tuple[Any, ...] | None:
        return self._table.get("row")

    @property
    def inserts(self) -> int:
        return int(self._table.get("inserts", 0))


async def _no_timeout(connection: object) -> None:
    return None


def _row(
    *,
    activated: datetime = _NOW,
    observed: datetime | None = None,
    revision: int = 1,
    blocked: bool = False,
) -> tuple[Any, ...]:
    return (
        _INSTALLATION,
        _DEPLOYMENT,
        activated,
        observed if observed is not None else activated,
        revision,
        blocked,
    )


@pytest.mark.asyncio
async def test_an_unactivated_installation_reads_no_record() -> None:
    connection = _Connection()

    record = await read_trial_record(
        connection=connection,  # type: ignore[arg-type]
        set_statement_timeout=_no_timeout,
    )

    assert record is None


@pytest.mark.asyncio
async def test_activation_creates_one_window() -> None:
    connection = _Connection()

    record = await activate_trial_once(
        connection=connection,  # type: ignore[arg-type]
        set_statement_timeout=_no_timeout,
        installation_binding=_INSTALLATION,
        deployment_binding=_DEPLOYMENT,
        now=_NOW,
    )

    assert record.activated_at == _NOW
    assert record.revision == 1
    assert connection.inserts == 1


@pytest.mark.asyncio
async def test_a_second_activation_keeps_the_first_window() -> None:
    """An upgrade or a racing installer must not restart the clock."""

    connection = _Connection(_row())
    later = _NOW + timedelta(days=10)

    record = await activate_trial_once(
        connection=connection,  # type: ignore[arg-type]
        set_statement_timeout=_no_timeout,
        installation_binding=_INSTALLATION,
        deployment_binding=_DEPLOYMENT,
        now=later,
    )

    assert record.activated_at == _NOW
    assert record.expires_at == TrialRecord(_INSTALLATION, _DEPLOYMENT, _NOW, _NOW).expires_at


@pytest.mark.asyncio
async def test_observing_advances_the_revision_and_time() -> None:
    connection = _Connection(_row())
    later = _NOW + timedelta(hours=1)

    record = await observe_trial(
        connection=connection,  # type: ignore[arg-type]
        set_statement_timeout=_no_timeout,
        now=later,
    )

    assert record is not None
    assert record.last_observed_at == later
    assert record.revision == 2
    assert connection.row is not None and connection.row[4] == 2


@pytest.mark.asyncio
async def test_observing_an_absent_record_never_activates_one() -> None:
    """A read path must not silently start a window it was supposed to find."""

    connection = _Connection()

    record = await observe_trial(
        connection=connection,  # type: ignore[arg-type]
        set_statement_timeout=_no_timeout,
        now=_NOW,
    )

    assert record is None
    assert connection.inserts == 0
    assert connection.row is None


@pytest.mark.asyncio
async def test_a_backward_clock_is_recorded_as_blocked() -> None:
    connection = _Connection(_row(observed=_NOW + timedelta(hours=2)))

    record = await observe_trial(
        connection=connection,  # type: ignore[arg-type]
        set_statement_timeout=_no_timeout,
        now=_NOW,
    )

    assert record is not None
    assert record.clock_blocked is True
    assert record.last_observed_at == _NOW + timedelta(hours=2)


@pytest.mark.asyncio
async def test_a_losing_writer_adopts_the_winning_record() -> None:
    """A stale revision must update nothing and return the committed winner."""

    connection = _Connection(_row())
    original_cursor = connection.cursor
    cursors = 0

    def racing_cursor() -> _Cursor:
        nonlocal cursors
        cursors += 1
        # observe_trial reads first, then updates. Commit a rival revision in between,
        # so this writer's compare-and-set predicate no longer matches.
        if cursors == 2:
            connection._table["row"] = _row(  # noqa: SLF001 - fake connection fixture
                observed=_NOW + timedelta(hours=3), revision=5
            )
        return original_cursor()

    connection.cursor = racing_cursor  # type: ignore[method-assign]
    later = await observe_trial(
        connection=connection,  # type: ignore[arg-type]
        set_statement_timeout=_no_timeout,
        now=_NOW + timedelta(hours=1),
    )

    assert later is not None
    assert later.revision == 5
    assert later.last_observed_at == _NOW + timedelta(hours=3)
