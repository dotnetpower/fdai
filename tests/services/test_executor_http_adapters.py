"""Focused tests for Executor-owned managed identity and gateway adapters."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from fdai_executor_service.adapters.gateway_direct_api import (
    AzureGatewayDirectApiConfig,
    AzureGatewayDirectApiExecutor,
)
from fdai_executor_service.adapters.workload_identity import (
    ManagedIdentityWorkloadIdentity,
    ManagedIdentityWorkloadIdentityConfig,
)
from fdai_service_contracts.executor import (
    DirectApiAuthenticationError,
    DirectApiOutcome,
    DirectApiPermissionDeniedError,
    DirectApiPreconditionError,
    DirectApiRequest,
    IdentityToken,
    Mode,
)


def _future_epoch(seconds: int = 3600) -> int:
    return int((datetime.now(tz=UTC) + timedelta(seconds=seconds)).timestamp())


async def test_managed_identity_coalesces_concurrent_audience_requests() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        await asyncio.sleep(0.01)
        return httpx.Response(
            200,
            json={"access_token": "executor-token", "expires_on": _future_epoch()},
        )

    config = ManagedIdentityWorkloadIdentityConfig(
        endpoint="https://identity.example/token",
        header="proof",
        client_id="executor-client",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        identity = ManagedIdentityWorkloadIdentity(http_client=client, config=config)
        tokens = await asyncio.gather(*(identity.get_token("gateway") for _ in range(4)))

    assert [token.token for token in tokens] == ["executor-token"] * 4
    assert len(calls) == 1
    assert calls[0].url.params["client_id"] == "executor-client"
    assert calls[0].headers["X-IDENTITY-HEADER"] == "proof"


async def test_managed_identity_malformed_response_is_redacted() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"secret-field": "must-not-leak"})
    )
    config = ManagedIdentityWorkloadIdentityConfig(
        endpoint="https://identity.example/token",
        header="proof",
    )
    async with httpx.AsyncClient(transport=transport) as client:
        identity = ManagedIdentityWorkloadIdentity(http_client=client, config=config)
        with pytest.raises(RuntimeError, match="unrecognized body") as caught:
            await identity.get_token("gateway")

    assert "must-not-leak" not in str(caught.value)


class _Identity:
    def __init__(self, token: str) -> None:
        self.token = token
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token=self.token,
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            audience=audience,
        )


def _request(mode: Mode) -> DirectApiRequest:
    return DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key="operation-one",
        action_type_name="ops.start-vm",
        rule_ids=("operator.request.ops.start-vm",),
        resource_ref="resource:vm-app",
        arguments={"resource_group": "example", "vm_name": "vm-app"},
        labels=("enforce",) if mode is Mode.ENFORCE else ("shadow",),
        mode=mode,
        metadata={
            "audit_ref": "action:one",
            "stop_condition": "provider_api_error_streak",
            "rollback_ref": "state_forward_only",
            "max_resources": "1",
            "executor_identity_ref": "identity/change",
        },
    )


def _gateway_config() -> AzureGatewayDirectApiConfig:
    return AzureGatewayDirectApiConfig(
        base_url="https://gateway.example.com",
        audience="gateway-audience",
        poll_interval_seconds=0,
    )


async def test_gateway_plans_before_enforce_mutation() -> None:
    operations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        operation = request.url.path.rsplit("/", 1)[-1]
        operations.append(operation)
        if operation == "azure.operation.plan":
            return httpx.Response(
                200,
                json={
                    "operation_id": operation,
                    "status": "succeeded",
                    "result": {"dry_run_receipt": "dry-run-one"},
                },
            )
        assert b'"dry_run_receipt":"dry-run-one"' in request.read()
        return httpx.Response(
            200,
            json={"operation_id": operation, "status": "succeeded"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/change": _Identity("gateway-token")},
            http_client=client,
        ).execute(_request(Mode.ENFORCE))

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert operations == ["azure.operation.plan", "azure.compute.vm.start"]


async def test_gateway_uses_exact_action_bound_executor_identity() -> None:
    change_identity = _Identity("change-token")
    resilience_identity = _Identity("resilience-token")
    authorization_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization_headers.append(request.headers["Authorization"])
        operation = request.url.path.rsplit("/", 1)[-1]
        if operation == "azure.operation.plan":
            return httpx.Response(
                200,
                json={
                    "operation_id": operation,
                    "status": "succeeded",
                    "result": {"dry_run_receipt": "dry-run-one"},
                },
            )
        return httpx.Response(
            200,
            json={"operation_id": operation, "status": "succeeded"},
        )

    request = replace(
        _request(Mode.ENFORCE),
        metadata={
            **_request(Mode.ENFORCE).metadata,
            "executor_identity_ref": "identity/change",
        },
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={
                "identity/change": change_identity,
                "identity/resilience": resilience_identity,
            },
            http_client=client,
        ).execute(request)

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert authorization_headers == ["Bearer change-token", "Bearer change-token"]
    assert change_identity.audiences == ["gateway-audience", "gateway-audience"]
    assert resilience_identity.audiences == []


@pytest.mark.parametrize("identity_ref", (None, "identity/unknown"))
async def test_gateway_rejects_unbound_executor_identity_before_http(
    identity_ref: str | None,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    request = _request(Mode.ENFORCE)
    metadata = dict(request.metadata)
    if identity_ref is None:
        metadata.pop("executor_identity_ref")
    else:
        metadata["executor_identity_ref"] = identity_ref
    request = replace(request, metadata=metadata)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        executor = AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/change": _Identity("gateway-token")},
            http_client=client,
        )
        with pytest.raises(DirectApiPreconditionError, match="executor_identity_ref"):
            await executor.execute(request)

    assert calls == 0


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    ((401, DirectApiAuthenticationError), (403, DirectApiPermissionDeniedError)),
)
async def test_gateway_redacts_authorization_response(
    status_code: int,
    error_type: type[Exception],
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(status_code, content=b"sensitive-provider-body")
    )
    async with httpx.AsyncClient(transport=transport) as client:
        executor = AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/change": _Identity("gateway-token")},
            http_client=client,
        )
        with pytest.raises(error_type) as caught:
            await executor.execute(_request(Mode.SHADOW))

    assert "sensitive-provider-body" not in str(caught.value)


async def test_gateway_rejects_oversized_response() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 262_145))
    async with httpx.AsyncClient(transport=transport) as client:
        executor = AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/change": _Identity("gateway-token")},
            http_client=client,
        )
        with pytest.raises(RuntimeError, match="too large"):
            await executor.execute(_request(Mode.SHADOW))


def test_gateway_requires_https_origin_without_credentials() -> None:
    for base_url in (
        "http://gateway.example.com",
        "https://user:password@gateway.example.com",
        "https://gateway.example.com/path",
    ):
        with pytest.raises(ValueError, match="HTTPS origin"):
            AzureGatewayDirectApiConfig(base_url=base_url, audience="gateway")


async def test_gateway_rejects_unregistered_operation_before_http() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    request = _request(Mode.SHADOW)
    request = replace(request, action_type_name="ops.unknown")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        executor = AzureGatewayDirectApiExecutor(
            config=_gateway_config(),
            identities={"identity/change": _Identity("gateway-token")},
            http_client=client,
        )
        with pytest.raises(DirectApiPreconditionError, match="no registered operation"):
            await executor.execute(request)

    assert calls == 0
