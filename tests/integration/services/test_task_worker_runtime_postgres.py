"""Task-owned loopback PostgreSQL proof; model HTTP and identity are synthetic, never live."""

from __future__ import annotations

import asyncio
import os
import runpy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import psycopg
import pytest
from fdai.core.task_worker import (
    AttenuatedCapabilities,
    TaskWorkerBudget,
    TaskWorkerRequest,
    TaskWorkerResult,
    TaskWorkerSnapshot,
    TaskWorkerStatus,
    TaskWorkerUsage,
)
from fdai.delivery.persistence.postgres_task_worker import (
    PostgresTaskWorkerStoreConfig,
    _capabilities_to_dict,
    _request_to_dict,
    _result_to_dict,
    _usage_to_dict,
)
from fdai.delivery.persistence.postgres_task_worker_runtime import PostgresTaskWorkerRuntimeStore
from fdai.runtime.task_workers import build_task_worker_runtime_from_env
from fdai.shared.providers.workload_identity import IdentityToken
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[3]
binding_arguments = runpy.run_path(
    str(ROOT / "services/core-control-plane/tests/runtime/test_task_workers.py")
)["binding_arguments"]
NOW = datetime(2026, 9, 15, tzinfo=UTC)
pytestmark = pytest.mark.integration


@pytest.fixture
def database():
    source = os.environ.get("FDAI_TASK_WORKER_TEST_DSN")
    if not source:
        pytest.skip("FDAI_TASK_WORKER_TEST_DSN is unset")
    parameters = conninfo_to_dict(source)
    if parameters.get("host") not in {"127.0.0.1", "localhost", "::1"} or parameters.get(
        "password"
    ):
        pytest.fail(
            "worker tests require loopback and private PGPASSWORD, not a credential in the DSN"
        )
    name = "fdai_worker_805_" + uuid4().hex[:12]
    statements = []
    for relative in (
        "20260720_0039_task_worker.py",
        "20260714_0015_inventory_snapshots.py",
        "20260718_0035_inventory_realtime_overlay.py",
    ):
        module = runpy.run_path(str(ROOT / "alembic/versions" / relative))
        with patch("alembic.op.execute", side_effect=statements.append):
            module["upgrade"]()
    with psycopg.connect(source, autocommit=True) as admin:
        if admin.execute("SELECT 1 FROM pg_roles WHERE rolname='fdai_core'").fetchone() is None:
            admin.execute(
                sql.SQL("CREATE ROLE fdai_core LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}").format(
                    sql.Literal(os.environ["PGPASSWORD"])
                )
            )
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        dsn = make_conninfo(source, dbname=name)
        try:
            with psycopg.connect(dsn) as connection:
                for statement in statements:
                    connection.execute(statement)
                connection.execute(
                    "GRANT USAGE ON SCHEMA public TO fdai_core; "
                    "GRANT SELECT, INSERT, UPDATE ON task_worker_run TO fdai_core; "
                    "GRANT SELECT, INSERT ON task_worker_event TO fdai_core; "
                    "GRANT SELECT ON inventory_active, inventory_snapshot, "
                    "inventory_snapshot_resource, inventory_realtime_resource TO fdai_core;"
                )
            yield dsn, make_conninfo(dsn, user="fdai_core")
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def request(worker_id="worker:one"):
    return TaskWorkerRequest(
        worker_id=worker_id,
        parent_trace_ref="trace:one",
        cancellation_owner="person:one",
        goal="Read selected evidence.",
        evidence_refs=("evidence:one",),
        constraints=(),
        requested_tools=frozenset(),
        budget=TaskWorkerBudget(),
        created_at=NOW,
    )


def _snapshot(req, *, usage=None):
    return TaskWorkerSnapshot(
        req,
        AttenuatedCapabilities(frozenset()),
        TaskWorkerStatus.RUNNING,
        usage if usage is not None else TaskWorkerUsage(),
        NOW,
    )


async def _binding(dsn, client, *, identity=None):
    arguments = binding_arguments(dsn)
    arguments["http_client"] = client
    if identity is not None:
        arguments["identity"] = identity
    binding = await build_task_worker_runtime_from_env(**arguments)
    assert binding is not None
    return binding


