"""Entitlement state publication tests.

The writer is the one place a notice enters storage, and the publisher is the one
loop that keeps it current. These prove the monotonic upsert, the bounded
transaction, off-loop resolution, and that a failed tick never stops Core.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.licensing.entitlement import Entitlement, LicenseStatus
from fdai.core.licensing.entitlement_notice import ACTING_CAPABILITY_ID, EntitlementNotice
from fdai.delivery.persistence.postgres_licensing_entitlement_state import (
    PostgresEntitlementStateWriter,
)
from fdai.runtime.licensing_state import (
    EntitlementStatePublisher,
    build_entitlement_state_publisher,
)

_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exception: object) -> None:
        return None


class _Connection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *exception: object) -> None:
        self.closed = True

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(self, statement: str, parameters: tuple[Any, ...] = ()) -> None:
        self.statements.append((" ".join(statement.split()), parameters))


def _writer(connection: _Connection, calls: list[dict[str, Any]]) -> PostgresEntitlementStateWriter:
    async def connect(dsn: str, **options: Any) -> _Connection:
        calls.append({"dsn": dsn, **options})
        return connection

    return PostgresEntitlementStateWriter(
        dsn="postgresql://core@db.invalid/fdai",
        statement_timeout_ms=1_500,
        connect_timeout_s=3,
        connect=connect,
    )


async def test_the_writer_upserts_one_monotonic_notice_in_a_bounded_transaction() -> None:
    connection = _Connection()
    calls: list[dict[str, Any]] = []

    await _writer(connection, calls).publish(EntitlementNotice.EVALUATION_ENDED, observed_at=_NOW)

    assert calls == [{"dsn": "postgresql://core@db.invalid/fdai", "connect_timeout": 3}]
    assert connection.statements[0] == ("SET LOCAL statement_timeout = 1500", ())
    statement, parameters = connection.statements[1]
    assert statement.startswith("INSERT INTO licensing_entitlement_state")
    assert "WHERE licensing_entitlement_state.observed_at <= EXCLUDED.observed_at" in statement
    assert parameters == ("evaluation-ended", _NOW)
    assert connection.closed


async def test_the_writer_refuses_a_naive_observation_time() -> None:
    connection = _Connection()

    with pytest.raises(ValueError, match="timezone-aware"):
        await _writer(connection, []).publish(
            EntitlementNotice.NONE, observed_at=datetime(2026, 10, 1, 12, 0)
        )
    assert connection.statements == []


async def test_the_writer_refuses_a_notice_outside_the_vocabulary() -> None:
    with pytest.raises(ValueError):
        await _writer(_Connection(), []).publish(
            "hidden",  # type: ignore[arg-type]
            observed_at=_NOW,
        )


@pytest.mark.parametrize(
    ("dsn", "timeout_ms", "connect_s"),
    [(" ", 5_000, 5), ("postgresql://db.invalid/fdai", 0, 5), ("postgresql://x", 5, 0)],
)
def test_the_writer_requires_a_dsn_and_positive_timeouts(
    dsn: str, timeout_ms: int, connect_s: int
) -> None:
    with pytest.raises(ValueError):
        PostgresEntitlementStateWriter(
            dsn=dsn, statement_timeout_ms=timeout_ms, connect_timeout_s=connect_s
        )


class _Authority:
    """Resolve on a worker thread only, like the real Trial-backed authority."""

    def __init__(self, entitlement: Entitlement, *, fail: int = 0) -> None:
        self._entitlement = entitlement
        self._fail = fail
        self.calls: list[datetime] = []
        self.threads: list[bool] = []

    def resolve(self, *, now: datetime) -> Entitlement:
        self.calls.append(now)
        self.threads.append(threading.current_thread() is threading.main_thread())
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("resolved on the event loop")
        if self._fail:
            self._fail -= 1
            raise RuntimeError("storage unavailable")
        return self._entitlement


class _Writer:
    def __init__(self) -> None:
        self.published: list[tuple[EntitlementNotice, datetime]] = []

    async def publish(self, notice: EntitlementNotice, *, observed_at: datetime) -> None:
        self.published.append((notice, observed_at))


async def test_the_publisher_resolves_off_the_loop_and_records_the_notice() -> None:
    authority = _Authority(
        Entitlement(
            status=LicenseStatus.ACTIVE,
            available_capability_ids=frozenset({ACTING_CAPABILITY_ID}),
        )
    )
    writer = _Writer()
    publisher = EntitlementStatePublisher(
        authority=authority,  # type: ignore[arg-type]
        writer=writer,
        clock=lambda: _NOW,
    )

    notice = await publisher.publish_once()

    assert notice is EntitlementNotice.NONE
    assert authority.calls == [_NOW]
    assert authority.threads == [False]
    assert writer.published == [(EntitlementNotice.NONE, _NOW)]


async def test_a_failed_tick_is_logged_and_the_next_tick_publishes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    authority = _Authority(Entitlement(status=LicenseStatus.ABSENT), fail=1)
    writer = _Writer()
    stop = asyncio.Event()
    times = iter([_NOW, _NOW + timedelta(seconds=1)])

    class _StopAfterPublish(_Writer):
        async def publish(self, notice: EntitlementNotice, *, observed_at: datetime) -> None:
            await writer.publish(notice, observed_at=observed_at)
            stop.set()

    publisher = EntitlementStatePublisher(
        authority=authority,  # type: ignore[arg-type]
        writer=_StopAfterPublish(),
        clock=lambda: next(times),
        interval_seconds=0.01,
    )

    with caplog.at_level(logging.WARNING, logger="fdai.startup"):
        await asyncio.wait_for(publisher.run(stop), timeout=5)

    assert writer.published == [(EntitlementNotice.NOT_ACTIVATED, _NOW + timedelta(seconds=1))]
    assert [record.message for record in caplog.records] == [
        "license_entitlement_state_publish_failed"
    ]
    assert "storage unavailable" not in caplog.text


async def test_the_publisher_stops_without_another_tick() -> None:
    authority = _Authority(Entitlement(status=LicenseStatus.ABSENT))
    stop = asyncio.Event()
    stop.set()
    publisher = EntitlementStatePublisher(
        authority=authority,  # type: ignore[arg-type]
        writer=_Writer(),
        clock=lambda: _NOW,
    )

    await asyncio.wait_for(publisher.run(stop), timeout=5)

    assert authority.calls == []


def test_publication_needs_the_state_store(caplog: pytest.LogCaptureFixture) -> None:
    authority = _Authority(Entitlement(status=LicenseStatus.ABSENT))

    with caplog.at_level(logging.WARNING, logger="fdai.startup"):
        unbound = build_entitlement_state_publisher(
            authority=authority,  # type: ignore[arg-type]
            environment={"FDAI_STATE_STORE_DSN": "  "},
        )
    bound = build_entitlement_state_publisher(
        authority=authority,  # type: ignore[arg-type]
        environment={"FDAI_STATE_STORE_DSN": "postgresql://core@db.invalid/fdai"},
    )

    assert unbound is None
    assert [record.message for record in caplog.records] == [
        "license_entitlement_state_unpublished"
    ]
    assert isinstance(bound, EntitlementStatePublisher)
    assert isinstance(bound.writer, PostgresEntitlementStateWriter)
