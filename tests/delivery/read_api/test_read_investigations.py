from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch
from starlette.applications import Starlette
from starlette.requests import Request

from fdai.core.background_task import BackgroundTaskService, InMemoryBackgroundTaskStore
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.core.read_investigation import (
    PlanLatencyEstimate,
    ReadInvestigationBudget,
    ReadInvestigationProgressKind,
    ReadInvestigationRequest,
    ReadInvestigationService,
    plan_read_investigation,
)
from fdai.delivery.read_api.routes import read_investigations as read_investigation_routes
from fdai.delivery.read_api.routes.background_tasks import BackgroundTaskRoutesConfig
from fdai.delivery.read_api.routes.read_investigations import (
    ReadInvestigationRoutesConfig,
    _stream,
    make_read_investigation_routes,
)
from fdai.shared.providers.read_investigation import (
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceAttempt,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ReadInvestigationIntent,
    ReadLatencySample,
    ReadToolId,
    ResolvedResource,
    ResourceResolution,
    ResourceResolutionAttempt,
    ResourceResolutionStatus,
    ResourceSelector,
)
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt

NOW = datetime(2026, 7, 22, tzinfo=UTC)


class _Audit:
    async def append(self, event: dict[str, object]) -> None:
        del event


class _Coordinator:
    def __init__(self) -> None:
        self.wakes = 0

    def wake(self) -> None:
        self.wakes += 1


class _LatencyStore:
    def __init__(self, *, measured: bool) -> None:
        self.measured = measured
        self.appended: list[ReadLatencySample] = []

    async def append(self, sample: ReadLatencySample) -> None:
        self.appended.append(sample)

    async def recent(
        self,
        *,
        tool_id: ReadToolId,
        transport: str,
        operation_class: str,
        limit: int,
    ) -> tuple[ReadLatencySample, ...]:
        del limit
        if not self.measured:
            return ()
        return tuple(
            ReadLatencySample(
                tool_id=tool_id,
                transport=transport,
                operation_class=operation_class,
                succeeded=True,
                queue_duration_ms=0,
                execution_duration_ms=100,
                recorded_at=NOW,
            )
            for _ in range(20)
        )


class _Provider:
    transport = "rest"

    def __init__(self) -> None:
        self.calls: list[ReadToolId] = []

    async def resolve_resource(self, selector, *, limits):  # type: ignore[no-untyped-def]
        del limits
        self.calls.append(ReadToolId.RESOLVE_RESOURCE)
        resource = ResolvedResource(
            resource_ref="resource:opaque",
            scope_ref=selector.scope_ref,
            name=selector.name,
            resource_type="compute.vm",
        )
        return ResourceResolutionAttempt(
            ResourceResolution(ResourceResolutionStatus.MATCHED, resource=resource),
            _receipt(ReadToolId.RESOLVE_RESOURCE, "resource_resolution"),
        )

    async def get_resource_state(self, resource, *, limits):  # type: ignore[no-untyped-def]
        del limits
        self.calls.append(ReadToolId.GET_RESOURCE_STATE)
        record = ReadEvidenceRecord(
            occurred_at=NOW,
            status="observed",
            state="stopped",
        )
        return ReadEvidenceAttempt(
            ReadToolId.GET_RESOURCE_STATE,
            ReadEvidenceEnvelope(
                status=EvidenceStatus.MATCHED,
                authority="azure.resource_state",
                resource_ref=resource.resource_ref,
                observed_at=NOW,
                freshness=EvidenceFreshness.LIVE,
                truncated=False,
                records=(record,),
                evidence_refs=("evidence:opaque",),
            ),
            _receipt(ReadToolId.GET_RESOURCE_STATE, "resource_state", result_count=1),
        )

    async def query_resource_activity(self, resource, **kwargs):  # type: ignore[no-untyped-def]
        del resource, kwargs
        self.calls.append(ReadToolId.QUERY_RESOURCE_ACTIVITY)
        raise AssertionError("multi-source request should detach before cloud I/O")

    async def query_resource_health(self, resource, **kwargs):  # type: ignore[no-untyped-def]
        del resource, kwargs
        self.calls.append(ReadToolId.QUERY_RESOURCE_HEALTH)
        raise AssertionError("multi-source request should detach before cloud I/O")

    async def query_guest_shutdown_events(self, resource, **kwargs):  # type: ignore[no-untyped-def]
        del resource, kwargs
        self.calls.append(ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS)
        raise AssertionError("multi-source request should detach before cloud I/O")


def _receipt(
    tool_id: ReadToolId,
    operation_class: str,
    *,
    result_count: int = 0,
) -> ToolCallReceipt:
    return ToolCallReceipt(
        outcome=ToolCallOutcome.SUCCEEDED,
        receipt_ref=f"receipt:{tool_id.value}",
        tool_id=tool_id.value,
        transport="rest",
        operation_class=operation_class,
        execution_duration_ms=100,
        result_count=result_count,
        recorded_at=NOW,
        trace_ref="trace:one",
    )


async def _client(*, measured: bool, role: Role = Role.CONTRIBUTOR):
    provider = _Provider()
    latency = _LatencyStore(measured=measured)
    background_store = InMemoryBackgroundTaskStore()
    coordinator = _Coordinator()

    async def authorize(_request: Request) -> Principal:
        return Principal(oid="principal:one", roles=frozenset({role}))

    background = BackgroundTaskRoutesConfig(
        service=BackgroundTaskService(store=background_store, audit=_Audit()),
        store=background_store,
        coordinator=coordinator,  # type: ignore[arg-type]
    )
    config = ReadInvestigationRoutesConfig(
        service=ReadInvestigationService(provider, clock=lambda: NOW, latency_store=latency),
        latency_store=latency,
        background=background,
        scope_ref="scope:allowed",
    )
    app = Starlette(
        routes=list(
            make_read_investigation_routes(
                config=config,
                authorize_principal=authorize,
            )
        )
    )
    return (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test"),
        provider,
        coordinator,
    )


