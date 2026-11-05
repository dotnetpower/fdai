"""Azure Cost Governance analytics normalization tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fdai.shared.providers.cost_governance import CostCollectionRequest

from fdai_cost_governance.azure_analytics import (
    _budget,
    _decimal,
    _recommendation,
    analytics_identity,
    build_azure_cost_analytics,
    build_usage_observations,
    percentile_95,
    usage_has_negative_costs,
)
from fdai_cost_governance.azure_focus import (
    AzureFocusObservationAdapter,
    CostHttpResponse,
    decode_cost_query_rows,
)

NOW = datetime(2026, 8, 31, tzinfo=UTC)


def test_builds_safe_trend_budget_and_candidate_recommendation() -> None:
    projection = build_azure_cost_analytics(
        usage_items=(
            {
                "properties": {
                    "date": "2026-08-30T00:00:00Z",
                    "serviceFamily": "Compute",
                    "billingCurrencyCode": "USD",
                    "costInBillingCurrency": 12.5,
                }
            },
            {
                "properties": {
                    "date": "2026-08-30T00:00:00Z",
                    "serviceFamily": "Compute",
                    "billingCurrencyCode": "USD",
                    "costInBillingCurrency": 7.5,
                }
            },
        ),
        budget_items=(
            {
                "id": "/subscriptions/private/providers/budgets/primary",
                "properties": {
                    "amount": 100,
                    "currentSpend": {"amount": 20, "unit": "USD"},
                    "forecastSpend": {"amount": 80, "unit": "USD"},
                    "timeGrain": "Monthly",
                },
            },
        ),
        advisor_items=(
            {
                "id": "/private/recommendation/one",
                "impact": "Medium",
                "impactedField": "Microsoft.Compute/disks",
                "resourceMetadata": {"resourceId": "/subscriptions/private/disks/one"},
                "shortDescription": {
                    "problem": "Unattached disk",
                    "solution": "Review whether the disk is needed",
                },
                "extendedProperties": {
                    "annualSavingsAmount": "120",
                    "savingsCurrency": "USD",
                    "skuName": "P30",
                },
            },
        ),
        utilization_by_resource={
            "/subscriptions/private/disks/one": Decimal("12.34"),
        },
        observed_at=NOW,
        complete=True,
    )

    assert projection.trend[0].amount == Decimal("20")
    assert projection.budgets[0].forecast_spend == Decimal("80")
    assert projection.recommendations[0].monthly_savings == Decimal("10.00")
    assert projection.recommendations[0].resource_ref is not None
    assert projection.recommendations[0].resource_ref.startswith("resource:")
    assert "private" not in str(projection.model_dump(mode="json"))
    snapshot_id, evidence_digest = analytics_identity(
        projection,
        package_id="cost-governance",
        scope_id="subscriptions/example",
    )
    assert snapshot_id.startswith("analytics:")
    assert evidence_digest == snapshot_id.replace("analytics:", "sha256:")


def test_normalizes_advisor_rest_properties_without_retaining_resource_id() -> None:
    projection = build_azure_cost_analytics(
        usage_items=(),
        budget_items=(),
        advisor_items=(
            {
                "id": "/recommendations/one",
                "properties": {
                    "impact": "High",
                    "impactedField": "Microsoft.ContainerService/managedClusters",
                    "impactedValue": "/subscriptions/private/managedClusters/one",
                    "shortDescription": {
                        "problem": "Oversized cluster",
                        "solution": "Use a smaller compatible node SKU",
                    },
                    "extendedProperties": {
                        "annualSavingsAmount": "240",
                        "savingsCurrency": "USD",
                        "skuName": "Standard_D4s_v5",
                        "displaySKU": "Standard_D2s_v5",
                    },
                },
            },
        ),
        utilization_by_resource={
            "/subscriptions/private/managedclusters/one": Decimal("17.5"),
        },
        observed_at=NOW,
        complete=True,
    )

    recommendation = projection.recommendations[0]
    assert recommendation.current_sku == "Standard_D4s_v5"
    assert recommendation.target_sku == "Standard_D2s_v5"
    assert recommendation.utilization_percent == Decimal("17.5")
    assert "subscriptions/private" not in repr(recommendation)


def test_percentile_95_ignores_invalid_values() -> None:
    assert percentile_95([1, 2, 3, float("nan"), -1]) == Decimal("3.00")
    assert percentile_95([]) is None


def test_builds_scope_bound_complete_agent_observations() -> None:
    items = (
        {
            "properties": {
                "date": "2026-08-30T00:00:00Z",
                "serviceFamily": "Compute",
                "billingCurrencyCode": "USD",
                "costInBillingCurrency": 12.5,
            }
        },
        {
            "properties": {
                "date": "2026-08-30T00:00:00Z",
                "serviceFamily": "Compute",
                "billingCurrencyCode": "USD",
                "costInBillingCurrency": 7.5,
            }
        },
    )
    observations = build_usage_observations(
        package_id="cost-governance",
        scope_id="subscriptions/example",
        usage_items=items,
        collected_at=NOW,
        ontology_release_id="ontology:test",
        ontology_release_digest=f"sha256:{'a' * 64}",
        complete=True,
    )

    assert len(observations) == 1
    assert observations[0].amount == Decimal("20")
    assert observations[0].completeness == Decimal("1")
    assert observations[0].source_uri.startswith("cost-service:")
    assert usage_has_negative_costs(items) is False


def test_agent_observations_exclude_currency_without_authoritative_usd_conversion() -> None:
    observations = build_usage_observations(
        package_id="cost-governance",
        scope_id="subscriptions/example",
        usage_items=(
            {
                "properties": {
                    "date": "2026-08-30T00:00:00Z",
                    "serviceFamily": "Compute",
                    "billingCurrencyCode": "EUR",
                    "costInBillingCurrency": 12.5,
                }
            },
        ),
        collected_at=NOW,
        ontology_release_id="ontology:test",
        ontology_release_digest=f"sha256:{'a' * 64}",
        complete=True,
    )

    assert observations == ()


def test_budget_limit_is_explicit_and_scope_changes_identity() -> None:
    budgets = tuple(
        {
            "id": f"/budgets/{index}",
            "properties": {
                "amount": index + 1,
                "currentSpend": {"amount": 1, "unit": "USD"},
                "timeGrain": "Monthly",
            },
        }
        for index in range(33)
    )
    projection = build_azure_cost_analytics(
        usage_items=(),
        budget_items=budgets,
        advisor_items=(),
        utilization_by_resource={},
        observed_at=NOW,
        complete=True,
    )

    assert len(projection.budgets) == 32
    assert projection.complete is False
    assert projection.limitations == ("budget_limit",)
    first = analytics_identity(
        projection,
        package_id="cost-governance",
        scope_id="subscriptions/one",
    )
    second = analytics_identity(
        projection,
        package_id="cost-governance",
        scope_id="subscriptions/two",
    )
    assert first != second


def test_azure_analytics_edge_cases_and_limits() -> None:
    assert _decimal(True) is None
    assert _decimal("not-a-decimal") is None
    assert _decimal("NaN") is None
    assert _budget({"properties": {"amount": 0}}) is None
    assert (
        _budget(
            {
                "properties": {
                    "amount": 10,
                    "currentSpend": {"amount": 1, "unit": "USD"},
                }
            }
        )
        is None
    )
    assert _recommendation({}, utilization_by_resource={}, observed_at=NOW) is None

    rec_low = _recommendation(
        {
            "id": "/rec/low",
            "impact": "Low",
            "shortDescription": {"problem": "p", "solution": "s"},
            "extendedProperties": {"savingsCurrency": "US"},
        },
        utilization_by_resource={},
        observed_at=NOW,
    )
    assert rec_low is not None and rec_low.impact == "Low" and rec_low.currency is None

    rec_unknown = _recommendation(
        {
            "id": "/rec/unk",
            "impact": "Custom",
            "shortDescription": {"problem": "p", "solution": "s"},
        },
        utilization_by_resource={},
        observed_at=NOW,
    )
    assert rec_unknown is not None and rec_unknown.impact == "Unknown"

    many_recs = tuple(
        {
            "id": f"/rec/{i}",
            "impact": "Medium",
            "shortDescription": {"problem": "p", "solution": "s"},
        }
        for i in range(201)
    )
    proj = build_azure_cost_analytics(
        usage_items=(),
        budget_items=(),
        advisor_items=many_recs,
        utilization_by_resource={},
        observed_at=NOW,
        complete=True,
    )
    assert len(proj.recommendations) == 200
    assert "advisor_recommendation_limit" in proj.limitations

    future_obs = build_usage_observations(
        package_id="cost-governance",
        scope_id="subscriptions/example",
        usage_items=(
            {
                "properties": {
                    "date": "2026-09-05T00:00:00Z",
                    "serviceFamily": "Compute",
                    "billingCurrencyCode": "USD",
                    "costInBillingCurrency": 5,
                }
            },
        ),
        collected_at=NOW,
        ontology_release_id="ontology:test",
        ontology_release_digest=f"sha256:{'a' * 64}",
        complete=True,
    )
    assert future_obs == ()


async def test_azure_focus_adapter_and_row_decoder_branches() -> None:
    with pytest.raises(ValueError, match="finite and nonnegative"):
        CostHttpResponse(status_code=200, body=b"{}", retry_after_seconds=-1.0)

    class _Cred:
        async def access_token(self, *, deadline_at: datetime) -> str:
            return "tok"

    responses: list[CostHttpResponse] = []

    class _Transport:
        async def post(self, url: str, **kwargs: object) -> CostHttpResponse:
            return responses.pop(0)

    with pytest.raises(ValueError, match="max_response_bytes"):
        AzureFocusObservationAdapter(
            transport=_Transport(),
            credential=_Cred(),
            ontology_release_id="rel",
            ontology_release_digest=f"sha256:{'a' * 64}",
            max_response_bytes=0,
        )
    with pytest.raises(ValueError, match="max_rate_limit_retries"):
        AzureFocusObservationAdapter(
            transport=_Transport(),
            credential=_Cred(),
            ontology_release_id="rel",
            ontology_release_digest=f"sha256:{'a' * 64}",
            max_rate_limit_retries=4,
        )

    adapter = AzureFocusObservationAdapter(
        transport=_Transport(),
        credential=_Cred(),
        ontology_release_id="rel",
        ontology_release_digest=f"sha256:{'a' * 64}",
        max_response_bytes=500,
        clock=lambda: NOW,
    )
    req = CostCollectionRequest(
        package_id="cost-governance",
        scope_id="subscriptions/example",
        start_at=NOW - timedelta(days=2),
        end_at=NOW,
        page_size=10,
        deadline_at=NOW + timedelta(minutes=5),
    )

    with pytest.raises(ValueError, match="continuation URL is not authoritative"):
        await adapter.collect_cost_page(req, resume_token="http://evil.invalid/next")

    responses.append(CostHttpResponse(status_code=200, body=b"x" * 600))
    with pytest.raises(RuntimeError, match="exceeded byte budget"):
        await adapter.collect_cost_page(req, resume_token=None)

    responses.append(CostHttpResponse(status_code=200, body=b"{bad"))
    with pytest.raises(ValueError, match="invalid JSON"):
        await adapter.collect_cost_page(req, resume_token=None)

    valid_doc = {
        "properties": {
            "columns": [
                {"name": "ServiceName"},
                {"name": "Cost"},
                {"name": "UsageDate"},
                {"name": "Currency"},
            ],
            "rows": [["Compute", 10, "20260830", "USD"]],
            "nextLink": "https://management.azure.com/next",
        }
    }
    responses.append(CostHttpResponse(status_code=200, body=json.dumps(valid_doc).encode()))
    page = await adapter.collect_cost_page(
        req,
        resume_token="https://management.azure.com/start",
    )
    assert page.complete is False
    assert page.next_resume_token == "https://management.azure.com/next"

    with pytest.raises(ValueError, match="invalid amount or time"):
        adapter._observation(
            req,
            {"ServiceName": "Compute", "Cost": "bad", "UsageDate": "20260830", "Currency": "USD"},
            NOW,
        )
    with pytest.raises(ValueError, match="outside the observed collection window"):
        adapter._observation(
            req,
            {"ServiceName": "Compute", "Cost": 1, "UsageDate": "20260905", "Currency": "USD"},
            NOW,
        )

    for bad_doc, match in (
        ("not-a-dict", "response is invalid"),
        ({"properties": "bad"}, "properties are invalid"),
        ({"properties": {"rows": "bad"}}, "exceeded row budget"),
        ({"properties": {"columns": "bad", "rows": []}}, "columns are invalid"),
        ({"properties": {"columns": [{}], "rows": []}}, "columns are invalid"),
        (
            {
                "properties": {
                    "columns": [{"name": "ServiceName"}],
                    "rows": [["a", "b"]],
                }
            },
            "rows are invalid",
        ),
    ):
        with pytest.raises(ValueError, match=match):
            decode_cost_query_rows(bad_doc, page_size=5)
