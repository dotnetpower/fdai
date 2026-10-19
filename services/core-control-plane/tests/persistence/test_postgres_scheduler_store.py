"""PostgresScheduleStore - offline unit + DB-gated integration tests (P2-6).

The DB-touching tests are gated on ``FDAI_DATABASE_URL`` and mirror the
skip pattern in ``services/core-control-plane/tests/persistence/test_postgres_operator_memory.py``.
The integration test proves schedules survive a "restart" by using two
independent store instances against the same database, and that the
scheduler's due-lookup path (``list_all`` + ``mark_run``) round-trips.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from fdai.core.conversation.creation import CreateScheduledTaskCommand
from fdai.core.conversation.session import Principal, Role
from fdai.core.scheduler.models import (
    ScheduledRunIsolationProfile,
    ScheduledTask,
    ScheduleKind,
)
from fdai.core.scheduler.service import SchedulerService
from fdai.core.scheduler.store import ScheduleNotFoundError
from fdai.delivery.persistence.postgres_scheduler_store import (
    PostgresScheduleStore,
    PostgresScheduleStoreConfig,
    _row_to_task,
)
from fdai.shared.providers.scheduled_continuation import (
    ContinuationMode,
    ScheduledResultOrigin,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
async def replay_stores() -> AsyncIterator[tuple[PostgresScheduleStore, PostgresScheduleStore]]:
    dsn = _plain_dsn(_requires_live_db())
    settings = conninfo_to_dict(dsn)
    if settings.get("host") not in {"localhost", "127.0.0.1", "::1"} or (
        os.environ.get("GITHUB_ACTIONS") != "true" and settings.get("port") != "5433"
    ):
        pytest.fail("schedule replay requires the isolated loopback validation database")
    _upgrade_head()
    schema = f"schedule_replay_test_{uuid.uuid4().hex}"
    async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as connection:
        await connection.execute("SET statement_timeout = '15s'")
        await connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        await connection.execute(
            sql.SQL(
                "CREATE TABLE {}.scheduled_task (LIKE public.scheduled_task INCLUDING ALL)"
            ).format(sql.Identifier(schema))
        )
    config = PostgresScheduleStoreConfig(dsn=make_conninfo(dsn, options=f"-c search_path={schema}"))
    try:
        yield PostgresScheduleStore(config=config), PostgresScheduleStore(config=config)
    finally:
        async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as connection:
            await connection.execute("SET statement_timeout = '15s'")
            await connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


@pytest.mark.integration
@pytest.mark.parametrize("value", [True, 1.0, -0.0])
async def test_creation_replay_after_real_dispatch_preserves_postgres_progress(
    replay_stores: tuple[PostgresScheduleStore, PostgresScheduleStore], value: object
) -> None:
    first, restarted = replay_stores
    actor = Principal(id="operator-1", role=Role.CONTRIBUTOR)
    arguments = {
        "principal": actor,
        "task_id": "daily-read",
        "name": "Daily bounded observation",
        "interval_seconds": 86400,
        "event_type": "synthetic.monitoring",
        "event_payload": {"value": value},
    }
    created = await CreateScheduledTaskCommand(store=first).create(**arguments)
    bus = InMemoryEventBus()
    now = datetime(2026, 10, 19, tzinfo=UTC)
    report = await SchedulerService(store=first, event_bus=bus).run_once(now=now)
    assert report.fired == 1
    replayed = await CreateScheduledTaskCommand(store=restarted).create(**arguments)
    assert replayed.task_id == created.task_id
    assert replayed.last_run == now
    assert replayed.kind is ScheduleKind.INTERVAL
    assert len(await restarted.list_all()) == 1
    assert (await SchedulerService(store=restarted, event_bus=bus).run_once(now=now)).fired == 0


@pytest.mark.integration
async def test_postgres_atomic_creation_race_converges_without_duplicate_tasks(
    replay_stores: tuple[PostgresScheduleStore, PostgresScheduleStore],
) -> None:
    ready = asyncio.Event()
    misses = 0

    class BarrierStore(PostgresScheduleStore):
        async def get(self, task_id: str) -> ScheduledTask:
            nonlocal misses
            try:
                return await super().get(task_id)
            except ScheduleNotFoundError:
                if misses < 2:
                    misses += 1
                    if misses == 2:
                        ready.set()
                    await ready.wait()
                raise

    source, _other = replay_stores
    first = BarrierStore(config=source._config)
    second = BarrierStore(config=source._config)
    actor = Principal(id="operator-1", role=Role.CONTRIBUTOR)

    async def create(store: PostgresScheduleStore) -> ScheduledTask:
        return await CreateScheduledTaskCommand(store=store).create(
            principal=actor,
            task_id="same-task",
            name="same definition",
            interval_seconds=86400,
            event_type="synthetic.monitoring",
        )

    a, b = await asyncio.gather(create(first), create(second))
    assert a.task_id == b.task_id
    assert len(await source.list_all()) == 1


# ---------------------------------------------------------------------------
# Offline unit tests.
# ---------------------------------------------------------------------------


def test_config_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresScheduleStoreConfig(dsn="")


def test_config_rejects_bad_timeout() -> None:
    with pytest.raises(ValueError, match="timeout"):
        PostgresScheduleStoreConfig(dsn="postgresql://x", statement_timeout_ms=0)


def test_scheduled_task_continuation_row_codec_round_trips() -> None:
    row = {
        "task_id": "task-continuable",
        "name": "continuable task",
        "interval_seconds": 60,
        "event_type": "synthetic.monitor.scope",
        "created_by": "principal-a",
        "event_payload": {},
        "resource_ref": "scope-a",
        "enabled": True,
        "start_at": None,
        "last_run": None,
        "cron_expression": None,
        "schedule_kind": "interval",
        "timezone": "UTC",
        "exit_event_type": None,
        "exit_observed_at": None,
        "isolation_profile": {
            "profile_id": "scheduled.default-deny",
            "max_session_seconds": 300,
            "max_context_chars": 16000,
            "max_tool_calls": 0,
            "allowed_tool_ids": [],
            "command_sandbox_profile_id": None,
        },
        "continuation_mode": "origin_thread",
        "continuation_origin": json.dumps(
            {
                "audience": "direct",
                "channel_kind": "web",
                "channel_ref": "console",
                "conversation_ref": "conversation-1",
                "thread_ref": None,
            }
        ),
    }

    task = _row_to_task(row)

    assert task.continuation_mode is ContinuationMode.ORIGIN_THREAD
    assert task.continuation_origin == ScheduledResultOrigin(
        channel_kind="web",
        channel_ref="console",
        conversation_ref="conversation-1",
    )


# ---------------------------------------------------------------------------
# Integration tests - require a live Postgres.
# ---------------------------------------------------------------------------


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _plain_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _task(task_id: str, *, interval: float = 3600.0) -> ScheduledTask:
    return ScheduledTask(
        task_id=task_id,
        name="cost probe",
        interval_seconds=interval,
        event_type="synthetic.cost.probe",
        created_by="oid-c",
        event_payload={"scope": "sub-a"},
        resource_ref="rg/sub-a",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_crud_and_survives_restart() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    cfg = PostgresScheduleStoreConfig(dsn=dsn)

    tid = f"task-{uuid.uuid4().hex[:8]}"
    store = PostgresScheduleStore(config=cfg)

    created = await store.create(_task(tid))
    assert created.task_id == tid

    # duplicate id fails closed, same as the in-memory store
    with pytest.raises(ValueError, match="duplicate"):
        await store.create(_task(tid))

    got = await store.get(tid)
    assert got.event_payload == {"scope": "sub-a"}
    assert got.resource_ref == "rg/sub-a"

    # "Restart": a brand-new store instance sees the persisted task.
    store2 = PostgresScheduleStore(config=cfg)
    listed = [t for t in await store2.list_all() if t.task_id == tid]
    assert len(listed) == 1
    assert listed[0].last_run is None

    # mark_run advances last_run and round-trips.
    ran_at = datetime(2026, 7, 12, 6, 0, 0, tzinfo=UTC)
    updated = await store2.mark_run(tid, ran_at)
    assert updated.last_run == ran_at

    # cancel removes it; a second cancel raises NotFound.
    await store2.cancel(tid)
    with pytest.raises(ScheduleNotFoundError):
        await store2.get(tid)
    with pytest.raises(ScheduleNotFoundError):
        await store2.cancel(tid)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scheduler_run_once_over_postgres_store() -> None:
    url = _requires_live_db()

    from fdai.core.scheduler.service import SchedulerService
    from fdai.shared.providers.testing import InMemoryEventBus

    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresScheduleStore(config=PostgresScheduleStoreConfig(dsn=dsn))

    tid = f"task-{uuid.uuid4().hex[:8]}"
    await store.create(_task(tid, interval=60.0))

    bus = InMemoryEventBus()
    service = SchedulerService(store=store, event_bus=bus)
    report = await service.run_once(now=datetime(2026, 7, 12, 7, 0, 0, tzinfo=UTC))

    assert report.fired >= 1
    # the fired task's last_run is now persisted
    refreshed = await store.get(tid)
    assert refreshed.last_run is not None
    await store.cancel(tid)


@pytest.mark.integration
async def test_expanded_schedule_fields_and_event_exit_survive_restart() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresScheduleStore(config=PostgresScheduleStoreConfig(dsn=dsn))
    cron_id = f"cron-{uuid.uuid4().hex[:8]}"
    exit_id = f"exit-{uuid.uuid4().hex[:8]}"
    await store.create(
        ScheduledTask(
            task_id=cron_id,
            name="local cron",
            interval_seconds=60,
            event_type="synthetic.cron",
            created_by="operator-example",
            schedule_kind=ScheduleKind.CRON,
            cron_expression="0 21 * * *",
            timezone="Asia/Seoul",
        )
    )
    await store.create(
        ScheduledTask(
            task_id=exit_id,
            name="until deployment",
            interval_seconds=60,
            event_type="synthetic.until",
            created_by="operator-example",
            schedule_kind=ScheduleKind.EVENT_EXIT,
            exit_event_type="deployment.completed",
            isolation_profile=ScheduledRunIsolationProfile(
                profile_id="scheduled.inventory",
                max_tool_calls=1,
                allowed_tool_ids=frozenset({"query_inventory"}),
            ),
        )
    )

    restarted = PostgresScheduleStore(config=PostgresScheduleStoreConfig(dsn=dsn))
    cron = await restarted.get(cron_id)
    assert cron.kind is ScheduleKind.CRON
    assert cron.timezone == "Asia/Seoul"
    assert await restarted.mark_exit_event("deployment.completed", datetime.now(tz=UTC)) >= 1
    exited = await restarted.get(exit_id)
    assert exited.enabled is False
    assert exited.isolation_profile.allowed_tool_ids == frozenset({"query_inventory"})
    await restarted.cancel(cron_id)
    await restarted.cancel(exit_id)
