"""PostgresScheduleStore - persistent :class:`ScheduleStore` on Postgres.

Realizes :class:`~fdai.core.scheduler.store.ScheduleStore` against the
``scheduled_task`` table created by
``alembic/versions/20260712_0010_scheduled_task.py`` so schedules survive a
process restart and are shared between the operator console (create / list /
cancel) and the Container Apps Job cron that drives
:meth:`~fdai.core.scheduler.service.SchedulerService.run_once` (P2-6).

Design invariants (mirror the in-memory
:class:`~fdai.core.scheduler.store.InMemoryScheduleStore`)
----------------------------------------------------------

- :meth:`create` refuses a duplicate ``task_id`` (PRIMARY KEY) and surfaces
  it as the same ``ValueError`` the in-memory store raises, so the two
  backends are indistinguishable to callers.
- :meth:`get` / :meth:`cancel` / :meth:`mark_run` raise
  :class:`~fdai.core.scheduler.store.ScheduleNotFoundError` on a missing id.
- :meth:`mark_run` advances ``last_run`` in a single UPDATE and returns the
  refreshed record.

psycopg 3 (already a repo dep); bounded statement / connect timeouts fail
fast rather than blocking the event loop. ``core/`` never imports this
module - the composition root binds it in place of the in-memory default.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.scheduler.models import (
    ScheduledRunIsolationProfile,
    ScheduledTask,
    ScheduleKind,
)
from fdai.core.scheduler.store import ScheduleNotFoundError
from fdai.shared.providers.scheduled_continuation import (
    ContinuationAudience,
    ContinuationMode,
    ScheduledResultOrigin,
)

_COLUMNS: Final[str] = (
    "task_id, name, interval_seconds, event_type, created_by, "
    "event_payload, resource_ref, enabled, start_at, last_run, cron_expression, "
    "schedule_kind, timezone, exit_event_type, exit_observed_at, isolation_profile, "
    "continuation_mode, continuation_origin"
)


@dataclass(frozen=True, slots=True)
class PostgresScheduleStoreConfig:
    """DSN + timeouts for the adapter."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresScheduleStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if self.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")


