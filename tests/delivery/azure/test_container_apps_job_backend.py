"""Azure Container Apps Job backend uses only server-owned templates."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import httpx
import pytest

from fdai.core.execution_backend import (
    CancellationGuarantee,
    ExecutionBackendKind,
    ExecutionBackendProfile,
    ExecutionNetworkProfile,
    PersistenceMode,
    ResourceCeilings,
    WorkspaceMode,
)
from fdai.delivery.azure.container_apps_job_backend import (
    AzureContainerAppsJobBackendConfig,
    AzureContainerAppsJobExecutionBackend,
    AzureContainerAppsJobTemplate,
    ContainerAppsJobTrigger,
)
from fdai.shared.providers.execution_backend import (
    ExecutionBackendError,
    ExecutionBackendRequest,
    ExecutionCleanupState,
    ExecutionHealthState,
    ExecutionOwnerTrace,
    ExecutionStatus,
)
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

_TOKEN = "test-token"  # noqa: S105 - deterministic fake
_AUDIENCE = "https://management.azure.com/.default"
_DIGEST = "a" * 64
_JOB_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/"
    "rg-example/providers/Microsoft.App/jobs/job-example"
)


def _profile() -> ExecutionBackendProfile:
    return ExecutionBackendProfile(
        profile_id="aca.report",
        version="1.0.0",
        backend_kind=ExecutionBackendKind.AZURE_CONTAINER_APPS_JOB,
        workload_ids=frozenset({"report.render"}),
        workspace_mode=WorkspaceMode.NONE,
        network_profiles=frozenset({ExecutionNetworkProfile.AZURE_CONTROL_PLANE}),
        credential_profile_refs=frozenset({"azure.executor"}),
        max_timeout_seconds=300,
        max_output_bytes=10_000,
        resources=ResourceCeilings(
            cpu_millis=1_000,
            memory_bytes=512_000_000,
            ephemeral_storage_bytes=1_000_000_000,
            max_concurrency=1,
        ),
        persistence_mode=PersistenceMode.DURABLE,
        regions=frozenset({"example-region"}),
        scope_refs=frozenset({_JOB_ID}),
        cancellation_guarantee=CancellationGuarantee.BEST_EFFORT,
        template_ref="report.job",
        artifact_digest=_DIGEST,
    )


def _request() -> ExecutionBackendRequest:
    return ExecutionBackendRequest(
        workload_id="report.render",
        idempotency_key="event-1:report",
        artifact_digest=_DIGEST,
        profile_id="aca.report",
        profile_version="1.0.0",
        owner_trace=ExecutionOwnerTrace(
            event_ref="event:1",
            action_ref="action:1",
            correlation_ref="trace:1",
        ),
        stop_condition="stop after 300 seconds or terminal state",
        audit_ref="audit:action:1",
        scope_ref=_JOB_ID,
        region="example-region",
        payload=ContainerAppsJobTrigger(workload_id="report.render"),
    )


def _adapter(
    client: httpx.AsyncClient,
    *,
    config: AzureContainerAppsJobBackendConfig | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> AzureContainerAppsJobExecutionBackend:
    identity = StaticWorkloadIdentity(audience=_AUDIENCE, token=_TOKEN)
    templates = {
        "report.job": AzureContainerAppsJobTemplate(
            template_ref="report.job",
            job_resource_id=_JOB_ID,
            image_digest=_DIGEST,
        )
    }
    backend_config = config or AzureContainerAppsJobBackendConfig(endpoint="https://mock-arm.local")
    if sleep is None:
        return AzureContainerAppsJobExecutionBackend(
            identity=identity,
            http_client=client,
            templates=templates,
            config=backend_config,
        )
    return AzureContainerAppsJobExecutionBackend(
        identity=identity,
        http_client=client,
        templates=templates,
        config=backend_config,
        sleep=sleep,
    )


async def test_full_job_lifecycle_never_sends_image_command_or_credentials() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/start"):
            return httpx.Response(202, json={"name": "job-example-abc123"})
        if request.url.path.endswith("/stop"):
            return httpx.Response(202, json={})
        return httpx.Response(200, json={"properties": {"status": "Succeeded"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = _adapter(client)
        plan = await backend.plan(_request(), profile=_profile())
        submitted = await backend.submit(plan)
        status = await backend.status(submitted.submission_ref)
        cancelled = await backend.cancel(submitted.submission_ref)
        receipt = await backend.collect_receipt(submitted.submission_ref)
        cleanup = await backend.cleanup(submitted.submission_ref)

    start = calls[0]
    assert start.method == "POST"
    assert json.loads(start.content) == {}
    assert b"image" not in start.content
    assert b"command" not in start.content
    assert _TOKEN.encode() not in start.content
    assert start.headers["Authorization"] == f"Bearer {_TOKEN}"
    assert status.status is ExecutionStatus.SUCCEEDED
    assert cancelled.status is ExecutionStatus.SUCCEEDED
    assert receipt.output_digest is not None
    assert cleanup.state is ExecutionCleanupState.PROVIDER_RETENTION


async def test_health_verifies_server_owned_pinned_image() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "properties": {
                    "template": {
                        "containers": [{"image": f"registry.example/reports@sha256:{_DIGEST}"}]
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        health = await _adapter(client).health()

    assert health.state is ExecutionHealthState.HEALTHY


async def test_retry_after_is_bounded_and_retries_transient_start() -> None:
    calls = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(202, json={"name": "job-example-retry"})

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = _adapter(client, sleep=sleep)
        plan = await backend.plan(_request(), profile=_profile())
        receipt = await backend.submit(plan)

    assert receipt.status is ExecutionStatus.SUBMITTED
    assert calls == 2
    assert delays == [0.0]


async def test_repeated_failures_open_circuit_and_health_stops_calling_arm() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"error": "unavailable"})

    config = AzureContainerAppsJobBackendConfig(
        endpoint="https://mock-arm.local",
        max_attempts=1,
        circuit_failure_threshold=2,
        circuit_reset_seconds=60,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = _adapter(client, config=config)
        first = await backend.health()
        second = await backend.health()
        third = await backend.health()

    assert first.state is ExecutionHealthState.UNAVAILABLE
    assert second.state is ExecutionHealthState.UNAVAILABLE
    assert third.state is ExecutionHealthState.UNAVAILABLE
    assert calls == 2


async def test_provider_error_body_is_not_copied_into_execution_error() -> None:
    secret_canary = "client_secret=must-not-leak"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=secret_canary)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = _adapter(client)
        plan = await backend.plan(_request(), profile=_profile())
        with pytest.raises(ExecutionBackendError) as caught:
            await backend.submit(plan)

    assert secret_canary not in str(caught.value)
