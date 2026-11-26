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

import fdai_cost_governance.scheduled_analytics as scheduled_analytics
from fdai_cost_governance.scheduled_analytics import (
    AnalyticsSourceError,
    AzureAnalyticsBatch,
    AzureScheduledAnalyticsSource,
    ScheduledAnalyticsResult,
    _mapping_items,
    _require_management_url,
    _subscription_id,
    _usage_item,
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


@pytest.mark.asyncio
async def test_azure_source_utilization_pagination_and_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="subscriptions/<id>"):
        _subscription_id("invalid-scope")
    with pytest.raises(AnalyticsSourceError, match="invalid_next_link"):
        _require_management_url("http://management.azure.com/bad")
    with pytest.raises(AnalyticsSourceError, match="invalid_source_payload"):
        _usage_item({"UsageDate": "20260916", "ServiceName": "Compute", "Currency": "USD"})
    with pytest.raises(AnalyticsSourceError, match="invalid_source_payload"):
        _usage_item(
            {
                "UsageDate": "bad-date",
                "ServiceName": "Compute",
                "Currency": "USD",
                "Cost": 1,
            }
        )
    assert _mapping_items("not-a-list") == []

    async with httpx.AsyncClient() as empty_client:
        expired_source = AzureScheduledAnalyticsSource(
            client=empty_client,
            credential=_Credential(),
            clock=lambda: NOW,
        )
        with pytest.raises(AnalyticsSourceError, match="deadline_exceeded"):
            await expired_source.collect(
                scope_id="subscriptions/example",
                start_at=NOW - timedelta(days=1),
                end_at=NOW,
                deadline_at=NOW,
            )

        class _TimeoutCred:
            async def access_token(self, *, deadline_at: datetime) -> str:
                raise TimeoutError

        class _ErrorCred:
            async def access_token(self, *, deadline_at: datetime) -> str:
                raise RuntimeError("no cred")

        for cred, expected in (
            (_TimeoutCred(), "deadline_exceeded"),
            (_ErrorCred(), "credential_unavailable"),
        ):
            src = AzureScheduledAnalyticsSource(
                client=empty_client,
                credential=cred,
                clock=lambda: NOW,
            )
            with pytest.raises(AnalyticsSourceError, match=expected):
                await src.collect(
                    scope_id="subscriptions/example",
                    start_at=NOW - timedelta(days=1),
                    end_at=NOW,
                    deadline_at=NOW + timedelta(minutes=1),
                )

    monkeypatch.setattr(scheduled_analytics, "_MAX_RECOMMENDATIONS", 1)

    def partial_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "Microsoft.CostManagement/query" in url:
            if "page=2" not in url:
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
                            "nextLink": (
                                "https://management.azure.com/subscriptions/example"
                                "/providers/Microsoft.CostManagement/query?page=2"
                            ),
                        }
                    },
                )
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
                        "rows": [["Storage", 1, 20260916, "USD"]],
                    }
                },
            )
        if "Microsoft.Consumption/budgets" in url:
            return httpx.Response(404, json={})
        if "Microsoft.Advisor/recommendations" in url:
            if "page=2" not in url:
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {
                                "id": "/rec/1",
                                "properties": {
                                    "impactedField": "Microsoft.ContainerService/managedClusters",
                                    "resourceMetadata": {
                                        "resourceId": "/subscriptions/example/clusters/c1"
                                    },
                                },
                            },
                            {
                                "id": "/rec/2",
                                "properties": {
                                    "impactedField": "Microsoft.ContainerService/managedClusters",
                                    "resourceMetadata": {
                                        "resourceId": "/subscriptions/other/clusters/c2"
                                    },
                                },
                            },
                        ],
                        "nextLink": (
                            "https://management.azure.com/subscriptions/example"
                            "/providers/Microsoft.Advisor/recommendations?page=2"
                        ),
                    },
                )
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "/rec/3",
                            "properties": {"impactedField": "Microsoft.Compute/disks"},
                        }
                    ]
                },
            )
        if "microsoft.insights/metrics" in url:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "timeseries": [
                                {"data": [{"average": 33.5}]},
                            ]
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"value": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(partial_handler)) as client:
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
        assert "budgets_unavailable" in batch.limitations
        assert "advisor_recommendation_limit" in batch.limitations
        assert batch.utilization_by_resource["/subscriptions/example/clusters/c1"] == Decimal(
            "33.50"
        )

        _, util_complete = await source._utilization(
            subscription_id="example",
            advisor_items=(
                {
                    "properties": {
                        "impactedField": "Microsoft.ContainerService/managedClusters",
                        "impactedValue": "/subscriptions/other/clusters/c2",
                    }
                },
            ),
            start_at=NOW - timedelta(days=1),
            end_at=NOW,
            token="tok",
            deadline_at=NOW + timedelta(minutes=1),
        )
        assert util_complete is False

        with pytest.raises(AnalyticsSourceError, match="deadline_exceeded"):
            await source._get_json(
                source="s",
                url="https://management.azure.com/x",
                params=None,
                token="t",
                deadline_at=NOW,
            )
        with pytest.raises(AnalyticsSourceError, match="deadline_exceeded"):
            await source._post_json(
                source="s",
                url="https://management.azure.com/x",
                payload={},
                token="t",
                deadline_at=NOW,
            )

    for status, body, expected_reason in (
        (503, b"{}", "provider_unavailable"),
        (500, b"{}", "source_unavailable"),
        (200, b"{bad", "invalid_source_payload"),
        (200, b"[]", "invalid_source_payload"),
    ):
        transport = httpx.MockTransport(lambda req, s=status, b=body: httpx.Response(s, content=b))
        async with httpx.AsyncClient(transport=transport) as err_client:
            err_src = AzureScheduledAnalyticsSource(
                client=err_client,
                credential=_Credential(),
                clock=lambda: NOW,
            )
            with pytest.raises(AnalyticsSourceError, match=expected_reason):
                await err_src._get_json(
                    source="s",
                    url="https://management.azure.com/x",
                    params=None,
                    token="t",
                    deadline_at=NOW + timedelta(minutes=1),
                )
            with pytest.raises(AnalyticsSourceError, match=expected_reason):
                await err_src._post_json(
                    source="s",
                    url="https://management.azure.com/x",
                    payload={},
                    token="t",
                    deadline_at=NOW + timedelta(minutes=1),
                )

    def _raise_http(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    async with httpx.AsyncClient(transport=httpx.MockTransport(_raise_http)) as net_client:
        net_src = AzureScheduledAnalyticsSource(
            client=net_client,
            credential=_Credential(),
            clock=lambda: NOW,
        )
        with pytest.raises(AnalyticsSourceError, match="transport_error"):
            await net_src._get_json(
                source="s",
                url="https://management.azure.com/x",
                params=None,
                token="t",
                deadline_at=NOW + timedelta(minutes=1),
            )
        with pytest.raises(AnalyticsSourceError, match="transport_error"):
            await net_src._post_json(
                source="s",
                url="https://management.azure.com/x",
                payload={},
                token="t",
                deadline_at=NOW + timedelta(minutes=1),
            )


@pytest.mark.asyncio
async def test_run_scheduled_analytics_failure_modes_and_publisher() -> None:
    with pytest.raises(ValueError, match="days MUST be in"):
        await run_scheduled_analytics(
            config=_config(),
            scope_id="subscriptions/example",
            venue="local",
            days=0,
            source=_Source(),  # type: ignore[arg-type]
            store=_Store(),
        )

    store_mismatch = _Store()
    store_mismatch.activation = replace(
        store_mismatch.activation,
        ontology_release_id="other:release",
    )
    res_mismatch = await run_scheduled_analytics(
        config=_config(),
        scope_id="subscriptions/example",
        venue="local",
        days=1,
        source=_Source(),  # type: ignore[arg-type]
        store=store_mismatch,
        clock=lambda: NOW,
    )
    assert res_mismatch.receipt.failure_reason == "activation_revision_mismatch"

    class _ConflictStore(_Store):
        async def append_cost_page(self, page: object, **_: object) -> bool:
            return False

    res_conflict = await run_scheduled_analytics(
        config=_config(),
        scope_id="subscriptions/example",
        venue="local",
        days=1,
        source=_Source(),  # type: ignore[arg-type]
        store=_ConflictStore(),
        clock=lambda: NOW,
    )
    assert res_conflict.receipt.failure_reason == "observation_cursor_conflict"

    publisher = _Publisher()
    res_pub = await run_scheduled_analytics(
        config=_config(),
        scope_id="subscriptions/example",
        venue="local",
        days=1,
        source=_Source(),  # type: ignore[arg-type]
        store=_Store(),
        publisher=publisher,
        clock=lambda: NOW,
    )
    assert res_pub.published == 1

    class _CursorFailStore(_Store):
        async def advance_cost_analysis_cursor(self, **_: object) -> bool:
            return False

    res_pub_fail = await run_scheduled_analytics(
        config=_config(),
        scope_id="subscriptions/example",
        venue="local",
        days=1,
        source=_Source(),  # type: ignore[arg-type]
        store=_CursorFailStore(),
        publisher=_Publisher(),
        clock=lambda: NOW,
    )
    assert res_pub_fail.receipt.failure_reason == "analysis_publish_failed"

    for raised_exc, expected_reason in (
        (TimeoutError(), "deadline_exceeded"),
        (ValueError("bad"), "invalid_source_payload"),
        (RuntimeError("db"), "persistence_unavailable"),
        (KeyError("missing"), "internal_error"),
    ):

        class _ErrSrc:
            def __init__(self, err: Exception) -> None:
                self._err = err

            async def collect(self, **_: object) -> AzureAnalyticsBatch:
                raise self._err

        res_err = await run_scheduled_analytics(
            config=_config(),
            scope_id="subscriptions/example",
            venue="local",
            days=1,
            source=_ErrSrc(raised_exc),  # type: ignore[arg-type]
            store=_Store(),
            clock=lambda: NOW,
        )
        assert res_err.receipt.failure_reason == expected_reason