async def test_actual_runtime_recovers_unknown_allowance_behind_terminal_history(database):
    admin_dsn, core_dsn = database
    store = PostgresTaskWorkerRuntimeStore(config=PostgresTaskWorkerStoreConfig(dsn=core_dsn))
    await store.open()
    req = request()
    usage = TaskWorkerUsage(reserved_tokens=2048, reserved_cost_microusd=2500, complete=False)
    await store.create(_snapshot(req, usage=usage))
    await store.aclose()
    with psycopg.connect(admin_dsn) as connection:
        records = []
        for index in range(1001):
            prior = replace(req, worker_id=f"worker:terminal:{index}")
            result = TaskWorkerResult(
                prior.worker_id,
                prior.parent_trace_ref,
                TaskWorkerStatus.ABSTAINED,
                "No selected evidence.",
                (),
                (),
                TaskWorkerUsage(),
                "worker_abstained",
                NOW,
                NOW + timedelta(seconds=1),
            )
            records.append(
                (
                    prior.worker_id,
                    prior.parent_trace_ref,
                    prior.cancellation_owner,
                    result.status.value,
                    Jsonb(_request_to_dict(prior)),
                    Jsonb(_capabilities_to_dict(AttenuatedCapabilities(frozenset()))),
                    Jsonb(_usage_to_dict(result.usage)),
                    Jsonb(_result_to_dict(result)),
                    NOW,
                    result.finished_at,
                )
            )
        connection.cursor().executemany(
            "INSERT INTO task_worker_run "
            "(worker_id,parent_trace_ref,cancellation_owner,status,request,"
            "capabilities,usage,result,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            records,
        )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: pytest.fail("recovery cannot call a model"))
    ) as client:
        binding = await _binding(core_dsn, client)
        try:
            replay = await binding.runtime.run(req, parent_visible_tools=frozenset())
            assert replay.status is TaskWorkerStatus.FAILED
            assert replay.terminal_reason == "runtime_restart_interrupted"
            assert replay.usage == usage
            assert await binding.store.get(req.worker_id, owner="person:other") is None
            assert await binding.store.list(owner="person:other") == ()
            assert [event.kind for event in await binding.store.events(req.worker_id)] == [
                "worker.failed"
            ]
        finally:
            await binding.aclose()


async def test_competing_runtime_is_rejected_and_cannot_recover_live_work(database):
    _, dsn = database
    async with httpx.AsyncClient() as client:
        binding = await _binding(dsn, client)
        try:
            await binding.store.create(_snapshot(request()))
            with pytest.raises(RuntimeError, match="another Core runtime"):
                await _binding(dsn, client)
            assert (await binding.store.get("worker:one")).status is TaskWorkerStatus.RUNNING
            await binding.store.assert_lease()
        finally:
            await binding.aclose()


@pytest.mark.parametrize("impersonate", [False, True])
async def test_runtime_rejects_admin_and_set_role_impersonation(database, impersonate):
    admin, _ = database
    dsn = make_conninfo(admin, options="-c role=fdai_core") if impersonate else admin
    store = PostgresTaskWorkerRuntimeStore(config=PostgresTaskWorkerStoreConfig(dsn=dsn))
    with pytest.raises(RuntimeError, match="fdai_core"):
        await store.open()
    assert store._lease is None


@pytest.mark.parametrize("missing", ["worker", "inventory", "overlay", "update"])
async def test_missing_schema_or_update_grant_fails_enabled_startup(database, missing):
    admin, dsn = database
    with psycopg.connect(admin) as connection:
        if missing == "worker":
            connection.execute("DROP TABLE task_worker_event")
        elif missing == "inventory":
            connection.execute("DROP TABLE inventory_active")
        elif missing == "overlay":
            connection.execute("DROP TABLE inventory_realtime_resource")
        else:
            connection.execute("REVOKE UPDATE ON task_worker_run FROM fdai_core")
    async with httpx.AsyncClient() as client:
        with pytest.raises((psycopg.errors.UndefinedTable, RuntimeError)):
            await _binding(dsn, client)


async def test_paid_cancellation_reservation_survives_actual_runtime_reopen(database):
    _, dsn = database
    entered, pending = asyncio.Event(), asyncio.Event()
    calls = []
    identity = type("Identity", (), {})()
    identity.get_token = AsyncMock(
        return_value=IdentityToken("synthetic", NOW + timedelta(hours=1), "scope")
    )

    async def handler(req):
        calls.append(req)
        entered.set()
        await pending.wait()
        raise AssertionError("cancelled request must not complete")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        binding = await _binding(dsn, client, identity=identity)
        task = await binding.runtime.start(request(), parent_visible_tools=frozenset())
        await entered.wait()
        row = await binding.store.get("worker:one")
        assert row is not None and not row.usage.complete and row.usage.reserved_tokens > 0
        await binding.runtime.cancel("worker:one", owner="person:one")
        result = await task
        assert result.status is TaskWorkerStatus.CANCELLED
        await binding.aclose()
        reopened = await _binding(dsn, client, identity=identity)
        try:
            assert await reopened.runtime.run(request(), parent_visible_tools=frozenset()) == result
            assert not result.usage.complete and result.usage.reserved_cost_microusd > 0
            assert len(calls) == 1
        finally:
            await reopened.aclose()


