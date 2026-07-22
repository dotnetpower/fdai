from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch, raises
from starlette.applications import Starlette
from starlette.requests import Request

from fdai.core.background_task import BackgroundTaskService, InMemoryBackgroundTaskStore
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.core.read_investigation import (
    MAX_READ_INVESTIGATION_ATTEMPTS,
    InMemoryReadInvestigationRunStore,
    PlanLatencyEstimate,
    ReadInvestigationBudget,
    ReadInvestigationProgressKind,
    ReadInvestigationRequest,
    ReadInvestigationResult,
    ReadInvestigationRunConflictError,
    ReadInvestigationRunMode,
    ReadInvestigationRunRecord,
    ReadInvestigationRunState,
    ReadInvestigationRunUsage,
    ReadInvestigationService,
    plan_read_investigation,
)
from fdai.delivery.read_api.routes import read_investigations as read_investigation_routes
from fdai.delivery.read_api.routes.background_tasks import BackgroundTaskRoutesConfig
from fdai.delivery.read_api.routes.read_investigations import (
    ReadInvestigationRoutesConfig,
    ReadInvestigationRunLedgerConfig,
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


class _MutableClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


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
    run_store = InMemoryReadInvestigationRunStore()
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
        run_store=run_store,
        latency_store=latency,
        background=background,
        scope_ref="scope:allowed",
        clock=lambda: NOW,
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
        run_store,
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
    client, provider, _, _ = await _client(measured=True)
    async with client:
        response = await client.post("/read-investigations", json=_body("resource_state"))
    assert response.status_code == 200
    assert response.json()["mode"] == "direct"
    assert response.json()["result"]["outcome"] == "matched"
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]


async def test_cold_single_source_investigation_streams_semantic_progress() -> None:
    client, provider, _, _ = await _client(measured=False)
    async with client:
        response = await client.post("/read-investigations", json=_body("resource_state"))
    assert response.status_code == 200
    assert "event: progress" in response.text
    assert "event: terminal" in response.text
    assert '"mode": "streamed"' in response.text
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]


async def test_multi_source_investigation_detaches_before_cloud_io() -> None:
    client, provider, coordinator, _ = await _client(measured=True)
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
    client, provider, _, _ = await _client(measured=True, role=Role.READER)
    async with client:
        response = await client.post("/read-investigations", json=_body("resource_state"))
    assert response.status_code == 403
    assert provider.calls == []


async def test_invalid_budget_returns_400_before_cloud_io() -> None:
    client, provider, _, _ = await _client(measured=True)
    body = _body("resource_state")
    body["budget"] = {"max_tool_calls": 6}
    async with client:
        response = await client.post("/read-investigations", json=body)
    assert response.status_code == 400
    assert "max_tool_calls" in response.text
    assert provider.calls == []


async def test_direct_replay_returns_header_and_skips_provider_recall() -> None:
    client, provider, _, run_store = await _client(measured=True)
    body = _body("resource_state")
    async with client:
        first = await client.post("/read-investigations", json=body)
        second = await client.post("/read-investigations", json=body)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers.get("X-FDAI-Read-Investigation-Replay") == "1"
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]
    run = await run_store.get(
        owner_principal_id="principal:one",
        idempotency_key=str(body["idempotency_key"]),
    )
    assert run is not None and run.usage is not None
    assert run.usage.reserved_cost_microusd == 100_000
    assert run.usage.measured_cost_microusd is None


async def test_direct_executor_rejects_requester_mismatch_before_store_io() -> None:
    request = read_investigation_routes._request(
        _body("resource_state"),
        principal=Principal(oid="principal:one", roles=frozenset({Role.CONTRIBUTOR})),
        scope_ref="scope:allowed",
    )
    executor = read_investigation_routes.IdempotentReadInvestigationExecutor(
        None  # type: ignore[arg-type]
    )

    with raises(
        read_investigation_routes.ReadInvestigationRunRejectedError,
        match="requester does not match",
    ):
        await executor.execute(
            plan_read_investigation(request),
            owner_principal_id="principal:two",
        )


