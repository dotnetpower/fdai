from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.core.rca import (
    DEFAULT_TELEMETRY_RECIPE_CATALOG,
    TelemetryEvidenceDisposition,
    TelemetryEvidenceRecipe,
    TelemetryLookbackProfile,
    TelemetryMechanism,
    build_telemetry_evidence_need,
)
from fdai.delivery.azure.log_query import (
    AzureLogAnalyticsQueryConfig,
    AzureLogAnalyticsQueryProvider,
)
from fdai.delivery.azure.telemetry_recipe_query import AzureMonitorTelemetryRecipeProvider
from fdai.delivery.azure.telemetry_workspace import AzureTelemetryWorkspaceResolution
from fdai.shared.providers.workload_identity import IdentityToken

_NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)
_RESOURCE_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/"
    "providers/Microsoft.Web/sites/app-example"
)


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token", expires_at=_NOW + timedelta(hours=1), audience=audience
        )


class _Resolver:
    def __init__(self, workspace_ids: tuple[str, ...] = ("workspace-discovered",)) -> None:
        self.workspace_ids = workspace_ids
        self.calls = 0

    async def resolve(
        self, resource_ref: str, *, at: datetime
    ) -> AzureTelemetryWorkspaceResolution:
        self.calls += 1
        assert resource_ref == "resource:one"
        assert at == _NOW
        return AzureTelemetryWorkspaceResolution(
            provider_resource_id=_RESOURCE_ID,
            inventory_generation="generation:one",
            workspace_ids=self.workspace_ids,
        )


def _table(rows: list[list[object]]) -> dict[str, object]:
    return {
        "tables": [
            {
                "columns": [
                    {"name": "signal_count", "type": "long"},
                    {"name": "observed_until", "type": "datetime"},
                    {"name": "band", "type": "string"},
                ],
                "rows": rows,
            }
        ]
    }


def _recipe() -> TelemetryEvidenceRecipe:
    return DEFAULT_TELEMETRY_RECIPE_CATALOG.get("requests.failed", "1.0.0")


def _need(
    recipe: TelemetryEvidenceRecipe | None = None,
    *,
    max_query_count: int = 4,
    max_cost_units: int = 100,
):
    selected = recipe or _recipe()
    return build_telemetry_evidence_need(
        incident_id="incident:one",
        resource_ref="resource:one",
        evidence_cutoff=_NOW,
        recipe=selected,
        max_query_count=max_query_count,
        max_cost_units=max_cost_units,
        idempotency_key="incident:one:round:one",
    )


def _provider(handler: object, resolver: _Resolver | None = None):
    query_provider = AzureLogAnalyticsQueryProvider(
        config=AzureLogAnalyticsQueryConfig(workspace_id="workspace-fallback"),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),  # type: ignore[arg-type]
    )
    selected_resolver = resolver or _Resolver()
    return (
        AzureMonitorTelemetryRecipeProvider(
            query_provider=query_provider,
            workspace_resolver=selected_resolver,
        ),
        selected_resolver,
    )


@pytest.mark.asyncio
async def test_executes_fixed_recipe_across_exact_routes_and_returns_bounded_facts() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_table([[2, "2026-09-16T11:59:00Z", "low"]]))

    provider, _ = _provider(handler)
    receipt = await provider.gather(_need())

    assert receipt.disposition is TelemetryEvidenceDisposition.COMPLETE
    assert receipt.route_count == receipt.queried_route_count == 2
    assert receipt.fact_tokens == ("mechanism:failed_requests", "signal_count_band:low")
    assert receipt.actual_cost_units == 20
    assert receipt.query_execution_authority is False
    assert len(requests) == 2
    for request in requests:
        payload = json.loads(request.content)
        assert "AppRequests" in payload["query"]
        assert _RESOURCE_ID in payload["query"]
        assert "resource:one" not in payload["query"]
        assert payload["timespan"] == "PT15M"


@pytest.mark.asyncio
async def test_complete_empty_routes_are_not_reported_as_unavailable() -> None:
    provider, _ = _provider(lambda _request: httpx.Response(200, json=_table([])))

    receipt = await provider.gather(_need())

    assert receipt.disposition is TelemetryEvidenceDisposition.COMPLETE_NO_DATA
    assert receipt.complete is True
    assert receipt.row_count == 0


@pytest.mark.asyncio
async def test_unauthorized_query_is_terminal_and_not_retried() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(403, text="forbidden")

    provider, _ = _provider(handler)
    receipt = await provider.gather(_need())

    assert receipt.disposition is TelemetryEvidenceDisposition.UNAUTHORIZED
    assert receipt.complete is False
    assert receipt.queried_route_count == 1
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_route_budget_is_checked_before_query_io() -> None:
    requests: list[httpx.Request] = []
    provider, resolver = _provider(
        lambda request: requests.append(request) or httpx.Response(200, json=_table([]))
    )

    with pytest.raises(ValueError, match="query budget"):
        await provider.gather(_need(max_query_count=1))

    assert resolver.calls == 1
    assert requests == []


@pytest.mark.asyncio
async def test_substituted_schema_or_recipe_is_rejected_before_resolution() -> None:
    provider, resolver = _provider(lambda _request: pytest.fail("unexpected provider call"))
    substituted = TelemetryEvidenceRecipe(
        recipe_id="requests.failed",
        version="1.0.0",
        mechanism=TelemetryMechanism.FAILED_REQUESTS,
        output_schema_digest=f"sha256:{'f' * 64}",
        estimated_cost_units=10,
        default_lookback=TelemetryLookbackProfile.FIFTEEN_MINUTES,
        supports_no_data_refutation=True,
    )

    with pytest.raises(ValueError, match="substituted output schema"):
        await provider.gather(_need(substituted))
    with pytest.raises(ValueError, match="reviewed catalog"):
        await provider.gather(
            _need(replace(substituted, recipe_id="caller.supplied", version="9.0.0"))
        )

    assert resolver.calls == 0


@pytest.mark.asyncio
async def test_malformed_or_future_aggregate_is_unavailable_without_facts() -> None:
    provider, _ = _provider(
        lambda _request: httpx.Response(
            200,
            json=_table([[1, "2026-09-16T12:01:00Z", "low"]]),
        )
    )

    receipt = await provider.gather(_need())

    assert receipt.disposition is TelemetryEvidenceDisposition.UNAVAILABLE
    assert receipt.fact_tokens == ()