async def test_terminal_event_failure_rolls_back_success_without_refunding_usage(database):
    admin, dsn = database
    with psycopg.connect(admin) as connection:
        connection.execute("""CREATE FUNCTION reject_terminal_event()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.kind='worker.succeeded' THEN
                RAISE EXCEPTION 'synthetic terminal event failure';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER reject_terminal BEFORE INSERT ON task_worker_event
        FOR EACH ROW EXECUTE FUNCTION reject_terminal_event();""")
    store = PostgresTaskWorkerRuntimeStore(config=PostgresTaskWorkerStoreConfig(dsn=dsn))
    await store.open()
    try:
        req = request()
        usage = TaskWorkerUsage(tokens=80, cost_microusd=100)
        await store.create(_snapshot(req, usage=usage))
        result = TaskWorkerResult(
            req.worker_id,
            req.parent_trace_ref,
            TaskWorkerStatus.SUCCEEDED,
            "Recorded fact.",
            ("evidence:one",),
            (),
            usage,
            "completed",
            NOW,
            NOW + timedelta(seconds=1),
        )
        with pytest.raises(psycopg.errors.RaiseException, match="synthetic terminal event"):
            await store.finish(result)
        row = await store.get(req.worker_id)
        assert row is not None and row.status is TaskWorkerStatus.RUNNING and row.result is None
        assert row.usage == usage and await store.events(req.worker_id) == ()
    finally:
        await store.aclose()


@pytest.mark.parametrize(
    "evidence_state",
    ["fresh", "missing", "stale", "future", "expected", "pending", "newer_failure", "nontext"],
)
async def test_production_registry_reads_real_recorded_state(database, evidence_state):
    admin, dsn = database
    with psycopg.connect(admin) as connection:
        connection.execute(
            "INSERT INTO inventory_snapshot "
            "(id,source,observation_kind,status,started_at,completed_at,scopes,resource_types) "
            "VALUES ('snapshot:one','synthetic','observed','active',NOW(),NOW(),'[]','[]')"
        )
        connection.execute(
            "INSERT INTO inventory_snapshot_resource "
            "(snapshot_id,resource_id,resource_type,props) VALUES "
            "('snapshot:one','resource:one','Compute',%s)",
            (Jsonb({"name": "example-vm", "state": "running"}),),
        )
        connection.execute(
            "INSERT INTO inventory_active(singleton,snapshot_id) VALUES (TRUE,'snapshot:one')"
        )
        if evidence_state == "missing":
            connection.execute("DELETE FROM inventory_snapshot_resource")
        elif evidence_state == "stale":
            connection.execute("UPDATE inventory_snapshot SET completed_at=NOW()-INTERVAL '2 days'")
        elif evidence_state == "future":
            connection.execute(
                "UPDATE inventory_snapshot SET completed_at=NOW()+INTERVAL '1 minute'"
            )
        elif evidence_state == "expected":
            connection.execute("UPDATE inventory_snapshot SET observation_kind='expected'")
        elif evidence_state == "pending":
            connection.execute(
                "INSERT INTO inventory_realtime_resource "
                "(resource_id,resource_type,change_kind,observed_at,event_id,idempotency_key) "
                "VALUES ('resource:one','Compute','delete',NOW(),'event:one','key:one')"
            )
        elif evidence_state == "newer_failure":
            connection.execute(
                "INSERT INTO inventory_snapshot "
                "(id,source,observation_kind,status,started_at,scopes,resource_types) "
                "VALUES ('snapshot:failed','synthetic','observed','failed', "
                "NOW()+INTERVAL '1 second','[]','[]')"
            )
        elif evidence_state == "nontext":
            connection.execute(
                "UPDATE inventory_snapshot_resource SET props=%s",
                (Jsonb({"name": "example-vm", "state": False}),),
            )
    async with httpx.AsyncClient() as client:
        binding = await _binding(dsn, client)
        try:
            tool = next(
                item for item in binding.runtime._tools if item.name == "get_resource_state"
            )
            result = await tool.call({"resource_ref": "resource:one"})
            if evidence_state == "fresh":
                assert dict(result.data)["state_0"] == "running"
                assert result.evidence_refs == ("inventory-snapshot:snapshot:one",)
            else:
                assert dict(result.data) == {"status": "unavailable"}
                assert not result.evidence_refs
        finally:
            await binding.aclose()


async def test_lost_lease_cannot_reacquire_or_rerun_uncertain_work(database):
    _, dsn = database
    async with httpx.AsyncClient() as client:
        binding = await _binding(dsn, client)
        usage = TaskWorkerUsage(reserved_tokens=2048, reserved_cost_microusd=2500, complete=False)
        await binding.store.create(_snapshot(request(), usage=usage))
        await binding.store._lease.close()
        with pytest.raises(RuntimeError, match="lease is unavailable"):
            await binding.store.get("worker:one")
        with pytest.raises(RuntimeError, match="lease is unavailable"):
            await binding.aclose()
        assert binding.store._lease is None
        reopened = await _binding(dsn, client)
        try:
            result = await reopened.runtime.run(request(), parent_visible_tools=frozenset())
            assert result.status is TaskWorkerStatus.FAILED
            assert result.terminal_reason == "runtime_restart_interrupted"
            assert result.usage == usage
        finally:
            await reopened.aclose()