async def test_run_usage_sums_cost_only_when_every_receipt_is_measured() -> None:
    client, _, _, run_store = await _client(measured=True)
    body = _body("resource_state")
    async with client:
        response = await client.post("/read-investigations", json=body)
    assert response.status_code == 200
    run = await run_store.get(
        owner_principal_id="principal:one",
        idempotency_key=str(body["idempotency_key"]),
    )
    assert run is not None and run.result is not None

    measured_result = replace(
        run.result,
        receipts=tuple(
            replace(receipt, cost_microusd=100 + index)
            for index, receipt in enumerate(run.result.receipts)
        ),
    )
    measured = read_investigation_routes._run_usage(
        request=run.request,
        result=measured_result,
        execution_duration_ms=200,
    )
    partial = read_investigation_routes._run_usage(
        request=run.request,
        result=replace(
            measured_result,
            receipts=(replace(measured_result.receipts[0], cost_microusd=None),)
            + measured_result.receipts[1:],
        ),
        execution_duration_ms=200,
    )

    assert measured.reserved_cost_microusd == 100_000
    assert measured.measured_cost_microusd == 201
    assert partial.measured_cost_microusd is None


async def test_stream_replay_emits_immediate_terminal_without_provider_recall() -> None:
    client, provider, _, _ = await _client(measured=False)
    body = _body("resource_state")
    async with client:
        first = await client.post("/read-investigations", json=body)
        second = await client.post("/read-investigations", json=body)
    assert first.status_code == 200
    assert second.status_code == 200
    assert "event: terminal" in second.text
    assert "event: progress" not in second.text
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]


async def test_active_inflight_request_returns_409_with_retry_after() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class _SlowProvider(_Provider):
        async def get_resource_state(self, resource, *, limits):  # type: ignore[no-untyped-def]
            started.set()
            await release.wait()
            return await super().get_resource_state(resource, limits=limits)

    provider = _SlowProvider()
    latency = _LatencyStore(measured=True)
    run_store = InMemoryReadInvestigationRunStore()
    background_store = InMemoryBackgroundTaskStore()
    coordinator = _Coordinator()

    async def authorize(_request: Request) -> Principal:
        return Principal(oid="principal:one", roles=frozenset({Role.CONTRIBUTOR}))

    config = ReadInvestigationRoutesConfig(
        service=ReadInvestigationService(provider, clock=lambda: NOW, latency_store=latency),
        run_store=run_store,
        latency_store=latency,
        background=BackgroundTaskRoutesConfig(
            service=BackgroundTaskService(store=background_store, audit=_Audit()),
            store=background_store,
            coordinator=coordinator,  # type: ignore[arg-type]
        ),
        scope_ref="scope:allowed",
        clock=lambda: NOW,
    )
    app = Starlette(
        routes=list(make_read_investigation_routes(config=config, authorize_principal=authorize))
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    body = _body("resource_state")

    async with client:
        first_task = asyncio.create_task(client.post("/read-investigations", json=body))
        await asyncio.wait_for(started.wait(), timeout=1.0)
        second = await client.post("/read-investigations", json=body)
        release.set()
        first = await first_task

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.headers.get("Retry-After") is not None
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]


async def test_same_key_with_different_payload_returns_409() -> None:
    client, provider, _, _ = await _client(measured=True)
    first = _body("resource_state")
    second = dict(first)
    second["lookback_seconds"] = 7_200
    async with client:
        first_response = await client.post("/read-investigations", json=first)
        second_response = await client.post("/read-investigations", json=second)
    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]


