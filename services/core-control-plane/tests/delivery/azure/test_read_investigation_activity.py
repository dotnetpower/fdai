"""Bounded exact-target Azure Activity Log investigation tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fdai.delivery.azure.read_investigation_activity import (
    AzureActivityReadConfig,
    AzureActivityReadInvestigationProvider,
)
from fdai.shared.providers.read_investigation import (
    EvidenceLimitationKind,
    EvidenceStatus,
    ReadToolLimits,
    ResolvedResource,
)
from fdai.shared.providers.workload_identity import IdentityToken

SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"
NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        assert audience == "https://management.azure.com/.default"
        return IdentityToken(
            token="test-token",
            expires_at=NOW + timedelta(minutes=5),
            audience=audience,
        )


class _BaseProvider:
    transport = "inventory"

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"unexpected base provider call: {name}")


def _resource() -> ResolvedResource:
    return ResolvedResource(
        resource_ref=(
            "scope-0123456789abcdef/resource-group/example-rg/providers/"
            "microsoft.app/containerapps/service-example-api"
        ),
        scope_ref="scope-example",
        name="service-example-api",
        resource_type="container-app",
        resource_group="example-rg",
    )


def _limits(*, max_results: int = 8) -> ReadToolLimits:
    return ReadToolLimits(timeout_seconds=5, max_results=max_results, max_output_bytes=64_000)


async def test_activity_read_filters_one_exact_resolved_target() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "eventTimestamp": "2026-08-20T11:55:00Z",
                        "resourceId": (
                            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/example-rg/"
                            "providers/Microsoft.App/containerApps/service-example-api"
                        ),
                        "operationName": {"value": "Microsoft.App/containerApps/write"},
                        "status": {"value": "Succeeded"},
                        "caller": "00000000-0000-0000-0000-000000000001",
                        "correlationId": "00000000-0000-0000-0000-000000000002",
                    },
                    {
                        "eventTimestamp": "2026-08-20T11:56:00Z",
                        "resourceId": (
                            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/example-rg/"
                            "providers/Microsoft.App/containerApps/other-service"
                        ),
                        "operationName": {"value": "Microsoft.App/containerApps/write"},
                        "status": {"value": "Succeeded"},
                    },
                    {
                        "eventTimestamp": "2026-08-20T11:57:00Z",
                        "resourceId": (
                            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/example-rg/"
                            "providers/Microsoft.Compute/virtualMachines/service-example-api"
                        ),
                        "operationName": {"value": "Microsoft.Compute/virtualMachines/write"},
                        "status": {"value": "Succeeded"},
                    },
                    {
                        "eventTimestamp": "2026-08-20T11:58:00Z",
                        "resourceId": (
                            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/example-rg/"
                            "providers/Microsoft.App/containerApps/service-example-api/"
                            "revisions/revision-example"
                        ),
                        "operationName": {"value": "Microsoft.App/containerApps/revisions/write"},
                        "status": {"value": "Succeeded"},
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureActivityReadInvestigationProvider(
            base=_BaseProvider(),  # type: ignore[arg-type]
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureActivityReadConfig(subscription_id=SUBSCRIPTION_ID),
        )
        result = await provider.query_resource_activity(
            _resource(),
            lookback_seconds=3600,
            limits=_limits(),
        )

    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer test-token"
    assert requests[0].url.path.startswith(f"/subscriptions/{SUBSCRIPTION_ID}/providers/")
    assert "resourceGroupName eq 'example-rg'" in requests[0].url.params["$filter"]
    assert result.evidence.status is EvidenceStatus.MATCHED
    assert len(result.evidence.records) == 1
    assert result.evidence.records[0].operation_kind == "microsoft_app_containerapps_write"
    assert result.evidence.records[0].status == "succeeded"
    assert result.evidence.records[0].actor_ref == "00000000-0000-0000-0000-000000000001"
    assert result.evidence.evidence_refs[0].startswith("azure-activity:")
    assert result.evidence.truncated is False


async def test_activity_read_caps_results_and_marks_truncation() -> None:
    rows = [
        {
            "eventTimestamp": f"2026-08-20T11:{50 + index:02d}:00Z",
            "resourceId": (
                f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/example-rg/"
                "providers/Microsoft.App/containerApps/service-example-api"
            ),
            "operationName": {"value": "Microsoft.App/containerApps/write"},
            "status": {"value": "Succeeded"},
        }
        for index in range(3)
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"value": rows, "nextLink": "bounded"})
        )
    ) as client:
        provider = AzureActivityReadInvestigationProvider(
            base=_BaseProvider(),  # type: ignore[arg-type]
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureActivityReadConfig(subscription_id=SUBSCRIPTION_ID),
        )
        result = await provider.query_resource_activity(
            _resource(),
            lookback_seconds=3600,
            limits=_limits(max_results=2),
        )

    assert len(result.evidence.records) == 2
    assert result.evidence.truncated is True
    assert result.evidence.truncation_reason is EvidenceLimitationKind.RESULT_LIMIT


async def test_activity_read_treats_authorization_and_throttling_as_terminal_unavailable() -> None:
    for status_code, limitation in (
        (403, EvidenceLimitationKind.UNAUTHORIZED),
        (429, EvidenceLimitationKind.SOURCE_UNAVAILABLE),
    ):
        requests = 0

        def handler(
            request: httpx.Request,
            response_status: int = status_code,
        ) -> httpx.Response:
            nonlocal requests
            requests += 1
            return httpx.Response(response_status)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AzureActivityReadInvestigationProvider(
                base=_BaseProvider(),  # type: ignore[arg-type]
                identity=_Identity(),  # type: ignore[arg-type]
                http_client=client,
                config=AzureActivityReadConfig(subscription_id=SUBSCRIPTION_ID),
            )
            result = await provider.query_resource_activity(
                _resource(),
                lookback_seconds=3600,
                limits=_limits(),
            )

        assert requests == 1
        assert result.evidence.status is EvidenceStatus.UNAVAILABLE
        assert result.evidence.limitations == (limitation,)
        assert result.evidence.records == ()


async def test_activity_read_rejects_response_over_byte_budget_before_parsing() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"{" + (b"x" * 1_024) + b"}")
        )
    ) as client:
        provider = AzureActivityReadInvestigationProvider(
            base=_BaseProvider(),  # type: ignore[arg-type]
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureActivityReadConfig(subscription_id=SUBSCRIPTION_ID),
        )
        result = await provider.query_resource_activity(
            _resource(),
            lookback_seconds=3600,
            limits=ReadToolLimits(
                timeout_seconds=5,
                max_results=8,
                max_output_bytes=1_024,
            ),
        )

    assert result.evidence.status is EvidenceStatus.UNAVAILABLE
    assert result.evidence.limitations == (EvidenceLimitationKind.BYTE_LIMIT,)
    assert result.evidence.records == ()
