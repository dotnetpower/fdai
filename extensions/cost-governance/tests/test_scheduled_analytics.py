from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fdai.shared.providers.cost_governance import CostPackageActivation
from fdai_service_contracts import (
    CostAnalyticsRunReceipt,
    CostEvidenceSourceFacet,
    CostEvidenceState,
)

from fdai_cost_governance.scheduled_analytics import (
    AnalyticsSourceError,
    AzureAnalyticsBatch,
    AzureScheduledAnalyticsSource,
    ScheduledAnalyticsResult,
    run_scheduled_analytics,
)
from fdai_cost_governance.service import CostJobConfig

NOW = datetime(2026, 9, 17, 1, tzinfo=UTC)
DIGEST = f"sha256:{'a' * 64}"


class _Store:
    def __init__(self, *, enabled: bool = True) -> None:
        self.activation = CostPackageActivation(
            vertical_id="cost-governance",
            package_id="cost-governance",
            available=True,
            enabled=enabled,
            availability_reasons=(),
            package_version="0.1.0",
            image_digest=DIGEST,
            asset_manifest_digest=DIGEST,
            semantic_profile_digest=DIGEST,
            revision=4,
            effective_at=NOW,
            ontology_release_id="ontology:test",
            ontology_release_digest=DIGEST,
            source_authority="activation-store",
        )
        self.pages: list[object] = []
        self.snapshots: list[dict[str, object]] = []
        self.receipts: list[CostAnalyticsRunReceipt] = []

    async def read_cost_activation(self, package_id: str) -> CostPackageActivation:
        assert package_id == "cost-governance"
        return self.activation

    async def read_cost_cursor(self, package_id: str, scope_id: str) -> object:
        del package_id, scope_id
        return SimpleNamespace(
            revision=0,
            analysis_revision=0,
            last_published_at=None,
            last_published_observation_id=None,
        )

    async def append_cost_page(self, page: object, **_: object) -> bool:
        self.pages.append(page)
        return True

    async def append_cost_analytics_snapshot(self, **kwargs: object) -> bool:
        self.snapshots.append(kwargs)
        return True

    async def append_cost_analytics_run_receipt(
        self,
        receipt: CostAnalyticsRunReceipt,
        *,
        scope_id: str,
    ) -> bool:
        assert scope_id == "subscriptions/example"
        self.receipts.append(receipt)
        return True

    async def read_cost_observations(self, **_: object) -> tuple[object, ...]:
        if not self.pages:
            return ()
        return self.pages[-1].observations

    async def advance_cost_analysis_cursor(self, **_: object) -> bool:
        return True


class _Source:
    async def collect(self, **_: object) -> AzureAnalyticsBatch:
        source = CostEvidenceSourceFacet(
            source_authority="azure-consumption-usage-details",
            state=CostEvidenceState.COMPLETE,
            window_start_at=NOW - timedelta(days=1),
            window_end_at=NOW,
            latest_source_at=NOW,
            complete_count=1,
        )
        return AzureAnalyticsBatch(
            usage_items=(
                {
                    "properties": {
                        "date": "2026-09-16T00:00:00Z",
                        "serviceFamily": "Compute",
                        "billingCurrencyCode": "USD",
                        "costInBillingCurrency": 2,
                    }
                },
            ),
            budget_items=(),
            advisor_items=(),
            utilization_by_resource={},
            usage_complete=True,
            usage_bytes=128,
            sources=(source,),
            limitations=(),
            collected_at=NOW,
        )


class _FailingSource:
    async def collect(self, **_: object) -> AzureAnalyticsBatch:
        raise AnalyticsSourceError("usage-details", "provider_unavailable")


class _NegativeSource(_Source):
    async def collect(self, **kwargs: object) -> AzureAnalyticsBatch:
        batch = await super().collect(**kwargs)
        return replace(
            batch,
            usage_items=(
                *batch.usage_items,
                {
                    "properties": {
                        "date": "2026-09-16T00:00:00Z",
                        "serviceFamily": "Compute",
                        "billingCurrencyCode": "USD",
                        "costInBillingCurrency": -1,
                    }
                },
            ),
        )


class _Publisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish_cost_sample(self, observation: object, **_: object) -> None:
        self.published.append(observation)


class _Credential:
    async def access_token(self, *, deadline_at: datetime) -> str:
        assert deadline_at > NOW
        return "test-token"  # noqa: S105 - synthetic credential fixture


def _config() -> CostJobConfig:
    return CostJobConfig(
        package_id="cost-governance",
        ontology_release_id="ontology:test",
        ontology_release_digest=DIGEST,
        known_service_ids=frozenset({"scheduled-analytics"}),
    )


