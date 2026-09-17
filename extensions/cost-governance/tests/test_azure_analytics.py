"""Azure Cost Governance analytics normalization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fdai_cost_governance.azure_analytics import (
    analytics_identity,
    build_azure_cost_analytics,
    build_usage_observations,
    percentile_95,
    usage_has_negative_costs,
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