class PostgresScheduleStore:
    """Async :class:`ScheduleStore` on the ``scheduled_task`` table."""

    def __init__(self, *, config: PostgresScheduleStoreConfig) -> None:
        self._config: Final[PostgresScheduleStoreConfig] = config

    async def create(self, task: ScheduledTask) -> ScheduledTask:
        # Rely on the PRIMARY KEY for atomic duplicate detection rather than a
        # SELECT-then-INSERT (which races: two concurrent creates both see no
        # row and both insert). A UniqueViolation is mapped to the same
        # ValueError the in-memory store raises so the two backends stay
        # indistinguishable to callers.
        async with await self._connect() as conn:
            try:
                async with conn.transaction():
                    await self._set_session_knobs(conn)
                    await conn.execute(
                        f"""
                        INSERT INTO scheduled_task ({_COLUMNS})
                        VALUES (
                            %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb
                        )
                        """,  # noqa: S608 - _COLUMNS is a module constant, values parametrized
                        (
                            task.task_id,
                            task.name,
                            float(task.interval_seconds),
                            task.event_type,
                            task.created_by,
                            json.dumps(dict(task.event_payload), default=str),
                            task.resource_ref,
                            task.enabled,
                            task.start_at,
                            task.last_run,
                            task.cron_expression,
                            task.kind.value,
                            task.timezone,
                            task.exit_event_type,
                            task.exit_observed_at,
                            json.dumps(
                                {
                                    "profile_id": task.isolation_profile.profile_id,
                                    "max_session_seconds": (
                                        task.isolation_profile.max_session_seconds
                                    ),
                                    "max_context_chars": task.isolation_profile.max_context_chars,
                                    "max_tool_calls": task.isolation_profile.max_tool_calls,
                                    "allowed_tool_ids": sorted(
                                        task.isolation_profile.allowed_tool_ids
                                    ),
                                    "command_sandbox_profile_id": (
                                        task.isolation_profile.command_sandbox_profile_id
                                    ),
                                },
                                sort_keys=True,
                            ),
                            task.continuation_mode.value,
                            (
                                _origin_json(task.continuation_origin)
                                if task.continuation_origin is not None
                                else None
                            ),
                        ),
                    )
            except psycopg.errors.UniqueViolation as exc:
                raise ValueError(f"duplicate task_id {task.task_id!r}") from exc
        return task

    async def get(self, task_id: str) -> ScheduledTask:
        async with await self._connect(row_factory=True) as conn:
            await self._set_session_knobs(conn)
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM scheduled_task WHERE task_id = %s",  # noqa: S608
                (task_id,),
            )
            row = await cur.fetchone()
        if row is None:
            raise ScheduleNotFoundError(task_id)
        return _row_to_task(row)

    async def list_all(self) -> Sequence[ScheduledTask]:
        async with await self._connect(row_factory=True) as conn:
            await self._set_session_knobs(conn)
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM scheduled_task ORDER BY created_at"  # noqa: S608
            )
            rows = await cur.fetchall()
        return tuple(_row_to_task(row) for row in rows)

    async def update(self, task: ScheduledTask) -> ScheduledTask:
        async with await self._connect(row_factory=True) as conn:
            async with conn.transaction():
                await self._set_session_knobs(conn)
                cur = await conn.execute(
                    f"""
                    UPDATE scheduled_task
                       SET name = %s,
                           interval_seconds = %s,
                           event_type = %s,
                           event_payload = %s::jsonb,
                           resource_ref = %s,
                           enabled = %s,
                           start_at = %s,
                           last_run = %s,
                           cron_expression = %s,
                           schedule_kind = %s,
                           timezone = %s,
                           exit_event_type = %s,
                           exit_observed_at = %s,
                           isolation_profile = %s::jsonb,
                           continuation_mode = %s,
                           continuation_origin = %s::jsonb
                     WHERE task_id = %s
                     RETURNING {_COLUMNS}
                    """,  # noqa: S608 - column list is static and values are parametrized
                    (
                        task.name,
                        float(task.interval_seconds),
                        task.event_type,
                        json.dumps(dict(task.event_payload), default=str),
                        task.resource_ref,
                        task.enabled,
                        task.start_at,
                        task.last_run,
                        task.cron_expression,
                        task.kind.value,
                        task.timezone,
                        task.exit_event_type,
                        task.exit_observed_at,
                        _isolation_json(task),
                        task.continuation_mode.value,
                        (
                            _origin_json(task.continuation_origin)
                            if task.continuation_origin is not None
                            else None
                        ),
                        task.task_id,
                    ),
                )
                row = await cur.fetchone()
        if row is None:
            raise ScheduleNotFoundError(task.task_id)
        return _row_to_task(row)

    async def cancel(self, task_id: str) -> None:
        async with await self._connect() as conn:
            async with conn.transaction():
                await self._set_session_knobs(conn)
                cur = await conn.execute(
                    "DELETE FROM scheduled_task WHERE task_id = %s", (task_id,)
                )
                if cur.rowcount == 0:
                    raise ScheduleNotFoundError(task_id)

    async def mark_run(self, task_id: str, at: datetime) -> ScheduledTask:
        async with await self._connect(row_factory=True) as conn:
            async with conn.transaction():
                await self._set_session_knobs(conn)
                cur = await conn.execute(
                    f"""
                    UPDATE scheduled_task SET last_run = %s
                     WHERE task_id = %s
                     RETURNING {_COLUMNS}
                    """,  # noqa: S608
                    (at, task_id),
                )
                row = await cur.fetchone()
        if row is None:
            raise ScheduleNotFoundError(task_id)
        return _row_to_task(row)

    async def mark_exit_event(self, event_type: str, at: datetime) -> int:
        async with await self._connect() as conn:
            async with conn.transaction():
                await self._set_session_knobs(conn)
                cursor = await conn.execute(
                    """
                    UPDATE scheduled_task
                       SET enabled = FALSE, exit_observed_at = %s
                     WHERE schedule_kind = 'event-exit'
                       AND exit_event_type = %s
                       AND enabled = TRUE
                    """,
                    (at, event_type),
                )
        return cursor.rowcount

    async def _connect(self, *, row_factory: bool = False) -> psycopg.AsyncConnection[Any]:
        kwargs: dict[str, Any] = {"connect_timeout": self._config.connect_timeout_s}
        if row_factory:
            kwargs["row_factory"] = dict_row
        return await psycopg.AsyncConnection.connect(self._config.dsn, **kwargs)

    async def _set_session_knobs(self, conn: psycopg.AsyncConnection[Any]) -> None:
        timeout_ms = int(self._config.statement_timeout_ms)
        await conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")


