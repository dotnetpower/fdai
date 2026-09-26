"""Contract tests for the disabled-by-default Container Apps Job adapter."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fdai.core.execution_backend.profiles import (
    CancellationGuarantee,
    ExecutionAuthority,
    ExecutionBackendKind,
    ExecutionBackendProfile,
    ExecutionNetworkProfile,
    ExecutionProfileError,
    PersistenceMode,
    ResourceCeilings,
    WorkspaceMode,
)
from fdai.delivery.execution_backend import (
    AzureContainerAppsJobExecutionBackend,
    ContainerAppsJobConfig,
    ContainerAppsJobTemplate,
)
from fdai.shared.providers.execution_backend import (
    ExecutionBackendError,
    ExecutionBackendRequest,
    ExecutionCleanupState,
    ExecutionHealthState,
    ExecutionOwnerTrace,
    ExecutionStatus,
)
from fdai.shared.providers.workload_identity import IdentityToken
from fdai.shared.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

_JOB = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/"
    "example/providers/Microsoft.App/jobs/fdai-example"
)
_REF = f"https://management.azure.com{_JOB}/executions/fdai-example-abc"
_DIGEST = "a" * 64
_CEILINGS = ResourceCeilings(1000, 256_000_000, 64_000_000, 1)


class _Identity:
    def __init__(self, *, audience: str = "https://management.azure.com/.default") -> None:
        self.audience = audience
        self.calls: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.calls.append(audience)
        return IdentityToken(
            "test-only-token", datetime.now(UTC) + timedelta(minutes=5), self.audience
        )


class _Arm:
    def __init__(self) -> None:
        self.image = f"example.invalid/job@sha256:{_DIGEST}"
        self.state = "Running"
        self.start_code = 200
        self.start_body: dict[str, object] = {
            "name": "fdai-example-abc",
            "id": f"{_JOB}/executions/fdai-example-abc",
        }
        self.failure: int | None = None
        self.failures: list[int] = []
        self.requests: list[httpx.Request] = []
        self.cancel_state: str | None = "Stopped"

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failures:
            return httpx.Response(self.failures.pop(0), headers={"Retry-After": "2"})
        if self.failure is not None:
            code = self.failure
            self.failure = None
            return httpx.Response(code, headers={"Retry-After": "2"})
        path = request.url.path
        if path == _JOB:
            return httpx.Response(
                200,
                json={
                    "id": _JOB,
                    "properties": {
                        "template": {"containers": [{"image": self.image}], "initContainers": []},
                    },
                },
            )
        if path == f"{_JOB}/start":
            return httpx.Response(self.start_code, json=self.start_body)
        if path == f"{_JOB}/executions/fdai-example-abc/stop":
            if self.cancel_state is not None:
                self.state = self.cancel_state
            return httpx.Response(202)
        if path == f"{_JOB}/executions/fdai-example-abc":
            return httpx.Response(
                200,
                json={
                    "name": "fdai-example-abc",
                    "id": path,
                    "properties": {
                        "status": self.state,
                        "template": {"containers": [{"image": self.image}]},
                    },
                },
            )
        raise AssertionError(f"unexpected ARM request path: {path}")


def _profile() -> ExecutionBackendProfile:
    return ExecutionBackendProfile(
        profile_id="job.example",
        version="1.0.0",
        backend_kind=ExecutionBackendKind.AZURE_CONTAINER_APPS_JOB,
        workload_ids=frozenset({"job.read"}),
        workspace_mode=WorkspaceMode.NONE,
        network_profiles=frozenset({ExecutionNetworkProfile.AZURE_CONTROL_PLANE}),
        credential_profile_refs=frozenset({"azure.job"}),
        max_timeout_seconds=30,
        max_output_bytes=1024,
        resources=_CEILINGS,
        persistence_mode=PersistenceMode.DURABLE,
        regions=frozenset({"example-region"}),
        scope_refs=frozenset({"scope.example"}),
        cancellation_guarantee=CancellationGuarantee.BEST_EFFORT,
        template_ref="job.template",
        artifact_digest=_DIGEST,
    )


def _authority() -> ExecutionAuthority:
    profile = _profile()
    return ExecutionAuthority(
        backend_kind=profile.backend_kind,
        workload_ids=profile.workload_ids,
        workspace_mode=profile.workspace_mode,
        network_profiles=profile.network_profiles,
        credential_profile_refs=profile.credential_profile_refs,
        max_timeout_seconds=profile.max_timeout_seconds,
        max_output_bytes=profile.max_output_bytes,
        resources=profile.resources,
        regions=profile.regions,
        scope_refs=profile.scope_refs,
    )


def _request(**changes: Any) -> ExecutionBackendRequest:
    request = ExecutionBackendRequest(
        workload_id="job.read",
        idempotency_key="run-1",
        artifact_digest=_DIGEST,
        profile_id="job.example",
        profile_version="1.0.0",
        owner_trace=ExecutionOwnerTrace("event", "action", "correlation"),
        stop_condition="stop after 30 seconds",
        audit_ref="audit",
        scope_ref="scope.example",
        region="example-region",
        payload=None,
    )
    return replace(request, **changes)


def _backend(
    arm: _Arm,
    identity: _Identity,
    *,
    circuit: CircuitBreaker | None = None,
    sleep: Any = None,
) -> AzureContainerAppsJobExecutionBackend:
    client = httpx.AsyncClient(transport=httpx.MockTransport(arm.handle))
    options: dict[str, Any] = {}
    if sleep is not None:
        options["sleep"] = sleep
    return AzureContainerAppsJobExecutionBackend(
        templates={"job.template": ContainerAppsJobTemplate(_JOB, _authority(), _DIGEST)},
        identity=identity,
        http_client=client,
        circuit=circuit,
        **options,
    )


async def test_plan_submit_and_restart_safe_status_and_retention() -> None:
    arm, identity = _Arm(), _Identity()
    backend = _backend(arm, identity)
    plan = await backend.plan(_request(), profile=_profile())
    assert [request.method for request in arm.requests] == ["GET"]
    receipt = await backend.submit(plan)
    assert receipt.status is ExecutionStatus.SUBMITTED
    assert receipt.submission_ref == _REF
    starts = [request for request in arm.requests if request.url.path.endswith("/start")]
    assert len(starts) == 1
    assert starts[0].content == b"{}"
    assert starts[0].headers["Authorization"] == "Bearer test-only-token"
    assert "api-version=2024-03-01" in str(starts[0].url)
    with pytest.raises(ExecutionBackendError, match="locally verified|already submitted"):
        await backend.submit(plan)
    restarted = _backend(arm, identity)
    assert (await restarted.status(_REF)).status is ExecutionStatus.RUNNING
    arm.state = "Succeeded"
    assert (await restarted.collect_receipt(_REF)).status is ExecutionStatus.SUCCEEDED
    assert (await restarted.cleanup(_REF)).state is ExecutionCleanupState.PROVIDER_RETENTION
    assert (await backend.capabilities()).durable_provider_state
    assert identity.calls == ["https://management.azure.com/.default"] * len(arm.requests)


@pytest.mark.parametrize(
    "change",
    [
        {"payload": {"image": "example.invalid/other"}},
        {"artifact_digest": "b" * 64},
        {"scope_ref": "scope.other"},
        {"region": "other-region"},
        {"profile_id": "other.profile"},
    ],
)
async def test_request_cannot_supply_job_configuration_or_widen_scope(
    change: dict[str, Any],
) -> None:
    arm = _Arm()
    with pytest.raises(ExecutionBackendError, match="does not match"):
        await _backend(arm, _Identity()).plan(_request(**change), profile=_profile())
    assert not arm.requests


async def test_independent_authority_and_pinned_health_fail_before_start() -> None:
    arm = _Arm()
    backend = _backend(arm, _Identity())
    with pytest.raises(ExecutionProfileError, match="widen"):
        await backend.plan(_request(), profile=replace(_profile(), max_timeout_seconds=31))
    assert not arm.requests
    arm.image = "example.invalid/job:latest"
    assert (await backend.health()).state is ExecutionHealthState.UNAVAILABLE
    with pytest.raises(ExecutionBackendError, match="unpinned"):
        await backend.plan(_request(), profile=_profile())
    arm.image = f"example.invalid/job@sha256:{'b' * 64}"
    with pytest.raises(ExecutionBackendError, match="does not match"):
        await backend.plan(_request(), profile=_profile())
    with pytest.raises(ExecutionBackendError, match="does not match"):
        await backend.status(_REF)


async def test_changed_image_between_plan_and_submit_stops_before_post() -> None:
    arm = _Arm()
    backend = _backend(arm, _Identity())
    plan = await backend.plan(_request(), profile=_profile())
    arm.image = "example.invalid/job:latest"
    with pytest.raises(ExecutionBackendError, match="unpinned"):
        await backend.submit(plan)
    assert not any(request.method == "POST" for request in arm.requests)


@pytest.mark.parametrize(
    "body",
    [
        {"name": "../other"},
        {
            "name": "fdai-example-abc",
            "id": f"{_JOB}/executions/other-execution",
        },
        {},
    ],
)
async def test_ambiguous_start_never_retries(body: dict[str, object]) -> None:
    arm = _Arm()
    arm.start_body = body
    backend = _backend(arm, _Identity())
    plan = await backend.plan(_request(), profile=_profile())
    with pytest.raises(ExecutionBackendError):
        await backend.submit(plan)
    assert sum(request.url.path.endswith("/start") for request in arm.requests) == 1
    with pytest.raises(ExecutionBackendError, match="already submitted"):
        await backend.plan(_request(), profile=_profile())


async def test_accepted_without_execution_identity_is_ambiguous() -> None:
    arm = _Arm()
    arm.start_code = 202
    backend = _backend(arm, _Identity())
    with pytest.raises(ExecutionBackendError, match="no execution reference"):
        await backend.submit(await backend.plan(_request(), profile=_profile()))
    assert sum(request.url.path.endswith("/start") for request in arm.requests) == 1


@pytest.mark.parametrize(
    "ref",
    [
        "https://example.invalid" + _JOB + "/executions/fdai-example-abc",
        "http://management.azure.com" + _JOB + "/executions/fdai-example-abc",
        _REF + "/other",
        _REF + "?api-version=other",
        _REF.replace("/jobs/fdai-example/", "/jobs/other/"),
    ],
)
async def test_execution_ref_cannot_escape_exact_job(ref: str) -> None:
    arm = _Arm()
    with pytest.raises(ExecutionBackendError, match="reference"):
        await _backend(arm, _Identity()).status(ref)
    assert not arm.requests


@pytest.mark.parametrize(
    "state, expected",
    [
        ("Processing", ExecutionStatus.SUBMITTED),
        ("Succeeded", ExecutionStatus.SUCCEEDED),
        ("Failed", ExecutionStatus.FAILED),
        ("Stopped", ExecutionStatus.CANCELLED),
        ("Unknown", ExecutionStatus.AMBIGUOUS),
    ],
)
async def test_provider_states_are_explicit(state: str, expected: ExecutionStatus) -> None:
    arm = _Arm()
    arm.state = state
    assert (await _backend(arm, _Identity()).status(_REF)).status is expected


async def test_stop_race_and_retention_never_claim_unobserved_success() -> None:
    arm = _Arm()
    backend = _backend(arm, _Identity())
    arm.cancel_state = "Succeeded"
    assert (await backend.cancel(_REF)).status is ExecutionStatus.SUCCEEDED
    arm.state = "Running"
    arm.cancel_state = None
    assert (await backend.cancel(_REF)).status is ExecutionStatus.RUNNING
    with pytest.raises(ExecutionBackendError, match="terminal"):
        await backend.cleanup(_REF)
    assert sum(request.url.path.endswith("/stop") for request in arm.requests) == 2


async def test_bounded_retry_circuit_and_redacted_failure() -> None:
    arm = _Arm()
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    circuit = CircuitBreaker(
        name="test", config=CircuitBreakerConfig(failure_threshold=2, reset_timeout_s=30)
    )
    backend = _backend(arm, _Identity(), circuit=circuit, sleep=sleep)
    arm.failure = 429
    assert (await backend.health()).state is ExecutionHealthState.HEALTHY
    assert delays == [2]
    arm.failures = [503, 503]
    with pytest.raises(ExecutionBackendError, match="circuit"):
        await backend.status(_REF)
    before = len(arm.requests)
    assert (await backend.health()).state is ExecutionHealthState.UNAVAILABLE
    assert len(arm.requests) == before
    with pytest.raises(ValueError, match="HTTPS origin"):
        ContainerAppsJobConfig(endpoint="https://management.azure.com@other.invalid")


async def test_identity_audience_mismatch_does_not_issue_http_request() -> None:
    arm = _Arm()
    with pytest.raises(ExecutionBackendError, match="audience"):
        await _backend(arm, _Identity(audience="wrong")).status(_REF)
    assert not arm.requests