async def test_owner_isolation_allows_same_key_for_different_principals() -> None:
    provider = _Provider()
    latency = _LatencyStore(measured=True)
    run_store = InMemoryReadInvestigationRunStore()
    background_store = InMemoryBackgroundTaskStore()
    coordinator = _Coordinator()

    async def authorize(request: Request) -> Principal:
        owner = request.headers.get("x-owner", "principal:one")
        return Principal(oid=owner, roles=frozenset({Role.CONTRIBUTOR}))

    config = ReadInvestigationRoutesConfig(
        service=ReadInvestigationService(provider, clock=lambda: NOW, latency_store=latency),
        run_store=run_store,
        latency_store=latency,
        background=BackgroundTaskRoutesConfig(
            service=BackgroundTaskService(store=background_store, audit=_Audit()),
            store=background_store,
            coordinator=coordinator,  # type: ignore[arg-type]
        ),
        scope_ref="scope:allowed",
        clock=lambda: NOW,
    )
    app = Starlette(
        routes=list(make_read_investigation_routes(config=config, authorize_principal=authorize))
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    body = _body("resource_state")

    async with client:
        first = await client.post("/read-investigations", json=body, headers={"x-owner": "a"})
        second = await client.post("/read-investigations", json=body, headers={"x-owner": "b"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert provider.calls == [
        ReadToolId.RESOLVE_RESOURCE,
        ReadToolId.GET_RESOURCE_STATE,
        ReadToolId.RESOLVE_RESOURCE,
        ReadToolId.GET_RESOURCE_STATE,
    ]


async def test_service_failure_marks_failed_terminal_state() -> None:
    class _FailingService:
        transport = "rest"

        async def execute(self, plan, *, progress_observer=None):  # type: ignore[no-untyped-def]
            del plan, progress_observer
            raise RuntimeError("boom")

    run_store = InMemoryReadInvestigationRunStore()
    background_store = InMemoryBackgroundTaskStore()
    coordinator = _Coordinator()
    latency = _LatencyStore(measured=True)

    async def authorize(_request: Request) -> Principal:
        return Principal(oid="principal:one", roles=frozenset({Role.CONTRIBUTOR}))

    config = ReadInvestigationRoutesConfig(
        service=_FailingService(),  # type: ignore[arg-type]
        run_store=run_store,
        latency_store=latency,
        background=BackgroundTaskRoutesConfig(
            service=BackgroundTaskService(store=background_store, audit=_Audit()),
            store=background_store,
            coordinator=coordinator,  # type: ignore[arg-type]
        ),
        scope_ref="scope:allowed",
        clock=lambda: NOW,
    )
    app = Starlette(
        routes=list(make_read_investigation_routes(config=config, authorize_principal=authorize))
    )
    client = AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )
    body = _body("resource_state")

    async with client:
        response = await client.post("/read-investigations", json=body)

    run = await run_store.get(
        owner_principal_id="principal:one",
        idempotency_key=body["idempotency_key"],
    )
    assert response.status_code == 500
    assert run is not None
    assert run.state is ReadInvestigationRunState.FAILED
    assert run.failure_reason == "service_execution_failed"
    assert run.terminal_at == NOW


async def test_same_key_retry_after_transient_failure_reexecutes_once() -> None:
    provider = _Provider()
    latency = _LatencyStore(measured=True)
    run_store = InMemoryReadInvestigationRunStore()
    background_store = InMemoryBackgroundTaskStore()
    service = ReadInvestigationService(provider, clock=lambda: NOW, latency_store=latency)

    class _FlakyService:
        transport = "rest"

        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, plan, *, progress_observer=None):  # type: ignore[no-untyped-def]
            self.calls += 1
            result = await service.execute(plan, progress_observer=progress_observer)
            if self.calls == 1:
                raise RuntimeError("transient")
            return result

    flaky_service = _FlakyService()

    async def authorize(_request: Request) -> Principal:
        return Principal(oid="principal:one", roles=frozenset({Role.CONTRIBUTOR}))

    config = ReadInvestigationRoutesConfig(
        service=flaky_service,  # type: ignore[arg-type]
        run_store=run_store,
        latency_store=latency,
        background=BackgroundTaskRoutesConfig(
            service=BackgroundTaskService(store=background_store, audit=_Audit()),
            store=background_store,
            coordinator=_Coordinator(),  # type: ignore[arg-type]
        ),
        scope_ref="scope:allowed",
        clock=lambda: NOW,
    )
    app = Starlette(
        routes=list(make_read_investigation_routes(config=config, authorize_principal=authorize))
    )
    client = AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )
    body = _body("resource_state")

    async with client:
        first = await client.post("/read-investigations", json=body)
        second = await client.post("/read-investigations", json=body)

    run = await run_store.get(
        owner_principal_id="principal:one",
        idempotency_key=str(body["idempotency_key"]),
    )
    assert first.status_code == 500
    assert second.status_code == 200
    assert provider.calls == [
        ReadToolId.RESOLVE_RESOURCE,
        ReadToolId.GET_RESOURCE_STATE,
        ReadToolId.RESOLVE_RESOURCE,
        ReadToolId.GET_RESOURCE_STATE,
    ]
    assert run is not None
    assert run.state is ReadInvestigationRunState.COMPLETED
    assert run.attempt_count == 2


