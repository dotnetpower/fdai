"""Build disclosure-safe Cost Governance analytics from authoritative Azure reads."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from fdai.shared.providers.cost_governance import CostObservation
from fdai_service_contracts import (
    CostAnalyticsBudget,
    CostAnalyticsProjection,
    CostAnalyticsRecommendation,
    CostAnalyticsTrendPoint,
)

SOURCE_AUTHORITY = "azure-cost-management-budget-advisor"


def build_azure_cost_analytics(
    *,
    usage_items: Sequence[Mapping[str, Any]],
    budget_items: Sequence[Mapping[str, Any]],
    advisor_items: Sequence[Mapping[str, Any]],
    utilization_by_resource: Mapping[str, Decimal],
    observed_at: datetime,
    complete: bool,
    limitations: Sequence[str] = (),
) -> CostAnalyticsProjection:
    """Normalize bounded Azure responses without retaining resource identities."""

    service_daily = _service_daily_costs(usage_items)
    daily: defaultdict[tuple[str, str], Decimal] = defaultdict(Decimal)
    completeness = Decimal("1") if complete else Decimal("0.5")
    for (day, _service, currency), amount in service_daily.items():
        daily[(day, currency)] += amount
    trend = tuple(
        CostAnalyticsTrendPoint(
            observed_on=datetime.strptime(day, "%Y-%m-%d").date(),
            amount=amount,
            currency=currency,
            completeness=completeness,
        )
        for (day, currency), amount in sorted(daily.items())
    )

    normalized_budgets = [budget for item in budget_items if (budget := _budget(item)) is not None]
    bounded_limitations = set(limitations)
    normalized_budgets.sort(key=lambda item: item.amount, reverse=True)
    if len(normalized_budgets) > 32:
        normalized_budgets = normalized_budgets[:32]
        bounded_limitations.add("budget_limit")
    normalized_recommendations = [
        recommendation
        for item in advisor_items
        if (
            recommendation := _recommendation(
                item,
                utilization_by_resource=utilization_by_resource,
                observed_at=observed_at,
            )
        )
        is not None
    ]
    normalized_recommendations.sort(
        key=lambda item: item.monthly_savings or Decimal(),
        reverse=True,
    )
    if len(normalized_recommendations) > 200:
        normalized_recommendations = normalized_recommendations[:200]
        bounded_limitations.add("advisor_recommendation_limit")
    return CostAnalyticsProjection(
        source_authority=SOURCE_AUTHORITY,
        observed_at=observed_at,
        complete=complete and not bounded_limitations,
        trend=trend,
        budgets=tuple(normalized_budgets),
        recommendations=tuple(normalized_recommendations),
        limitations=tuple(sorted(bounded_limitations)),
    )


def build_usage_observations(
    *,
    package_id: str,
    scope_id: str,
    usage_items: Sequence[Mapping[str, Any]],
    collected_at: datetime,
    ontology_release_id: str,
    ontology_release_digest: str,
    complete: bool,
) -> tuple[CostObservation, ...]:
    """Build complete service-day facts for the existing typed agent ingress."""

    completeness = Decimal("1") if complete else Decimal("0.5")
    observations: list[CostObservation] = []
    for (day, service, currency), amount in sorted(_service_daily_costs(usage_items).items()):
        if currency != "USD":
            continue
        start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)
        end = min(start + timedelta(days=1), collected_at)
        if end <= start:
            continue
        material = json.dumps(
            {
                "package_id": package_id,
                "scope_id": scope_id,
                "day": day,
                "service": service,
                "currency": currency,
                "amount": str(amount),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        digest = hashlib.sha256(material).hexdigest()
        observations.append(
            CostObservation(
                observation_id=f"costobs:{digest}",
                package_id=package_id,
                scope_id=scope_id,
                service_id=service,
                amount=amount,
                currency=currency,
                event_start_at=start,
                event_end_at=end,
                observed_at=end,
                recorded_at=collected_at,
                source_authority="azure-consumption-usage-details",
                source_uri=f"cost-service:{_short_digest(f'{scope_id}:{service}')}",
                completeness=completeness,
                ontology_release_id=ontology_release_id,
                ontology_release_digest=ontology_release_digest,
                evidence_digest=f"sha256:{digest}",
                retention_until=collected_at + timedelta(days=400),
            )
        )
    return tuple(observations)


def usage_has_negative_costs(usage_items: Sequence[Mapping[str, Any]]) -> bool:
    """Return whether the nonnegative observation contract excludes any charge."""

    return any(
        amount is not None and amount < 0
        for item in usage_items
        if (amount := _decimal(_mapping(item.get("properties")).get("costInBillingCurrency")))
        is not None
    )


def analytics_identity(
    projection: CostAnalyticsProjection,
    *,
    package_id: str,
    scope_id: str,
) -> tuple[str, str]:
    """Return stable snapshot and evidence digests over canonical safe content."""

    encoded = json.dumps(
        {
            "package_id": package_id,
            "scope_id": scope_id,
            "projection": projection.model_dump(mode="json"),
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    return f"analytics:{digest}", f"sha256:{digest}"


def percentile_95(values: Sequence[float]) -> Decimal | None:
    """Return the bounded nearest-rank p95 for provider metric samples."""

    finite = sorted(value for value in values if math.isfinite(value) and value >= 0)
    if not finite:
        return None
    index = max(0, math.ceil(len(finite) * 0.95) - 1)
    return Decimal(str(finite[index])).quantize(Decimal("0.01"))


def _budget(item: Mapping[str, Any]) -> CostAnalyticsBudget | None:
    properties = _mapping(item.get("properties"))
    amount = _decimal(properties.get("amount"))
    current = _mapping(properties.get("currentSpend"))
    current_spend = _decimal(current.get("amount"))
    currency = str(current.get("unit") or "").strip().upper()
    if amount is None or amount <= 0 or current_spend is None or len(currency) != 3:
        return None
    forecast = _mapping(properties.get("forecastSpend"))
    forecast_spend = _decimal(forecast.get("amount"))
    identity = str(item.get("id") or item.get("name") or "")
    if not identity:
        return None
    return CostAnalyticsBudget(
        budget_ref=f"budget:{_short_digest(identity)}",
        amount=amount,
        current_spend=current_spend,
        forecast_spend=forecast_spend,
        currency=currency,
        time_grain=str(properties.get("timeGrain") or "Unknown")[:32],
    )


def _recommendation(
    item: Mapping[str, Any],
    *,
    utilization_by_resource: Mapping[str, Decimal],
    observed_at: datetime,
) -> CostAnalyticsRecommendation | None:
    resource = _mapping(item.get("resourceMetadata"))
    resource_id = str(resource.get("resourceId") or "")
    recommendation_id = str(item.get("id") or item.get("name") or "")
    description = _mapping(item.get("shortDescription"))
    problem = str(description.get("problem") or "").strip()
    solution = str(description.get("solution") or "").strip()
    resource_type = str(item.get("impactedField") or "unknown").strip().casefold()
    if not recommendation_id or not problem or not solution:
        return None
    extended = _mapping(item.get("extendedProperties"))
    annual_savings = _decimal(extended.get("annualSavingsAmount"))
    monthly_savings = (
        (annual_savings / Decimal(12)).quantize(Decimal("0.01"))
        if annual_savings is not None and annual_savings >= 0
        else None
    )
    currency = str(extended.get("savingsCurrency") or "").strip().upper() or None
    if currency is not None and len(currency) != 3:
        currency = None
    raw_impact = str(item.get("impact") or "Unknown").title()
    impact: Literal["High", "Medium", "Low", "Unknown"]
    if raw_impact == "High":
        impact = "High"
    elif raw_impact == "Medium":
        impact = "Medium"
    elif raw_impact == "Low":
        impact = "Low"
    else:
        impact = "Unknown"
    utilization = utilization_by_resource.get(resource_id.casefold())
    return CostAnalyticsRecommendation(
        recommendation_ref=f"recommendation:{_short_digest(recommendation_id)}",
        resource_ref=f"resource:{_short_digest(resource_id)}" if resource_id else None,
        resource_type=resource_type[:256],
        problem=problem[:512],
        solution=solution[:512],
        impact=impact,
        monthly_savings=monthly_savings,
        currency=currency,
        current_sku=_optional_text(
            extended.get("skuName") or extended.get("vmSize") or extended.get("productName"),
            128,
        ),
        target_sku=_optional_text(extended.get("displaySKU"), 128),
        utilization_percent=utilization,
        utilization_metric="node_cpu_usage_percentage.hourly_average.p95"
        if utilization is not None
        else None,
        observed_at=observed_at.astimezone(UTC),
        source_authority="azure-advisor",
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _service_daily_costs(
    usage_items: Sequence[Mapping[str, Any]],
) -> defaultdict[tuple[str, str, str], Decimal]:
    daily: defaultdict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
    for item in usage_items:
        properties = _mapping(item.get("properties"))
        day = str(properties.get("date") or "")[:10]
        service = str(
            properties.get("serviceFamily") or properties.get("consumedService") or ""
        ).strip()
        currency = str(properties.get("billingCurrencyCode") or "").strip().upper()
        amount = _decimal(properties.get("costInBillingCurrency"))
        if not day or not service or len(currency) != 3 or amount is None or amount < 0:
            continue
        daily[(day, service, currency)] += amount
    return daily


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _optional_text(value: object, maximum: int) -> str | None:
    text = str(value or "").strip()
    return text[:maximum] if text else None


def _short_digest(value: str) -> str:
    return hashlib.sha256(value.casefold().encode()).hexdigest()[:16]


__all__ = [
    "SOURCE_AUTHORITY",
    "analytics_identity",
    "build_azure_cost_analytics",
    "build_usage_observations",
    "percentile_95",
    "usage_has_negative_costs",
]
