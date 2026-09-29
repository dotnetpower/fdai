"""Durable Trial storage with compare-and-set observations and one-time activation.

The resolver in `core/licensing/trial_entitlement.py` decides only from a committed
record. This adapter is what commits one, and it is deliberately narrow: it activates
a window once and advances observations, and it can do nothing else.

Two races matter here and both are settled by the database rather than by retry
discipline. Concurrent activation is settled by the singleton primary key, so a second
installer inserts nothing and reads the winner. Concurrent observation is settled by a
revision predicate, so a replica holding a stale revision updates zero rows, re-reads,
and returns the winning record instead of writing a window derived from its own view.

Activation is never repaired here. A missing row means an unactivated installation,
which the resolver treats as no capability; it never means "activate now on read".
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import psycopg

from fdai.core.licensing.trial import TrialRecord

SetStatementTimeout = Callable[[psycopg.AsyncConnection[Any]], Awaitable[None]]

_COLUMNS = (
    "installation_binding, deployment_binding, activated_at, "
    "last_observed_at, revision, clock_blocked"
)


async def read_trial_record(
    *,
    connection: psycopg.AsyncConnection[Any],
    set_statement_timeout: SetStatementTimeout,
) -> TrialRecord | None:
    """Return the committed record, or None when this installation never activated."""

    await set_statement_timeout(connection)
    async with connection.cursor() as cursor:
        await cursor.execute(f"SELECT {_COLUMNS} FROM licensing_trial WHERE singleton")  # noqa: S608 - fixed column list, no caller input
        row = await cursor.fetchone()
    return None if row is None else _record(row)


async def activate_trial_once(
    *,
    connection: psycopg.AsyncConnection[Any],
    set_statement_timeout: SetStatementTimeout,
    installation_binding: str,
    deployment_binding: str,
    now: datetime,
) -> TrialRecord:
    """Activate the window if absent, and always return the committed record.

    A losing concurrent activation inserts nothing and reads the winner, so the
    installation keeps the first activation time rather than the later attempt's.
    """

    candidate = TrialRecord(installation_binding, deployment_binding, now, now)
    await set_statement_timeout(connection)
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            INSERT INTO licensing_trial (
                singleton, installation_binding, deployment_binding,
                activated_at, last_observed_at, revision, clock_blocked
            )
            VALUES (TRUE, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (singleton) DO NOTHING
            """,
            (
                candidate.installation_binding,
                candidate.deployment_binding,
                candidate.activated_at,
                candidate.last_observed_at,
                candidate.revision,
                candidate.clock_blocked,
            ),
        )
        await cursor.execute(f"SELECT {_COLUMNS} FROM licensing_trial WHERE singleton")  # noqa: S608 - fixed column list, no caller input
        row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("Trial activation did not commit a record")
    return _record(row)


async def observe_trial(
    *,
    connection: psycopg.AsyncConnection[Any],
    set_statement_timeout: SetStatementTimeout,
    now: datetime,
) -> TrialRecord | None:
    """Advance the observation under compare-and-set, returning the committed record.

    The returned record is always the one the database holds. A caller that lost the
    race receives the winner rather than its own candidate, so replicas converge on a
    single monotonic observation.
    """

    current = await read_trial_record(
        connection=connection, set_statement_timeout=set_statement_timeout
    )
    if current is None:
        return None
    candidate = current.observe(now=now)
    if candidate.to_mapping() == current.to_mapping():
        return current
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE licensing_trial
            SET last_observed_at = %s, revision = %s, clock_blocked = %s
            WHERE singleton AND revision = %s
            """,
            (
                candidate.last_observed_at,
                candidate.revision,
                candidate.clock_blocked,
                current.revision,
            ),
        )
        if cursor.rowcount == 1:
            return candidate
    return await read_trial_record(
        connection=connection, set_statement_timeout=set_statement_timeout
    )


def _record(row: tuple[Any, ...]) -> TrialRecord:
    """Decode one stored row without repairing a field or restarting the window."""

    installation, deployment, activated, observed, revision, blocked = row
    return TrialRecord(installation, deployment, activated, observed, int(revision), bool(blocked))