async def test_same_key_retry_after_expired_reexecutes_once() -> None:
    provider = _Provider()
    latency = _LatencyStore(measured=True)
    run_store = InMemoryReadInvestigationRunStore()
    background_store = InMemoryBackgroundTaskStore()
    body = _body("resource_state")
    seeded_request = ReadInvestigationRequest(
        requester_ref="principal:one",
        conversation_ref=str(body["conversation_id"]),
        correlation_ref=str(body["correlation_id"]),
        intent=ReadInvestigationIntent.RESOURCE_STATE,
        selector=ResourceSelector(name=str(body["resource_name"]), scope_ref="scope:allowed"),
        lookback_seconds=3_600,
        requested_evidence=(),
        budget=ReadInvestigationBudget(),
        idempotency_key=str(body["idempotency_key"]),
        created_at=NOW,
    )
    claimed, _ = await run_store.claim(
        owner_principal_id="principal:one",
        request=seeded_request,
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="read-api",
        lease_token="lease:seed",
        now=NOW,
        lease_seconds=1,
        retention_seconds=300,
    )
    await run_store.fail(
        owner_principal_id="principal:one",
        idempotency_key=seeded_request.idempotency_key,
        expected_revision=claimed.revision,
        lease_token="lease:seed",
        failure_reason="client_stream_disconnected",
        usage=ReadInvestigationRunUsage(tool_calls=0, execution_duration_ms=1),
        now=NOW,
        state=ReadInvestigationRunState.EXPIRED,
    )

    async def authorize(_request: Request) -> Principal:
        return Principal(oid="principal:one", roles=frozenset({Role.CONTRIBUTOR}))

    config = ReadInvestigationRoutesConfig(
        service=ReadInvestigationService(provider, clock=lambda: NOW, latency_store=latency),
        run_store=run_store,
        latency_store=latency,
        background=BackgroundTaskRoutesConfig(
            service=BackgroundTaskService(store=background_store, audit=_Audit()),
            store=background_store,
            coordinator=_Coordinator(),  # type: ignore[arg-type]
        ),
        scope_ref="scope:allowed",
        clock=lambda: NOW,
    )
    app = Starlette(
        routes=list(make_read_investigation_routes(config=config, authorize_principal=authorize))
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async with client:
        response = await client.post("/read-investigations", json=body)

    run = await run_store.get(
        owner_principal_id="principal:one",
        idempotency_key=seeded_request.idempotency_key,
    )
    assert response.status_code == 200
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]
    assert run is not None
    assert run.state is ReadInvestigationRunState.COMPLETED
    assert run.attempt_count == 2


async def test_concurrent_reclaim_runs_provider_once_and_loser_gets_409() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class _SlowProvider(_Provider):
        async def get_resource_state(self, resource, *, limits):  # type: ignore[no-untyped-def]
            started.set()
            await release.wait()
            return await super().get_resource_state(resource, limits=limits)

    provider = _SlowProvider()
    latency = _LatencyStore(measured=True)
    run_store = InMemoryReadInvestigationRunStore()
    background_store = InMemoryBackgroundTaskStore()
    body = _body("resource_state")
    seeded_request = ReadInvestigationRequest(
        requester_ref="principal:one",
        conversation_ref=str(body["conversation_id"]),
        correlation_ref=str(body["correlation_id"]),
        intent=ReadInvestigationIntent.RESOURCE_STATE,
        selector=ResourceSelector(name=str(body["resource_name"]), scope_ref="scope:allowed"),
        lookback_seconds=3_600,
        requested_evidence=(),
        budget=ReadInvestigationBudget(),
        idempotency_key=str(body["idempotency_key"]),
        created_at=NOW,
    )
    claimed, _ = await run_store.claim(
        owner_principal_id="principal:one",
        request=seeded_request,
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="read-api",
        lease_token="lease:seed",
        now=NOW,
        lease_seconds=30,
        retention_seconds=300,
    )
    await run_store.fail(
        owner_principal_id="principal:one",
        idempotency_key=seeded_request.idempotency_key,
        expected_revision=claimed.revision,
        lease_token="lease:seed",
        failure_reason="service_execution_failed",
        usage=ReadInvestigationRunUsage(tool_calls=0, execution_duration_ms=1),
        now=NOW,
    )

    async def authorize(_request: Request) -> Principal:
        return Principal(oid="principal:one", roles=frozenset({Role.CONTRIBUTOR}))

    config = ReadInvestigationRoutesConfig(
        service=ReadInvestigationService(provider, clock=lambda: NOW, latency_store=latency),
        run_store=run_store,
        latency_store=latency,
        background=BackgroundTaskRoutesConfig(
            service=BackgroundTaskService(store=background_store, audit=_Audit()),
            store=background_store,
            coordinator=_Coordinator(),  # type: ignore[arg-type]
        ),
        scope_ref="scope:allowed",
        clock=lambda: NOW,
    )
    app = Starlette(
        routes=list(make_read_investigation_routes(config=config, authorize_principal=authorize))
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async with client:
        first_task = asyncio.create_task(client.post("/read-investigations", json=body))
        await asyncio.wait_for(started.wait(), timeout=1.0)
        second = await client.post("/read-investigations", json=body)
        release.set()
        first = await first_task

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.headers.get("Retry-After") is not None
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]


