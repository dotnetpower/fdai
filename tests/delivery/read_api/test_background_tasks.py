from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request

from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskCoordinator,
    BackgroundTaskCoordinatorConfig,
    BackgroundTaskResult,
    BackgroundTaskService,
    BackgroundTaskUsage,
    InMemoryBackgroundTaskStore,
    ProgressCallback,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.delivery.read_api.routes.background_tasks import (
    BackgroundTaskRoutesConfig,
    make_background_task_routes,
)


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append(self, event: dict[str, object]) -> None:
        self.events.append(event)


class _Executor:
    async def execute(
        self,
        *,
        task: BackgroundTask,  # noqa: ARG002 - fixture returns one deterministic result
        progress: ProgressCallback,
    ) -> BackgroundTaskResult:
        await progress("investigation.started", "Started.", BackgroundTaskUsage())
        now = datetime.now(UTC)
        return BackgroundTaskResult(
            summary="Completed.",
            evidence_refs=(),
            terminal_reason="completed",
            usage=BackgroundTaskUsage(tokens=5),
            started_at=now,
            finished_at=now,
        )


async def _client(principal: Principal) -> tuple[AsyncClient, InMemoryBackgroundTaskStore, _Audit]:
    store = InMemoryBackgroundTaskStore()
    audit = _Audit()
    coordinator = BackgroundTaskCoordinator(
        store=store,
        executor=_Executor(),
        config=BackgroundTaskCoordinatorConfig(coordinator_id="test-coordinator"),
    )

    async def authorize(_request: Request) -> Principal:
        return principal

    app = Starlette(
        routes=list(
            make_background_task_routes(
                config=BackgroundTaskRoutesConfig(
                    service=BackgroundTaskService(store=store, audit=audit),
                    store=store,
                    coordinator=coordinator,
                ),
                authorize_principal=authorize,
            )
        )
    )
    return (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test"),
        store,
        audit,
    )


def _body() -> dict[str, object]:
    return {
        "prompt": "Inspect bounded evidence.",
        "conversation_id": "conversation-one",
        "channel_kind": "web",
        "channel_id": "channel-one",
        "idempotency_key": "background-idempotency-one",
        "correlation_id": "correlation-one",
    }


async def test_create_returns_immediately_and_task_completes_out_of_band() -> None:
    client, store, audit = await _client(
        Principal(oid="operator-one", roles=frozenset({Role.CONTRIBUTOR}))
    )
    async with client:
        response = await client.post("/background-tasks", json=_body())
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        assert response.json()["status"] == "queued"
        for _ in range(20):
            await asyncio.sleep(0)
            loaded = await store.get(task_id)
            if loaded is not None and loaded.result is not None:
                break
        detail = await client.get(f"/background-tasks/{task_id}")
        progress = await client.get(f"/background-tasks/{task_id}/progress")
        stream = await client.get(f"/background-tasks/{task_id}/progress/stream")

    assert detail.status_code == 200
    assert detail.json()["status"] == "succeeded"
    assert detail.json()["result"]["trusted"] is False
    assert progress.json()["progress"][0]["kind"] == "investigation.started"
    assert "event: progress" in stream.text
    assert "event: terminal" in stream.text
    assert audit.events[0]["action_kind"] == "background-task.created"


async def test_reader_cannot_create_and_cross_owner_is_hidden() -> None:
    contributor, store, _ = await _client(
        Principal(oid="operator-one", roles=frozenset({Role.CONTRIBUTOR}))
    )
    async with contributor:
        created = await contributor.post("/background-tasks", json=_body())
        task_id = created.json()["task_id"]
    reader, _, _ = await _client(Principal(oid="reader-one", roles=frozenset({Role.READER})))
    async with reader:
        denied = await reader.post("/background-tasks", json=_body())
    assert denied.status_code == 403

    async def authorize_other(_request: Request) -> Principal:
        return Principal(oid="operator-two", roles=frozenset({Role.CONTRIBUTOR}))

    coordinator = BackgroundTaskCoordinator(
        store=store,
        executor=_Executor(),
        config=BackgroundTaskCoordinatorConfig(coordinator_id="other-coordinator"),
    )
    app = Starlette(
        routes=list(
            make_background_task_routes(
                config=BackgroundTaskRoutesConfig(
                    service=BackgroundTaskService(store=store, audit=_Audit()),
                    store=store,
                    coordinator=coordinator,
                ),
                authorize_principal=authorize_other,
            )
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        hidden = await other.get(f"/background-tasks/{task_id}")
        hidden_cancel = await other.post(f"/background-tasks/{task_id}/cancel")
    assert hidden.status_code == 404
    assert hidden_cancel.status_code == 404