def _isolation_json(task: ScheduledTask) -> str:
    profile = task.isolation_profile
    return json.dumps(
        {
            "profile_id": profile.profile_id,
            "max_session_seconds": profile.max_session_seconds,
            "max_context_chars": profile.max_context_chars,
            "max_tool_calls": profile.max_tool_calls,
            "allowed_tool_ids": sorted(profile.allowed_tool_ids),
            "command_sandbox_profile_id": profile.command_sandbox_profile_id,
        },
        sort_keys=True,
    )


def _row_to_task(row: dict[str, Any]) -> ScheduledTask:
    payload = row["event_payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    isolation = row["isolation_profile"]
    if isinstance(isolation, str):
        isolation = json.loads(isolation)
    if not isinstance(isolation, dict):
        raise ValueError("scheduled task isolation_profile MUST be a JSON object")
    return ScheduledTask(
        task_id=str(row["task_id"]),
        name=str(row["name"]),
        interval_seconds=float(row["interval_seconds"]),
        event_type=str(row["event_type"]),
        created_by=str(row["created_by"]),
        event_payload=dict(payload) if isinstance(payload, dict) else {},
        resource_ref=row["resource_ref"],
        enabled=bool(row["enabled"]),
        start_at=row["start_at"],
        last_run=row["last_run"],
        cron_expression=row.get("cron_expression"),
        schedule_kind=ScheduleKind(str(row["schedule_kind"])),
        timezone=str(row["timezone"]),
        exit_event_type=row["exit_event_type"],
        exit_observed_at=row["exit_observed_at"],
        isolation_profile=ScheduledRunIsolationProfile(
            profile_id=str(isolation["profile_id"]),
            max_session_seconds=int(isolation["max_session_seconds"]),
            max_context_chars=int(isolation["max_context_chars"]),
            max_tool_calls=int(isolation["max_tool_calls"]),
            allowed_tool_ids=frozenset(str(value) for value in isolation["allowed_tool_ids"]),
            command_sandbox_profile_id=(
                str(isolation["command_sandbox_profile_id"])
                if isolation.get("command_sandbox_profile_id") is not None
                else None
            ),
        ),
        continuation_mode=ContinuationMode(str(row["continuation_mode"])),
        continuation_origin=(
            _origin(row["continuation_origin"])
            if row.get("continuation_origin") is not None
            else None
        ),
    )


def _origin_json(origin: ScheduledResultOrigin) -> str:
    return json.dumps(
        {
            "audience": origin.audience.value,
            "channel_kind": origin.channel_kind,
            "channel_ref": origin.channel_ref,
            "conversation_ref": origin.conversation_ref,
            "thread_ref": origin.thread_ref,
        },
        sort_keys=True,
    )


def _origin(raw: Any) -> ScheduledResultOrigin:
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, dict):
        raise ValueError("scheduled task continuation_origin MUST be a JSON object")
    return ScheduledResultOrigin(
        channel_kind=str(value["channel_kind"]),
        channel_ref=str(value["channel_ref"]),
        conversation_ref=str(value["conversation_ref"]),
        thread_ref=(str(value["thread_ref"]) if value.get("thread_ref") is not None else None),
        audience=ContinuationAudience(str(value["audience"])),
    )


__all__ = [
    "PostgresScheduleStore",
    "PostgresScheduleStoreConfig",
]