async def test_exhausted_retry_returns_non_retryable_409() -> None:
    provider = _Provider()
    latency = _LatencyStore(measured=True)
    run_store = InMemoryReadInvestigationRunStore()
    background_store = InMemoryBackgroundTaskStore()
    body = _body("resource_state")
    seeded_request = ReadInvestigationRequest(
        requester_ref="principal:one",
        conversation_ref=str(body["conversation_id"]),
        correlation_ref=str(body["correlation_id"]),
        intent=ReadInvestigationIntent.RESOURCE_STATE,
        selector=ResourceSelector(name=str(body["resource_name"]), scope_ref="scope:allowed"),
        lookback_seconds=3_600,
        requested_evidence=(),
        budget=ReadInvestigationBudget(),
        idempotency_key=str(body["idempotency_key"]),
        created_at=NOW,
    )
    current, _ = await run_store.claim(
        owner_principal_id="principal:one",
        request=seeded_request,
        mode=ReadInvestigationRunMode.DIRECT,
        lease_owner="read-api",
        lease_token="lease:one",
        now=NOW,
        lease_seconds=30,
        retention_seconds=300,
    )
    for attempt in range(2, MAX_READ_INVESTIGATION_ATTEMPTS + 1):
        failed = await run_store.fail(
            owner_principal_id="principal:one",
            idempotency_key=seeded_request.idempotency_key,
            expected_revision=current.revision,
            lease_token=current.lease.token if current.lease is not None else "lease:unexpected",
            failure_reason=f"failed:{attempt}",
            usage=ReadInvestigationRunUsage(tool_calls=attempt, execution_duration_ms=attempt),
            now=NOW,
        )
        current = await run_store.reclaim(
            owner_principal_id="principal:one",
            idempotency_key=seeded_request.idempotency_key,
            request_digest=failed.request_digest,
            mode=ReadInvestigationRunMode.DIRECT,
            expected_revision=failed.revision,
            lease_owner="read-api",
            lease_token=f"lease:retry:{attempt}",
            now=NOW,
            lease_seconds=30,
            retention_seconds=300,
        )

    await run_store.fail(
        owner_principal_id="principal:one",
        idempotency_key=seeded_request.idempotency_key,
        expected_revision=current.revision,
        lease_token=current.lease.token if current.lease is not None else "lease:unexpected",
        failure_reason="terminal:max",
        usage=ReadInvestigationRunUsage(tool_calls=0, execution_duration_ms=0),
        now=NOW,
    )

    async def authorize(_request: Request) -> Principal:
        return Principal(oid="principal:one", roles=frozenset({Role.CONTRIBUTOR}))

    config = ReadInvestigationRoutesConfig(
        service=ReadInvestigationService(provider, clock=lambda: NOW, latency_store=latency),
        run_store=run_store,
        latency_store=latency,
        background=BackgroundTaskRoutesConfig(
            service=BackgroundTaskService(store=background_store, audit=_Audit()),
            store=background_store,
            coordinator=_Coordinator(),  # type: ignore[arg-type]
        ),
        scope_ref="scope:allowed",
        clock=lambda: NOW,
    )
    app = Starlette(
        routes=list(make_read_investigation_routes(config=config, authorize_principal=authorize))
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async with client:
        response = await client.post("/read-investigations", json=body)

    assert response.status_code == 409
    assert "exhausted" in response.text
    assert response.headers.get("Retry-After") is not None
    assert provider.calls == []


async def test_stream_disconnect_marks_terminal_without_leaking_running_lease() -> None:
    class _SlowService:
        transport = "rest"

        async def execute(self, plan, *, progress_observer=None):  # type: ignore[no-untyped-def]
            del plan
            if progress_observer is not None:
                await progress_observer(ReadInvestigationProgressKind.PLANNED)
            await asyncio.Future()

    run_store = InMemoryReadInvestigationRunStore()
    request = ReadInvestigationRequest(
        requester_ref="principal:one",
        conversation_ref="conversation:one",
        correlation_ref="correlation:one",
        intent=ReadInvestigationIntent.RESOURCE_STATE,
        selector=ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
        lookback_seconds=3_600,
        requested_evidence=(),
        budget=ReadInvestigationBudget(),
        idempotency_key="request:disconnect",
        created_at=NOW,
    )
    plan = plan_read_investigation(request)
    claimed, created = await run_store.claim(
        owner_principal_id="principal:one",
        request=request,
        mode=read_investigation_routes.ReadInvestigationRunMode.STREAMED,
        lease_owner="read-api",
        lease_token="lease:one",
        now=NOW,
        lease_seconds=30,
        retention_seconds=300,
    )
    assert created is True

    config = ReadInvestigationRoutesConfig(
        service=_SlowService(),  # type: ignore[arg-type]
        run_store=run_store,
        latency_store=_LatencyStore(measured=False),
        background=BackgroundTaskRoutesConfig(
            service=BackgroundTaskService(store=InMemoryBackgroundTaskStore(), audit=_Audit()),
            store=InMemoryBackgroundTaskStore(),
            coordinator=_Coordinator(),  # type: ignore[arg-type]
        ),
        scope_ref="scope:allowed",
        clock=lambda: NOW,
    )

    response = read_investigation_routes._stream_claimed(
        config=config,
        plan=plan,
        claimed=claimed,
        lease_token="lease:one",
        lease_seconds=30,
        lease_ceiling_at=NOW + timedelta(seconds=60),
        estimate=PlanLatencyEstimate(2_000, 8_000, False, 0, False),
    )
    iterator = response.body_iterator

    frame = await anext(iterator)
    assert "investigation.planned" in frame
    await iterator.aclose()

    run = await run_store.get(
        owner_principal_id="principal:one",
        idempotency_key=request.idempotency_key,
    )
    assert run is not None
    assert run.state is ReadInvestigationRunState.EXPIRED
    assert run.failure_reason == "client_stream_disconnected"
    assert run.lease is None


async def test_detached_same_payload_replays_existing_task_and_different_payload_409() -> None:
    client, provider, coordinator, _ = await _client(measured=True)
    body = _body("change_attribution")
    different = dict(body)
    different["resource_name"] = "vm-02"
    async with client:
        first = await client.post("/read-investigations", json=body)
        replay = await client.post("/read-investigations", json=body)
        conflict = await client.post("/read-investigations", json=different)

    assert first.status_code == 202
    assert replay.status_code == 200
    assert replay.json()["task_id"] == first.json()["task_id"]
    assert conflict.status_code == 409
    assert provider.calls == []
    assert coordinator.wakes == 1


async def test_detached_same_key_with_different_budget_returns_409() -> None:
    client, provider, coordinator, _ = await _client(measured=True)
    first = _body("change_attribution")
    different = dict(first)
    different["budget"] = {"max_cost_microusd": 200_000}

    async with client:
        created = await client.post("/read-investigations", json=first)
        conflict = await client.post("/read-investigations", json=different)

    assert created.status_code == 202
    assert conflict.status_code == 409
    assert provider.calls == []
    assert coordinator.wakes == 1


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
    latency = _LatencyStore(measured=False)
    run_store = InMemoryReadInvestigationRunStore()
    background_store = InMemoryBackgroundTaskStore()
    coordinator = _Coordinator()

    async def authorize(_request: Request) -> Principal:
        return Principal(oid="principal:one", roles=frozenset({Role.CONTRIBUTOR}))

    config = ReadInvestigationRoutesConfig(
        service=ReadInvestigationService(provider, clock=lambda: NOW, latency_store=latency),
        run_store=run_store,
        latency_store=latency,
        background=BackgroundTaskRoutesConfig(
            service=BackgroundTaskService(store=background_store, audit=_Audit()),
            store=background_store,
            coordinator=coordinator,  # type: ignore[arg-type]
        ),
        scope_ref="scope:allowed",
        clock=lambda: NOW,
    )
    app = Starlette(
        routes=list(make_read_investigation_routes(config=config, authorize_principal=authorize))
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    monkeypatch.setattr(
        read_investigation_routes,
        "_SSE_HEARTBEAT_INTERVAL_SECONDS",
        0.01,
    )
    async with client:
        request_task = asyncio.create_task(
            client.post("/read-investigations", json=_body("resource_state"))
        )
        await asyncio.wait_for(started.wait(), timeout=1.0)
        await asyncio.sleep(0.05)
        release.set()
        response = await request_task

    assert response.status_code == 200
    heartbeat_index = response.text.find(": heartbeat\n\n")
    terminal_index = response.text.find("event: terminal")
    assert heartbeat_index >= 0
    assert terminal_index > heartbeat_index
    assert provider.resolve_calls == 1
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]


async def test_long_execution_survives_renew_and_reconcile() -> None:
    class _LongProvider(_Provider):
        def __init__(self, *, clock: _MutableClock) -> None:
            super().__init__()
            self._clock = clock

        async def get_resource_state(self, resource, *, limits):  # type: ignore[no-untyped-def]
            for _ in range(80):
                await asyncio.sleep(0.02)
                self._clock.advance(0.03)
            return await super().get_resource_state(resource, limits=limits)

    clock = _MutableClock(NOW)
    provider = _LongProvider(clock=clock)
    latency = _LatencyStore(measured=True)
    run_store = InMemoryReadInvestigationRunStore()
    background_store = InMemoryBackgroundTaskStore()
    coordinator = _Coordinator()

    async def authorize(_request: Request) -> Principal:
        return Principal(oid="principal:one", roles=frozenset({Role.CONTRIBUTOR}))

    config = ReadInvestigationRoutesConfig(
        service=ReadInvestigationService(provider, clock=clock.now, latency_store=latency),
        run_store=run_store,
        latency_store=latency,
        background=BackgroundTaskRoutesConfig(
            service=BackgroundTaskService(store=background_store, audit=_Audit()),
            store=background_store,
            coordinator=coordinator,  # type: ignore[arg-type]
        ),
        scope_ref="scope:allowed",
        run_ledger=ReadInvestigationRunLedgerConfig(
            lease_seconds=2,
            lease_max_window_seconds=30,
            lease_budget_margin_seconds=5,
            renew_interval_seconds=0.2,
            retention_seconds=300,
        ),
        clock=clock.now,
    )
    app = Starlette(
        routes=list(make_read_investigation_routes(config=config, authorize_principal=authorize))
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    done = asyncio.Event()

    async def reconcile_loop() -> None:
        while not done.is_set():
            await run_store.reconcile_expired(now=clock.now(), limit=100)
            await asyncio.sleep(0.01)

    reconciler = asyncio.create_task(reconcile_loop())
    body = _body("resource_state")
    async with client:
        response = await client.post("/read-investigations", json=body)
    done.set()
    await asyncio.gather(reconciler, return_exceptions=True)

    run = await run_store.get(
        owner_principal_id="principal:one",
        idempotency_key=str(body["idempotency_key"]),
    )
    assert response.status_code == 200
    assert response.json()["result"]["outcome"] == "matched"
    assert run is not None
    assert run.state is ReadInvestigationRunState.COMPLETED
    assert run.lease is None
    assert run.revision > 2


class _CompleteConflictRunStore:
    def __init__(self, inner: InMemoryReadInvestigationRunStore) -> None:
        self._inner = inner

    async def claim(
        self,
        *,
        owner_principal_id: str,
        request: ReadInvestigationRequest,
        mode: ReadInvestigationRunMode,
        lease_owner: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        retention_seconds: int,
    ) -> tuple[ReadInvestigationRunRecord, bool]:
        return await self._inner.claim(
            owner_principal_id=owner_principal_id,
            request=request,
            mode=mode,
            lease_owner=lease_owner,
            lease_token=lease_token,
            now=now,
            lease_seconds=lease_seconds,
            retention_seconds=retention_seconds,
        )

    async def get(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
    ) -> ReadInvestigationRunRecord | None:
        return await self._inner.get(
            owner_principal_id=owner_principal_id,
            idempotency_key=idempotency_key,
        )

    async def start(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        now: datetime,
    ) -> ReadInvestigationRunRecord:
        return await self._inner.start(
            owner_principal_id=owner_principal_id,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
            lease_token=lease_token,
            now=now,
        )

    async def renew(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        lease_ceiling_at: datetime,
    ) -> ReadInvestigationRunRecord:
        return await self._inner.renew(
            owner_principal_id=owner_principal_id,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
            lease_token=lease_token,
            now=now,
            lease_seconds=lease_seconds,
            lease_ceiling_at=lease_ceiling_at,
        )

    async def complete(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        result: ReadInvestigationResult,
        usage: ReadInvestigationRunUsage,
        now: datetime,
    ) -> ReadInvestigationRunRecord:
        del owner_principal_id, idempotency_key, expected_revision, lease_token, result, usage, now
        raise ReadInvestigationRunConflictError("forced complete conflict")

    async def fail(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        failure_reason: str,
        usage: ReadInvestigationRunUsage,
        now: datetime,
        state: ReadInvestigationRunState = ReadInvestigationRunState.FAILED,
    ) -> ReadInvestigationRunRecord:
        return await self._inner.fail(
            owner_principal_id=owner_principal_id,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
            lease_token=lease_token,
            failure_reason=failure_reason,
            usage=usage,
            now=now,
            state=state,
        )

    async def reconcile_expired(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[ReadInvestigationRunRecord, ...]:
        return await self._inner.reconcile_expired(now=now, limit=limit)

    async def purge_retained(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[tuple[str, str], ...]:
        return await self._inner.purge_retained(now=now, limit=limit)


async def test_complete_conflict_still_returns_direct_result() -> None:
    provider = _Provider()
    latency = _LatencyStore(measured=True)
    run_store = _CompleteConflictRunStore(InMemoryReadInvestigationRunStore())
    background_store = InMemoryBackgroundTaskStore()
    coordinator = _Coordinator()

    async def authorize(_request: Request) -> Principal:
        return Principal(oid="principal:one", roles=frozenset({Role.CONTRIBUTOR}))

    config = ReadInvestigationRoutesConfig(
        service=ReadInvestigationService(provider, clock=lambda: NOW, latency_store=latency),
        run_store=run_store,  # type: ignore[arg-type]
        latency_store=latency,
        background=BackgroundTaskRoutesConfig(
            service=BackgroundTaskService(store=background_store, audit=_Audit()),
            store=background_store,
            coordinator=coordinator,  # type: ignore[arg-type]
        ),
        scope_ref="scope:allowed",
        clock=lambda: NOW,
    )
    app = Starlette(
        routes=list(make_read_investigation_routes(config=config, authorize_principal=authorize))
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async with client:
        response = await client.post("/read-investigations", json=_body("resource_state"))

    assert response.status_code == 200
    assert response.json()["mode"] == "direct"
    assert response.json()["result"]["outcome"] == "matched"
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]


async def test_complete_conflict_still_returns_stream_terminal() -> None:
    provider = _Provider()
    latency = _LatencyStore(measured=False)
    run_store = _CompleteConflictRunStore(InMemoryReadInvestigationRunStore())
    background_store = InMemoryBackgroundTaskStore()
    coordinator = _Coordinator()

    async def authorize(_request: Request) -> Principal:
        return Principal(oid="principal:one", roles=frozenset({Role.CONTRIBUTOR}))

    config = ReadInvestigationRoutesConfig(
        service=ReadInvestigationService(provider, clock=lambda: NOW, latency_store=latency),
        run_store=run_store,  # type: ignore[arg-type]
        latency_store=latency,
        background=BackgroundTaskRoutesConfig(
            service=BackgroundTaskService(store=background_store, audit=_Audit()),
            store=background_store,
            coordinator=coordinator,  # type: ignore[arg-type]
        ),
        scope_ref="scope:allowed",
        clock=lambda: NOW,
    )
    app = Starlette(
        routes=list(make_read_investigation_routes(config=config, authorize_principal=authorize))
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async with client:
        response = await client.post("/read-investigations", json=_body("resource_state"))

    assert response.status_code == 200
    assert "event: terminal" in response.text
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE]
