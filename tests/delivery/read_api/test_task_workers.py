from __future__ import annotations

from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request

from fdai.core.task_worker import (
    AttenuatedCapabilities,
    InMemoryTaskWorkerStore,
    TaskWorkerBudget,
    TaskWorkerRequest,
    TaskWorkerSnapshot,
    TaskWorkerStatus,
    TaskWorkerUsage,
)
from fdai.delivery.read_api.routes.task_workers import make_task_worker_routes


def _snapshot(worker_id: str, owner: str) -> TaskWorkerSnapshot:
    now = datetime(2026, 7, 20, tzinfo=UTC)
    return TaskWorkerSnapshot(
        request=TaskWorkerRequest(
            worker_id=worker_id,
            parent_trace_ref="trace:parent",
            cancellation_owner=owner,
            goal="private investigation body",
            evidence_refs=("evidence:one",),
            constraints=("read only",),
            requested_tools=frozenset({"read_inventory", "mutate_resource"}),
            budget=TaskWorkerBudget(),
            created_at=now,
        ),
        capabilities=AttenuatedCapabilities(
            allowed_tools=frozenset({"read_inventory"}),
            denied_tools=("mutate_resource",),
        ),
        status=TaskWorkerStatus.RUNNING,
        usage=TaskWorkerUsage(tokens=20, cost_microusd=30, tool_calls=1),
        updated_at=now,
        heartbeat_at=now,
    )


async def _client(store: InMemoryTaskWorkerStore, owner: str) -> AsyncClient:
    async def authorize(_request: Request) -> str:
        return owner

    app = Starlette(routes=list(make_task_worker_routes(store=store, authorize=authorize)))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_worker_projection_is_get_only_bounded_and_metadata_only() -> None:
    store = InMemoryTaskWorkerStore()
    await store.create(_snapshot("worker-one", "operator-one"))
    await store.append_event(
        "worker-one",
        kind="worker.started",
        at=datetime(2026, 7, 20, tzinfo=UTC),
        details=(("allowed_tools", "1"),),
    )

    async with await _client(store, "operator-one") as client:
        listed = await client.get("/task-workers")
        detail = await client.get("/task-workers/worker-one")
        events = await client.get("/task-workers/worker-one/events")
        rejected = await client.post("/task-workers")

    assert listed.status_code == 200
    worker = listed.json()["workers"][0]
    assert worker["status"] == "running"
    assert worker["heartbeat_at"] is not None
    assert worker["tools"] == {
        "requested": ["mutate_resource", "read_inventory"],
        "allowed": ["read_inventory"],
        "denied": ["mutate_resource"],
    }
    assert "goal" not in worker
    assert "constraints" not in worker
    assert detail.status_code == 200
    assert events.json()["events"][0]["kind"] == "worker.started"
    assert rejected.status_code == 405


async def test_worker_projection_hides_other_owner_and_validates_limits() -> None:
    store = InMemoryTaskWorkerStore()
    await store.create(_snapshot("worker-secret", "operator-two"))

    async with await _client(store, "operator-one") as client:
        listed = await client.get("/task-workers")
        detail = await client.get("/task-workers/worker-secret")
        events = await client.get("/task-workers/worker-secret/events")
        bad_limit = await client.get("/task-workers?limit=0")

    assert listed.json() == {"workers": []}
    assert detail.status_code == 404
    assert events.status_code == 404
    assert bad_limit.status_code == 400
