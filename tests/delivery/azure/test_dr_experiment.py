"""AzureDrExperimentAdapter — HTTP-level round-trip via httpx.MockTransport.

Verifies the wire contract the P3 executor + risk-gate rely on:

- Bearer-token auth via the injected :class:`WorkloadIdentity`.
- ``start`` dispatches to ``/start`` for Chaos experiments and
  ``/plannedFailover`` for Site Recovery, with the correct API-version
  query parameter for each surface.
- 202 accepted responses populate ``status_url`` from the
  ``Azure-AsyncOperation`` (or ``Location``) header.
- ``check`` reduces the vendor ``status`` (or nested
  ``properties.provisioningState``) to a :class:`DrRunStatus`; unknown
  values map to ``RUNNING`` so a caller keeps polling.
- ``rollback`` dispatches to ``/cancel`` for Chaos and
  ``/plannedFailoverCleanup`` for Site Recovery; 404 is a legitimate
  idempotent no-op.
- Non-2xx / non-JSON / transport failures raise :class:`DrRunnerError`
  with a truncated snippet — no raw response body leaks.

No real Azure endpoints are contacted; every test builds an
``httpx.AsyncClient`` on top of :class:`httpx.MockTransport`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from aiopspilot.core.verticals.resilience import DrExperiment
from aiopspilot.delivery.azure.dr_experiment import (
    AzureDrExperimentAdapter,
    AzureDrExperimentAdapterConfig,
)
from aiopspilot.shared.providers.dr_experiment import (
    DrExperimentKind,
    DrRunHandle,
    DrRunnerError,
    DrRunStatus,
)
from aiopspilot.shared.providers.testing.workload_identity import (
    StaticWorkloadIdentity,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_AUDIENCE = "https://management.azure.com/.default"
_TOKEN = "test-token-abc"  # noqa: S105 — deterministic test literal

_CHAOS_REF = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/"
    "rg-example/providers/Microsoft.Chaos/experiments/exp-1"
)
_ASR_REF = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/"
    "rg-example/providers/Microsoft.RecoveryServices/vaults/vault-1/"
    "replicationRecoveryPlans/plan-1"
)


def _identity() -> StaticWorkloadIdentity:
    return StaticWorkloadIdentity(audience=_AUDIENCE, token=_TOKEN)


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="https://mock-arm.local")


def _adapter(
    client: httpx.AsyncClient,
    *,
    config: AzureDrExperimentAdapterConfig | None = None,
) -> AzureDrExperimentAdapter:
    return AzureDrExperimentAdapter(
        identity=_identity(),
        http_client=client,
        config=config,
    )


def _chaos_experiment(*, provider_ref: str = _CHAOS_REF) -> DrExperiment:
    return DrExperiment(
        experiment_id="exp-1",
        target_resource_ref="res-1",
        provider_ref=provider_ref,
        is_production_target=False,
        has_rollback_path=True,
        stop_conditions=("health-probe-failure",),
    )


def _asr_experiment() -> DrExperiment:
    return DrExperiment(
        experiment_id="rp-1",
        target_resource_ref="db-1",
        provider_ref=_ASR_REF,
        is_production_target=False,
        has_rollback_path=True,
        stop_conditions=("integrity-mismatch",),
    )


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


def test_zero_timeout_is_rejected() -> None:
    with pytest.raises(ValueError, match="timeout_seconds MUST be > 0"):
        AzureDrExperimentAdapter(
            identity=_identity(),
            http_client=httpx.AsyncClient(),
            config=AzureDrExperimentAdapterConfig(timeout_seconds=0),
        )


def test_tiny_error_body_cap_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_error_body_bytes MUST be >= 64"):
        AzureDrExperimentAdapter(
            identity=_identity(),
            http_client=httpx.AsyncClient(),
            config=AzureDrExperimentAdapterConfig(max_error_body_bytes=32),
        )


# ---------------------------------------------------------------------------
# Happy path — Chaos Studio synchronous start
# ---------------------------------------------------------------------------


async def test_chaos_start_hits_start_endpoint_with_bearer_auth() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "exec-42", "status": "Running"})

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.start(_chaos_experiment())

    assert handle.kind is DrExperimentKind.CHAOS
    assert handle.run_id == "exec-42"
    assert handle.provider_ref == _CHAOS_REF
    assert handle.status_url is None  # no LRO header on synchronous 200

    assert len(seen) == 1
    req = seen[0]
    assert req.method == "POST"
    assert req.headers["Authorization"] == f"Bearer {_TOKEN}"
    assert req.url.path.endswith("/experiments/exp-1/start")
    assert req.url.params["api-version"] == "2024-01-01"


async def test_chaos_start_202_captures_lro_status_url() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            headers={
                "Azure-AsyncOperation": (
                    "https://management.azure.com/subscriptions/xxx/"
                    "providers/Microsoft.Chaos/operationResults/op-1?api-version=2024-01-01"
                )
            },
        )

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.start(_chaos_experiment())

    assert handle.status_url is not None
    assert "operationResults/op-1" in handle.status_url
    # Without a body id the run_id falls back to the LRO URL.
    assert handle.run_id == handle.status_url


async def test_chaos_start_falls_back_to_location_header() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            headers={"Location": "https://management.azure.com/subscriptions/xxx/operations/op-2"},
        )

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.start(_chaos_experiment())

    assert handle.status_url is not None
    assert handle.status_url.endswith("/operations/op-2")


async def test_chaos_start_uses_body_name_when_no_id() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "exec-name-only"})

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.start(_chaos_experiment())

    assert handle.run_id == "exec-name-only"


async def test_chaos_start_synchronous_200_without_body_uses_provider_ref() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.start(_chaos_experiment())

    # No LRO header and no body → run_id falls back to the ARM id.
    assert handle.run_id == _CHAOS_REF
    assert handle.status_url is None


# ---------------------------------------------------------------------------
# Site Recovery dispatch
# ---------------------------------------------------------------------------


async def test_site_recovery_start_hits_planned_failover_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "asr-op-1", "status": "InProgress"})

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.start(_asr_experiment())

    assert handle.kind is DrExperimentKind.SITE_RECOVERY_TEST_FAILOVER
    assert handle.run_id == "asr-op-1"

    assert len(seen) == 1
    req = seen[0]
    assert req.url.path.endswith("/replicationRecoveryPlans/plan-1/plannedFailover")
    assert req.url.params["api-version"] == "2024-04-01"


async def test_site_recovery_rollback_hits_cleanup_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        # start
        if request.url.path.endswith("plannedFailover"):
            return httpx.Response(200, json={"id": "asr-op-1"})
        # rollback
        return httpx.Response(202)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = await adapter.start(_asr_experiment())
        await adapter.rollback(handle)

    assert seen[-1].url.path.endswith("/replicationRecoveryPlans/plan-1/plannedFailoverCleanup")
    assert seen[-1].url.params["api-version"] == "2024-04-01"


# ---------------------------------------------------------------------------
# check() — status reduction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "vendor_status,expected",
    [
        ("Succeeded", DrRunStatus.SUCCEEDED),
        ("success", DrRunStatus.SUCCEEDED),
        ("Completed", DrRunStatus.SUCCEEDED),
        ("Failed", DrRunStatus.FAILED),
        ("Error", DrRunStatus.FAILED),
        ("Cancelled", DrRunStatus.STOPPED),
        ("Canceled", DrRunStatus.STOPPED),
        ("Aborted", DrRunStatus.STOPPED),
        ("Running", DrRunStatus.RUNNING),
        ("in-progress", DrRunStatus.RUNNING),  # unknown → RUNNING
    ],
)
async def test_check_maps_vendor_status_to_run_status(
    vendor_status: str, expected: DrRunStatus
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": vendor_status})

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = _handle(status_url="https://mock-arm.local/op/1")
        status = await adapter.check(handle)

    assert status is expected


async def test_check_reads_nested_provisioning_state() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"properties": {"provisioningState": "Succeeded"}})

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = _handle(status_url=None)  # falls back to resource-URL GET
        status = await adapter.check(handle)

    assert status is DrRunStatus.SUCCEEDED


async def test_check_reports_running_on_202() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, text="")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = _handle(status_url="https://mock-arm.local/op/1")
        status = await adapter.check(handle)

    assert status is DrRunStatus.RUNNING


async def test_check_reports_running_on_missing_status_field() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unrelated": "yes"})

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = _handle(status_url="https://mock-arm.local/op/1")
        status = await adapter.check(handle)

    assert status is DrRunStatus.RUNNING


async def test_check_reports_running_on_non_dict_payload() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        handle = _handle(status_url="https://mock-arm.local/op/1")
        status = await adapter.check(handle)

    assert status is DrRunStatus.RUNNING


# ---------------------------------------------------------------------------
# Rollback — idempotent 200 / 202 / 204 / 404
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [200, 202, 204, 404])
async def test_rollback_swallows_idempotent_statuses(status_code: int) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code, text="")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        await adapter.rollback(_handle())

    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert seen[0].url.path.endswith("/experiments/exp-1/cancel")


async def test_rollback_raises_on_500() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="substrate boom")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DrRunnerError) as excinfo:
            await adapter.rollback(_handle())

    assert excinfo.value.status_code == 500
    assert "substrate boom" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Failure paths — start
# ---------------------------------------------------------------------------


async def test_start_raises_on_non_2xx() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden — RBAC")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DrRunnerError) as excinfo:
            await adapter.start(_chaos_experiment())

    assert excinfo.value.status_code == 403
    assert "RBAC" in str(excinfo.value)


async def test_start_wraps_transport_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated network failure")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DrRunnerError, match="start request failed"):
            await adapter.start(_chaos_experiment())


async def test_start_requires_provider_ref() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP MUST NOT be touched when provider_ref is missing")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        experiment = DrExperiment(
            experiment_id="no-ref",
            target_resource_ref="res-1",
            provider_ref=None,
            has_rollback_path=True,
            stop_conditions=("x",),
        )
        with pytest.raises(DrRunnerError, match="provider_ref is required"):
            await adapter.start(experiment)


# ---------------------------------------------------------------------------
# Failure paths — check
# ---------------------------------------------------------------------------


async def test_check_raises_on_non_2xx() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="token expired")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DrRunnerError) as excinfo:
            await adapter.check(_handle(status_url="https://mock-arm.local/op/1"))

    assert excinfo.value.status_code == 401


async def test_check_raises_on_non_json() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not-json</html>")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DrRunnerError, match="non-JSON"):
            await adapter.check(_handle(status_url="https://mock-arm.local/op/1"))


async def test_check_wraps_transport_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("bang")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DrRunnerError, match="check request failed"):
            await adapter.check(_handle(status_url="https://mock-arm.local/op/1"))


async def test_rollback_wraps_transport_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("bang")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DrRunnerError, match="rollback request failed"):
            await adapter.rollback(_handle())


# ---------------------------------------------------------------------------
# Error-body truncation
# ---------------------------------------------------------------------------


async def test_start_error_body_is_truncated() -> None:
    huge_body = "x" * 2048  # bigger than the default 512-byte cap

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=huge_body)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(DrRunnerError) as excinfo:
            await adapter.start(_chaos_experiment())

    rendered = str(excinfo.value)
    # The rendered message includes the "…" ellipsis marker inserted by
    # the trimmer; the full 2KB body MUST NOT appear.
    assert "…" in rendered
    assert rendered.count("x") < len(huge_body)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _handle(
    *,
    status_url: str | None = "https://mock-arm.local/op/1",
    kind: DrExperimentKind = DrExperimentKind.CHAOS,
    provider_ref: str = _CHAOS_REF,
) -> DrRunHandle:
    return DrRunHandle(
        experiment_id="exp-1",
        kind=kind,
        provider_ref=provider_ref,
        run_id="run-1",
        started_at=datetime.now(tz=UTC),
        status_url=status_url,
    )