@pytest.mark.asyncio
async def test_shared_schedule_persists_snapshot_and_complete_receipt() -> None:
    store = _Store()
    times = iter((NOW, NOW + timedelta(minutes=1)))

    result = await run_scheduled_analytics(
        config=_config(),
        scope_id="subscriptions/example",
        venue="local",
        days=1,
        source=_Source(),
        store=store,
        clock=lambda: next(times),
    )

    assert isinstance(result, ScheduledAnalyticsResult)
    assert result.receipt.status.value == "complete"
    assert result.receipt.observation_count == 1
    assert result.receipt.scope_digest.startswith("sha256:")
    assert result.receipt.run_id.removeprefix("costrun:") == (
        result.receipt.receipt_digest.removeprefix("sha256:")
    )
    assert len(store.pages) == 1
    assert len(store.snapshots) == 1
    assert store.receipts == [result.receipt]
    payload = store.snapshots[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["window_start_at"] == "2026-09-16T01:00:00Z"
    assert "decision" not in payload
    assert "settlement" not in payload


@pytest.mark.asyncio
async def test_source_failure_is_visible_in_a_durable_content_free_receipt() -> None:
    store = _Store()
    times = iter((NOW, NOW + timedelta(seconds=2)))

    result = await run_scheduled_analytics(
        config=_config(),
        scope_id="subscriptions/example",
        venue="deployed",
        days=1,
        source=_FailingSource(),
        store=store,
        clock=lambda: next(times),
    )

    assert result.receipt.status.value == "failed"
    assert result.receipt.failure_reason == "provider_unavailable"
    assert result.receipt.sources[0].state is CostEvidenceState.UNAVAILABLE
    assert store.pages == []
    assert store.snapshots == []
    assert store.receipts == [result.receipt]
    assert "subscriptions/example" not in repr(result.receipt)


@pytest.mark.asyncio
async def test_negative_costs_make_facts_and_page_partial_and_publish_nothing() -> None:
    store = _Store()
    publisher = _Publisher()
    times = iter((NOW, NOW + timedelta(seconds=2)))

    result = await run_scheduled_analytics(
        config=_config(),
        scope_id="subscriptions/example",
        venue="deployed",
        days=1,
        source=_NegativeSource(),
        store=store,
        publisher=publisher,
        clock=lambda: next(times),
    )

    page = store.pages[0]
    assert page.complete is False
    assert {item.completeness for item in page.observations} == {Decimal("0.5")}
    assert result.receipt.status.value == "partial"
    assert "negative_cost_unsupported" in result.receipt.limitations
    usage_source = next(
        item
        for item in result.receipt.sources
        if item.source_authority == "azure-consumption-usage-details"
    )
    assert usage_source.state is CostEvidenceState.PARTIAL
    assert usage_source.reason == "negative_cost_unsupported"
    assert result.published == 0
    assert publisher.published == []


@pytest.mark.asyncio
async def test_disabled_package_records_no_source_reads_or_snapshot() -> None:
    store = _Store(enabled=False)
    times = iter((NOW, NOW + timedelta(seconds=1)))

    result = await run_scheduled_analytics(
        config=_config(),
        scope_id="subscriptions/example",
        venue="local",
        days=1,
        source=_FailingSource(),
        store=store,
        clock=lambda: next(times),
    )

    assert result.receipt.status.value == "disabled"
    assert result.receipt.failure_reason is None
    assert result.receipt.snapshot_id is None
    assert store.receipts == [result.receipt]


@pytest.mark.asyncio
async def test_azure_source_reports_each_authoritative_source_without_raw_identity() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "Microsoft.CostManagement/query" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "properties": {
                        "columns": [
                            {"name": "ServiceName"},
                            {"name": "Cost"},
                            {"name": "UsageDate"},
                            {"name": "Currency"},
                        ],
                        "rows": [["Compute", 2, 20260916, "USD"]],
                    }
                },
            )
        return httpx.Response(200, json={"value": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AzureScheduledAnalyticsSource(
            client=client,
            credential=_Credential(),
            clock=lambda: NOW,
        )
        batch = await source.collect(
            scope_id="subscriptions/example",
            start_at=NOW - timedelta(days=1),
            end_at=NOW,
            deadline_at=NOW + timedelta(days=1),
        )

    assert {item.source_authority for item in batch.sources} == {
        "azure-cost-management-query",
        "azure-consumption-budgets",
        "azure-advisor",
        "azure-monitor",
    }
    assert all(item.state is CostEvidenceState.COMPLETE for item in batch.sources)
    assert "subscriptions/example" not in repr(batch.sources)
    query_request = next(
        item for item in requests if "Microsoft.CostManagement/query" in str(item.url)
    )
    assert query_request.method == "POST"
    assert "startDate" not in str(query_request.url)
    assert batch.usage_items[0]["properties"]["date"] == "2026-09-16"


@pytest.mark.asyncio
async def test_azure_source_stops_on_optional_source_rate_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "Microsoft.CostManagement/query" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "properties": {
                        "columns": [
                            {"name": "ServiceName"},
                            {"name": "Cost"},
                            {"name": "UsageDate"},
                            {"name": "Currency"},
                        ],
                        "rows": [],
                    }
                },
            )
        return httpx.Response(429, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = AzureScheduledAnalyticsSource(
            client=client,
            credential=_Credential(),
            clock=lambda: NOW,
        )
        with pytest.raises(AnalyticsSourceError, match="provider_rate_limited"):
            await source.collect(
                scope_id="subscriptions/example",
                start_at=NOW - timedelta(days=1),
                end_at=NOW,
                deadline_at=NOW + timedelta(days=1),
            )
