#!/usr/bin/env python3
"""Collect bounded authoritative Cost Governance analytics for local Console use."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from collections.abc import Generator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx
from azure.identity.aio import AzureCliCredential
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.cost_sample_publisher import EventBusCostSamplePublisher
from fdai.delivery.persistence.postgres_cost_governance import (
    PostgresCostGovernanceConfig,
    PostgresCostGovernanceStore,
)
from fdai.shared.providers.cost_governance import (
    CostObservation,
    CostObservationPage,
    CostPackageActivation,
)

from fdai_cost_governance import CostAnalyzerService, CostJobConfig
from fdai_cost_governance.azure_analytics import (
    analytics_identity,
    build_azure_cost_analytics,
    build_usage_observations,
    percentile_95,
    usage_has_negative_costs,
)

_MANAGEMENT = "https://management.azure.com"
_MAX_PAGES = 12
_MAX_BYTES = 25_000_000
_MAX_RECOMMENDATIONS = 200
_MAX_METRIC_RESOURCES = 8


class AzureAnalyticsHttpError(RuntimeError):
    """An Azure analytics source returned a bounded HTTP failure."""

    def __init__(self, source: str, status: int) -> None:
        super().__init__(f"{source} returned HTTP {status}")
        self.source = source
        self.status = status


class _BearerAuth(httpx.Auth):
    """Attach one in-memory Azure token without exposing it to process arguments."""

    def __init__(self, token: str) -> None:
        self._token = token

    def auth_flow(
        self,
        request: httpx.Request,
    ) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["authorization"] = " ".join(("Bearer", self._token))
        yield request


async def collect(days: int) -> dict[str, object]:
    """Collect, sanitize, validate, and append one analytics snapshot."""

    if not 1 <= days <= 31:
        raise ValueError("days MUST be in [1, 31]")
    observed_at = datetime.now(UTC)
    deadline = observed_at + timedelta(minutes=2)
    subscription_id = _subscription_id(deadline)
    scope_id = f"subscriptions/{subscription_id}"
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        raise RuntimeError("FDAI_STATE_STORE_DSN is required")
    store = PostgresCostGovernanceStore(config=PostgresCostGovernanceConfig(dsn=dsn))
    activation = await store.read_cost_activation("cost-governance")
    if activation is None or not activation.available or not activation.enabled:
        raise RuntimeError("Cost Governance package is not enabled")

    start_at = observed_at - timedelta(days=days)
    credential = AzureCliCredential()
    limitations: list[str] = []
    try:
        async with asyncio.timeout(_remaining_seconds(deadline)):
            token = (await credential.get_token("https://management.azure.com/.default")).token
        async with httpx.AsyncClient(
            auth=_BearerAuth(token),
            headers={"Accept": "application/json"},
        ) as client:
            usage_items, usage_complete, usage_bytes = await _usage_details(
                client,
                subscription_id=subscription_id,
                start_at=start_at,
                end_at=observed_at,
                deadline=deadline,
            )
            budget_items = await _optional_list(
                client,
                source="budgets",
                url=(
                    f"{_MANAGEMENT}/subscriptions/{subscription_id}"
                    "/providers/Microsoft.Consumption/budgets"
                ),
                params={"api-version": "2023-11-01"},
                deadline=deadline,
                limitations=limitations,
            )
            advisor_items = _advisor_items(deadline)
            if len(advisor_items) > _MAX_RECOMMENDATIONS:
                advisor_items = advisor_items[:_MAX_RECOMMENDATIONS]
                limitations.append("advisor_recommendation_limit")
            utilization = await _utilization(
                client,
                advisor_items=advisor_items,
                start_at=start_at,
                end_at=observed_at,
                deadline=deadline,
                limitations=limitations,
            )
    finally:
        await credential.close()

    if usage_has_negative_costs(usage_items):
        limitations.append("negative_cost_unsupported")
    complete = usage_complete and not limitations
    observations = build_usage_observations(
        package_id="cost-governance",
        scope_id=scope_id,
        usage_items=usage_items,
        collected_at=observed_at,
        ontology_release_id=activation.ontology_release_id,
        ontology_release_digest=activation.ontology_release_digest,
        complete=usage_complete,
    )
    cursor = await store.read_cost_cursor("cost-governance", scope_id)
    expected_revision = cursor.revision if cursor else 0
    async with asyncio.timeout(_remaining_seconds(deadline)):
        appended = await store.append_cost_page(
            CostObservationPage(
                observations=observations,
                next_resume_token=None,
                complete=usage_complete,
                source_authority="azure-consumption-usage-details",
                bytes_read=usage_bytes,
                collected_at=observed_at,
            ),
            package_id="cost-governance",
            scope_id=scope_id,
            expected_revision=expected_revision,
            coverage_through_at=observed_at,
            retention_floor_at=start_at,
        )
    if not appended:
        raise RuntimeError("Cost Governance observation cursor conflict")
    projection = build_azure_cost_analytics(
        usage_items=usage_items,
        budget_items=budget_items,
        advisor_items=advisor_items,
        utilization_by_resource=utilization,
        observed_at=observed_at,
        complete=complete,
        limitations=limitations,
    )
    snapshot_id, evidence_digest = analytics_identity(
        projection,
        package_id="cost-governance",
        scope_id=scope_id,
    )
    async with asyncio.timeout(_remaining_seconds(deadline)):
        inserted = await store.append_cost_analytics_snapshot(
            snapshot_id=snapshot_id,
            package_id="cost-governance",
            scope_id=scope_id,
            observed_at=observed_at,
            source_authority=projection.source_authority,
            complete=projection.complete,
            payload=projection.model_dump(mode="json"),
            evidence_digest=evidence_digest,
            retention_until=observed_at + timedelta(days=400),
        )
    async with asyncio.timeout(_remaining_seconds(deadline)):
        published = await _publish_observations(
            store=store,
            activation=activation,
            scope_id=scope_id,
            observations=observations,
            days=days,
        )
    return {
        "status": "stored" if inserted else "already-stored",
        "trend_points": len(projection.trend),
        "budgets": len(projection.budgets),
        "recommendations": len(projection.recommendations),
        "utilization_samples": len(utilization),
        "observations": len(observations),
        "published": published,
        "complete": projection.complete,
        "limitations": list(projection.limitations),
    }


async def _publish_observations(
    *,
    store: PostgresCostGovernanceStore,
    activation: CostPackageActivation,
    scope_id: str,
    observations: Sequence[CostObservation],
    days: int,
) -> int:
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    topic = os.environ.get("KAFKA_TOPIC_EVENTS", "").strip()
    if not bootstrap_servers or not topic or not observations:
        return 0
    bus = EventHubsKafkaBus(
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=bootstrap_servers,
            security_protocol="PLAINTEXT",
            client_id="fdai-local-cost-analyzer",
            auto_offset_reset="earliest",
        ),
        identity=None,
    )
    try:
        result = await CostAnalyzerService(
            config=CostJobConfig(
                package_id="cost-governance",
                ontology_release_id=activation.ontology_release_id,
                ontology_release_digest=activation.ontology_release_digest,
                known_service_ids=frozenset(item.service_id for item in observations),
                max_observation_age=timedelta(days=days + 1),
            ),
            activation=store,
            store=store,
            publisher=EventBusCostSamplePublisher(bus=bus, topic=topic),
        ).analyze(
            scope_id=scope_id,
            since=datetime.now(UTC) - timedelta(days=days + 1),
            limit=1000,
        )
    finally:
        await bus.close()
    if result.status != "complete":
        raise RuntimeError(f"Cost Governance analyzer ended with {result.status}")
    return result.published


async def _usage_details(
    client: httpx.AsyncClient,
    *,
    subscription_id: str,
    start_at: datetime,
    end_at: datetime,
    deadline: datetime,
) -> tuple[list[Mapping[str, Any]], bool, int]:
    url = (
        f"{_MANAGEMENT}/subscriptions/{subscription_id}"
        "/providers/Microsoft.Consumption/usageDetails"
    )
    params: Mapping[str, str] | None = {
        "api-version": "2023-05-01",
        "startDate": start_at.date().isoformat(),
        "endDate": end_at.date().isoformat(),
    }
    items: list[Mapping[str, Any]] = []
    pages = bytes_read = 0
    while url and pages < _MAX_PAGES and bytes_read < _MAX_BYTES:
        document, size = await _get_json(
            client,
            source="usage-details",
            url=url,
            params=params,
            deadline=deadline,
        )
        pages += 1
        bytes_read += size
        items.extend(_mapping_items(document.get("value")))
        next_link = document.get("nextLink")
        url = str(next_link) if next_link else ""
        if url:
            _require_management_url(url)
        params = None
    return items, not bool(url), bytes_read


async def _optional_list(
    client: httpx.AsyncClient,
    *,
    source: str,
    url: str,
    params: Mapping[str, str],
    deadline: datetime,
    limitations: list[str],
) -> list[Mapping[str, Any]]:
    items: list[Mapping[str, Any]] = []
    pages = 0
    current_url = url
    current_params: Mapping[str, str] | None = params
    while current_url and pages < _MAX_PAGES:
        try:
            document, _ = await _get_json(
                client,
                source=source,
                url=current_url,
                params=current_params,
                deadline=deadline,
            )
        except AzureAnalyticsHttpError as exc:
            if exc.status in {429, 503}:
                raise
            limitations.append(f"{source}_unavailable")
            return []
        items.extend(_mapping_items(document.get("value")))
        pages += 1
        next_link = document.get("nextLink")
        current_url = str(next_link) if next_link else ""
        if current_url:
            _require_management_url(current_url)
        current_params = None
    if current_url:
        limitations.append(f"{source}_page_limit")
    return items


async def _utilization(
    client: httpx.AsyncClient,
    *,
    advisor_items: Sequence[Mapping[str, Any]],
    start_at: datetime,
    end_at: datetime,
    deadline: datetime,
    limitations: list[str],
) -> dict[str, Decimal]:
    resources = {
        resource_id
        for item in advisor_items
        if "managedclusters" in str(item.get("impactedField") or "").casefold()
        if (resource_id := str(_mapping(item.get("resourceMetadata")).get("resourceId") or ""))
    }
    selected = sorted(resources)[:_MAX_METRIC_RESOURCES]
    if len(resources) > len(selected):
        limitations.append("utilization_resource_limit")
    values: dict[str, Decimal] = {}
    for resource_id in selected:
        url = f"{_MANAGEMENT}{resource_id}/providers/microsoft.insights/metrics"
        try:
            document, _ = await _get_json(
                client,
                source="monitor-metrics",
                url=url,
                params={
                    "api-version": "2018-01-01",
                    "metricnamespace": "microsoft.containerservice/managedclusters",
                    "metricnames": "node_cpu_usage_percentage",
                    "aggregation": "Average",
                    "interval": "PT1H",
                    "timespan": f"{start_at.isoformat()}/{end_at.isoformat()}",
                },
                deadline=deadline,
            )
        except AzureAnalyticsHttpError as exc:
            if exc.status in {429, 503}:
                raise
            limitations.append("utilization_unavailable")
            continue
        samples = [
            float(point["average"])
            for metric in _mapping_items(document.get("value"))
            for series in _mapping_items(metric.get("timeseries"))
            for point in _mapping_items(series.get("data"))
            if isinstance(point.get("average"), (int, float))
        ]
        if (p95 := percentile_95(samples)) is not None:
            values[resource_id.casefold()] = p95
    return values


async def _get_json(
    client: httpx.AsyncClient,
    *,
    source: str,
    url: str,
    params: Mapping[str, str] | None,
    deadline: datetime,
) -> tuple[dict[str, Any], int]:
    if datetime.now(UTC) >= deadline:
        raise TimeoutError(f"{source} analytics deadline expired")
    _require_management_url(url)
    response = await client.get(
        url,
        params=params,
        timeout=max(1, (deadline - datetime.now(UTC)).total_seconds()),
    )
    body = await response.aread()
    if response.status_code != 200:
        raise AzureAnalyticsHttpError(source, response.status_code)
    if len(body) > _MAX_BYTES:
        raise RuntimeError(f"{source} response exceeded byte budget")
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{source} returned invalid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{source} returned a non-object document")
    return document, len(body)


def _mapping_items(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _require_management_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "management.azure.com":
        raise ValueError("Azure analytics URL is not authoritative")


def _subscription_id(deadline: datetime) -> str:
    try:
        result = subprocess.run(
            ["az", "account", "show", "--query", "id", "--output", "tsv"],
            check=True,
            capture_output=True,
            text=True,
            timeout=_remaining_seconds(deadline),
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Azure subscription discovery deadline expired") from exc
    value = result.stdout.strip()
    if not value:
        raise RuntimeError("Azure CLI returned no active subscription")
    return value


def _advisor_items(deadline: datetime) -> list[Mapping[str, Any]]:
    try:
        result = subprocess.run(
            [
                "az",
                "advisor",
                "recommendation",
                "list",
                "--category",
                "Cost",
                "--output",
                "json",
            ],
            check=True,
            capture_output=True,
            timeout=min(30, _remaining_seconds(deadline)),
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Azure Advisor deadline expired") from exc
    try:
        document = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Azure Advisor returned invalid JSON") from exc
    return _mapping_items(document)


def _remaining_seconds(deadline: datetime) -> float:
    remaining = (deadline - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise TimeoutError("Cost Governance analytics deadline expired")
    return remaining


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    result = asyncio.run(collect(args.days))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