def _body(intent: str) -> dict[str, object]:
    return {
        "intent": intent,
        "resource_name": "vm-01",
        "conversation_id": "conversation:one",
        "correlation_id": "correlation:one",
        "idempotency_key": f"request:{intent}",
        "channel_kind": "web",
        "channel_id": "channel:one",
        "message_id": "message:one",
    }


async def test_measured_fast_investigation_runs_direct() -> None:
    client, provider, _ = await _client(measured=True)
    async with client:
        response = await client.post("/read-investigations", json=_body("resource_state"))
    assert response.status_code == 200
    assert response.json()["mode"] == "direct"
    assert response.json()["result"]["outcome"] == "matched"
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]


async def test_cold_single_source_investigation_streams_semantic_progress() -> None:
    client, provider, _ = await _client(measured=False)
    async with client:
        response = await client.post("/read-investigations", json=_body("resource_state"))
    assert response.status_code == 200
    assert "event: progress" in response.text
    assert "event: terminal" in response.text
    assert '"mode": "streamed"' in response.text
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]


async def test_multi_source_investigation_detaches_before_cloud_io() -> None:
    client, provider, coordinator = await _client(measured=True)
    async with client:
        response = await client.post(
            "/read-investigations",
            json=_body("change_attribution"),
        )
    assert response.status_code == 202
    assert response.json()["mode"] == "detached"
    assert provider.calls == []
    assert coordinator.wakes == 1


async def test_reader_cannot_start_investigation() -> None:
    client, provider, _ = await _client(measured=True, role=Role.READER)
    async with client:
        response = await client.post("/read-investigations", json=_body("resource_state"))
    assert response.status_code == 403
    assert provider.calls == []


async def test_invalid_budget_returns_400_before_cloud_io() -> None:
    client, provider, _ = await _client(measured=True)
    body = _body("resource_state")
    body["budget"] = {"max_tool_calls": 6}
    async with client:
        response = await client.post("/read-investigations", json=body)
    assert response.status_code == 400
    assert "max_tool_calls" in response.text
    assert provider.calls == []


async def test_stream_heartbeat_precedes_terminal_without_restarting_provider(
    monkeypatch: MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class _SlowProvider(_Provider):
        def __init__(self) -> None:
            super().__init__()
            self.resolve_calls = 0

        async def resolve_resource(self, selector, *, limits):  # type: ignore[no-untyped-def]
            self.resolve_calls += 1
            started.set()
            await release.wait()
            return await super().resolve_resource(selector, limits=limits)

    provider = _SlowProvider()
    plan = plan_read_investigation(
        ReadInvestigationRequest(
            requester_ref="principal:one",
            conversation_ref="conversation:one",
            correlation_ref="correlation:one",
            intent=ReadInvestigationIntent.RESOURCE_STATE,
            selector=ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
            lookback_seconds=3_600,
            requested_evidence=(),
            budget=ReadInvestigationBudget(),
            idempotency_key="request:stream-heartbeat",
            created_at=NOW,
        )
    )
    monkeypatch.setattr(
        read_investigation_routes,
        "_SSE_HEARTBEAT_INTERVAL_SECONDS",
        0.01,
    )
    response = _stream(
        ReadInvestigationService(
            provider,
            clock=lambda: NOW,
            latency_store=_LatencyStore(measured=False),
        ),
        plan,
        estimate=PlanLatencyEstimate(2_000, 8_000, False, 0, False),
    )
    iterator = response.body_iterator
    frames = []

    while ": heartbeat\n\n" not in frames:
        frames.append(await asyncio.wait_for(anext(iterator), timeout=0.5))

    assert started.is_set()
    assert provider.resolve_calls == 1
    release.set()
    frames.extend([frame async for frame in iterator])

    heartbeat_indexes = [index for index, frame in enumerate(frames) if frame == ": heartbeat\n\n"]
    terminal_indexes = [index for index, frame in enumerate(frames) if "event: terminal" in frame]
    assert heartbeat_indexes
    assert terminal_indexes == [len(frames) - 1]
    assert max(heartbeat_indexes) < terminal_indexes[0]
    assert provider.resolve_calls == 1
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]


async def test_stream_close_cancels_inflight_investigation() -> None:
    cancelled = asyncio.Event()

    class _SlowService:
        async def execute(self, plan, *, progress_observer):  # type: ignore[no-untyped-def]
            del plan
            await progress_observer(ReadInvestigationProgressKind.PLANNED)
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    plan = plan_read_investigation(
        ReadInvestigationRequest(
            requester_ref="principal:one",
            conversation_ref="conversation:one",
            correlation_ref="correlation:one",
            intent=ReadInvestigationIntent.RESOURCE_STATE,
            selector=ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
            lookback_seconds=3_600,
            requested_evidence=(),
            budget=ReadInvestigationBudget(),
            idempotency_key="request:stream-close",
            created_at=NOW,
        )
    )
    response = _stream(
        _SlowService(),  # type: ignore[arg-type]
        plan,
        estimate=PlanLatencyEstimate(2_000, 8_000, False, 0, False),
    )
    iterator = response.body_iterator

    first = await anext(iterator)
    assert "investigation.planned" in first
    await iterator.aclose()

    assert cancelled.is_set()
