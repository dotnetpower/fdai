from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from fdai.delivery.azure.gateway_direct_api import (
    AzureGatewayDirectApiConfig,
    AzureGatewayDirectApiExecutor,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.direct_api import (
    DirectApiAuthenticationError,
    DirectApiOutcome,
    DirectApiPermissionDeniedError,
    DirectApiPreconditionError,
    DirectApiRequest,
)
from fdai.shared.providers.workload_identity import IdentityToken


class _Identity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="executor-token",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            audience=audience,
        )


def _request(*, mode: Mode) -> DirectApiRequest:
    return DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key="operation:one",
        action_type_name="ops.start-vm",
        rule_ids=("operator.request.ops.start-vm",),
        resource_ref="resource:vm-app",
        arguments={
            "resource_group": "rg-example",
            "vm_name": "vm-app",
            "reason": "recover the unavailable service",
        },
        labels=(("enforce",) if mode is Mode.ENFORCE else ("shadow",)),
        mode=mode,
        metadata={
            "audit_ref": "action:audit-one",
            "stop_condition": "provider_api_error_streak",
            "rollback_ref": "state_forward_only",
            "max_resources": "1",
        },
    )


def _config() -> AzureGatewayDirectApiConfig:
    return AzureGatewayDirectApiConfig(
        base_url="https://gateway.example.com",
        audience="api-application-id",
        poll_interval_seconds=0,
    )


async def test_enforce_plans_then_mutates_with_executor_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/azure.operation.plan"):
            return httpx.Response(
                200,
                json={
                    "operation_id": "azure.operation.plan",
                    "status": "succeeded",
                    "result": {
                        "status": "planned",
                        "dry_run_receipt": "server-receipt",
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "operation_id": "azure.compute.vm.start",
                "status": "succeeded",
                "result": {"status": "Succeeded"},
            },
        )

    identity = _Identity()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await AzureGatewayDirectApiExecutor(
            config=_config(), identity=identity, http_client=client
        ).execute(_request(mode=Mode.ENFORCE))

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == [
        "azure.operation.plan",
        "azure.compute.vm.start",
    ]
    assert all(request.headers["Authorization"] == "Bearer executor-token" for request in requests)
    mutation = requests[1].read().decode()
    assert '"dry_run_receipt":"server-receipt"' in mutation
    assert identity.audiences == ["api-application-id", "api-application-id"]


async def test_shadow_plans_without_mutating() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "operation_id": "azure.operation.plan",
                "status": "succeeded",
                "result": {"status": "planned", "dry_run_receipt": "server-receipt"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await AzureGatewayDirectApiExecutor(
            config=_config(), identity=_Identity(), http_client=client
        ).execute(_request(mode=Mode.SHADOW))

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert len(requests) == 1
    assert requests[0].url.path.endswith("/azure.operation.plan")


async def test_enforce_polls_submitted_operation_until_success() -> None:
    statuses = iter(("running", "succeeded"))

    def handler(request: httpx.Request) -> httpx.Response:
        operation = request.url.path.rsplit("/", 1)[-1]
        if operation == "azure.operation.plan":
            return httpx.Response(
                200,
                json={
                    "operation_id": operation,
                    "status": "succeeded",
                    "result": {"status": "planned", "dry_run_receipt": "receipt"},
                },
            )
        if operation == "azure.compute.vm.start":
            return httpx.Response(
                200,
                json={"operation_id": operation, "status": "submitted", "result": {}},
            )
        status = next(statuses)
        return httpx.Response(
            200,
            json={"operation_id": operation, "status": status, "result": {}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await AzureGatewayDirectApiExecutor(
            config=_config(), identity=_Identity(), http_client=client
        ).execute(_request(mode=Mode.ENFORCE))

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED


async def test_adapter_rejects_oversized_gateway_response() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 262_145))
    async with httpx.AsyncClient(transport=transport) as client:
        executor = AzureGatewayDirectApiExecutor(
            config=_config(), identity=_Identity(), http_client=client
        )
        with pytest.raises(RuntimeError, match="too large"):
            await executor.execute(_request(mode=Mode.SHADOW))


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    (
        (401, DirectApiAuthenticationError),
        (403, DirectApiPermissionDeniedError),
    ),
)
async def test_authorization_status_is_classified_before_body_parsing(
    status_code: int,
    error_type: type[Exception],
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(status_code, content=b"not-json-sensitive-body")
    )
    async with httpx.AsyncClient(transport=transport) as client:
        executor = AzureGatewayDirectApiExecutor(
            config=_config(), identity=_Identity(), http_client=client
        )
        with pytest.raises(error_type):
            await executor.execute(_request(mode=Mode.SHADOW))


async def test_precondition_response_does_not_surface_untrusted_detail() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            409,
            json={"detail": "resource/customer-sensitive-detail"},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        executor = AzureGatewayDirectApiExecutor(
            config=_config(), identity=_Identity(), http_client=client
        )
        with pytest.raises(
            DirectApiPreconditionError,
            match="operations gateway precondition failed",
        ) as caught:
            await executor.execute(_request(mode=Mode.SHADOW))
    assert "customer-sensitive" not in str(caught.value)
