"""Shared local and deployed scheduled Cost Analytics contract."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

import httpx
from fdai.shared.providers.cost_governance import (
    CostCollectionRequest,
    CostObservationPage,
    CostObservationStore,
    CostPackageActivationReader,
    CostSamplePublisher,
)
from fdai_service_contracts import (
    CostAnalyticsRunReceipt,
    CostAnalyticsRunStatus,
    CostEvidenceSourceFacet,
    CostEvidenceState,
)

from .azure_analytics import (
    analytics_identity,
    build_azure_cost_analytics,
    build_usage_observations,
    percentile_95,
    usage_has_negative_costs,
)
from .azure_focus import CostReadCredential, cost_query_body, decode_cost_query_rows
from .service import CostAnalyzerService, CostJobConfig

_MANAGEMENT = "https://management.azure.com"
_MAX_PAGES = 12
_MAX_BYTES = 25_000_000
_MAX_RECOMMENDATIONS = 200
_MAX_METRIC_RESOURCES = 8


class ScheduledAnalyticsStore(CostObservationStore, CostPackageActivationReader, Protocol):
    """Persistence used by the authority-free scheduled analytics attempt."""

    async def append_cost_analytics_snapshot(
        self,
        *,
        snapshot_id: str,
        package_id: str,
        scope_id: str,
        observed_at: datetime,
        source_authority: str,
        complete: bool,
        payload: Mapping[str, object],
        evidence_digest: str,
        retention_until: datetime,
    ) -> bool: ...

    async def append_cost_analytics_run_receipt(
        self,
        receipt: CostAnalyticsRunReceipt,
        *,
        scope_id: str,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class AzureAnalyticsBatch:
    """Bounded in-memory provider material erased after normalization."""

    usage_items: tuple[Mapping[str, Any], ...]
    budget_items: tuple[Mapping[str, Any], ...]
    advisor_items: tuple[Mapping[str, Any], ...]
    utilization_by_resource: Mapping[str, Decimal]
    usage_complete: bool
    usage_bytes: int
    sources: tuple[CostEvidenceSourceFacet, ...]
    limitations: tuple[str, ...]
    collected_at: datetime


@dataclass(frozen=True, slots=True)
class ScheduledAnalyticsResult:
    """Terminal scheduled attempt result backed by a durable receipt."""

    receipt: CostAnalyticsRunReceipt
    snapshot_stored: bool = False
    published: int = 0


class AnalyticsSourceError(RuntimeError):
    """One stable source failure with no provider response content."""

    def __init__(self, source: str, reason: str) -> None:
        super().__init__(reason)
        self.source = source
        self.reason = reason


class AzureScheduledAnalyticsSource:
    """Read bounded Cost Management, Budget, Advisor, and Monitor evidence."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        credential: CostReadCredential,
    ) -> None:
        self._client = client
        self._credential = credential

    async def collect(
        self,
        *,
        scope_id: str,
        start_at: datetime,
        end_at: datetime,
        deadline_at: datetime,
    ) -> AzureAnalyticsBatch:
        """Collect source material under one deadline and explicit source status."""

        subscription_id = _subscription_id(scope_id)
        remaining = (deadline_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise AnalyticsSourceError("credential", "deadline_exceeded")
        try:
            async with asyncio.timeout(remaining):
                token = await self._credential.access_token(deadline_at=deadline_at)
        except TimeoutError as exc:
            raise AnalyticsSourceError("credential", "deadline_exceeded") from exc
        except Exception as exc:
            raise AnalyticsSourceError("credential", "credential_unavailable") from exc
        usage, usage_complete, usage_bytes = await self._cost_query_usage(
            scope_id=scope_id,
            start_at=start_at,
            end_at=end_at,
            token=token,
            deadline_at=deadline_at,
        )
        sources = [
            _source_facet(
                "azure-cost-management-query",
                complete=usage_complete,
                count=len(usage),
                start_at=start_at,
                end_at=end_at,
                reason=None if usage_complete else "page_limit",
            )
        ]
        limitations: list[str] = [] if usage_complete else ["usage_page_limit"]
        budgets, budget_complete, _ = await self._paged_list(
            source="budgets",
            url=(
                f"{_MANAGEMENT}/subscriptions/{subscription_id}"
                "/providers/Microsoft.Consumption/budgets"
            ),
            params={"api-version": "2023-11-01"},
            token=token,
            deadline_at=deadline_at,
            required=False,
        )
        sources.append(
            _source_facet(
                "azure-consumption-budgets",
                complete=budget_complete,
                count=len(budgets),
                start_at=start_at,
                end_at=end_at,
                reason=None if budget_complete else "source_unavailable",
            )
        )
        if not budget_complete:
            limitations.append("budgets_unavailable")
        advisor, advisor_complete, _ = await self._paged_list(
            source="advisor",
            url=(
                f"{_MANAGEMENT}/subscriptions/{subscription_id}"
                "/providers/Microsoft.Advisor/recommendations"
            ),
            params={"api-version": "2023-01-01", "$filter": "Category eq 'Cost'"},
            token=token,
            deadline_at=deadline_at,
            required=False,
        )
        if len(advisor) > _MAX_RECOMMENDATIONS:
            advisor = advisor[:_MAX_RECOMMENDATIONS]
            advisor_complete = False
            limitations.append("advisor_recommendation_limit")
        sources.append(
            _source_facet(
                "azure-advisor",
                complete=advisor_complete,
                count=len(advisor),
                start_at=start_at,
                end_at=end_at,
                reason=None if advisor_complete else "source_partial",
            )
        )
        if not advisor_complete and "advisor_recommendation_limit" not in limitations:
            limitations.append("advisor_unavailable")
        utilization, utilization_complete = await self._utilization(
            subscription_id=subscription_id,
            advisor_items=advisor,
            start_at=start_at,
            end_at=end_at,
            token=token,
            deadline_at=deadline_at,
        )
        sources.append(
            _source_facet(
                "azure-monitor",
                complete=utilization_complete,
                count=len(utilization),
                start_at=start_at,
                end_at=end_at,
                reason=None if utilization_complete else "source_partial",
            )
        )
        if not utilization_complete:
            limitations.append("utilization_partial")
        return AzureAnalyticsBatch(
            usage_items=tuple(usage),
            budget_items=tuple(budgets),
            advisor_items=tuple(advisor),
            utilization_by_resource=utilization,
            usage_complete=usage_complete,
            usage_bytes=usage_bytes,
            sources=tuple(sources),
            limitations=tuple(sorted(set(limitations))),
            collected_at=datetime.now(UTC),
        )

    async def _cost_query_usage(
        self,
        *,
        scope_id: str,
        start_at: datetime,
        end_at: datetime,
        token: str,
        deadline_at: datetime,
    ) -> tuple[list[Mapping[str, Any]], bool, int]:
        request = CostCollectionRequest(
            package_id="cost-governance",
            scope_id=scope_id,
            start_at=start_at,
            end_at=end_at,
            page_size=1000,
            deadline_at=deadline_at,
        )
        url = (
            f"{_MANAGEMENT}/{scope_id.removeprefix('/')}"
            "/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
        )
        items: list[Mapping[str, Any]] = []
        pages = bytes_read = 0
        while url and pages < _MAX_PAGES and bytes_read < _MAX_BYTES:
            document, size = await self._post_json(
                source="cost-management-query",
                url=url,
                payload=cost_query_body(request),
                token=token,
                deadline_at=deadline_at,
            )
            rows = decode_cost_query_rows(document, page_size=request.page_size)
            items.extend(_usage_item(row) for row in rows)
            pages += 1
            bytes_read += size
            if bytes_read > _MAX_BYTES:
                raise AnalyticsSourceError("cost-management-query", "response_too_large")
            properties = _mapping(document.get("properties"))
            next_link = properties.get("nextLink")
            url = str(next_link) if next_link else ""
            if url:
                _require_management_url(url)
        return items, not bool(url), bytes_read

    async def _paged_list(
        self,
        *,
        source: str,
        url: str,
        params: Mapping[str, str],
        token: str,
        deadline_at: datetime,
        required: bool,
    ) -> tuple[list[Mapping[str, Any]], bool, int]:
        items: list[Mapping[str, Any]] = []
        current_url = url
        current_params: Mapping[str, str] | None = params
        pages = bytes_read = 0
        while current_url and pages < _MAX_PAGES and bytes_read < _MAX_BYTES:
            try:
                document, size = await self._get_json(
                    source=source,
                    url=current_url,
                    params=current_params,
                    token=token,
                    deadline_at=deadline_at,
                )
            except AnalyticsSourceError as exc:
                if required or exc.reason in {
                    "provider_rate_limited",
                    "provider_unavailable",
                }:
                    raise
                return [], False, bytes_read
            items.extend(_mapping_items(document.get("value")))
            pages += 1
            bytes_read += size
            if bytes_read > _MAX_BYTES:
                if required:
                    raise AnalyticsSourceError(source, "response_too_large")
                return items, False, bytes_read
            next_link = document.get("nextLink")
            current_url = str(next_link) if next_link else ""
            if current_url:
                _require_management_url(current_url)
            current_params = None
        return items, not bool(current_url), bytes_read

    async def _utilization(
        self,
        *,
        subscription_id: str,
        advisor_items: Sequence[Mapping[str, Any]],
        start_at: datetime,
        end_at: datetime,
        token: str,
        deadline_at: datetime,
    ) -> tuple[dict[str, Decimal], bool]:
        resources: set[str] = set()
        complete = True
        for item in advisor_items:
            details = _mapping(item.get("properties")) or item
            if "managedclusters" not in str(details.get("impactedField") or "").casefold():
                continue
            resource = _mapping(details.get("resourceMetadata"))
            resource_id = str(resource.get("resourceId") or details.get("impactedValue") or "")
            if resource_id.casefold().startswith(f"/subscriptions/{subscription_id}/".casefold()):
                resources.add(resource_id)
            else:
                complete = False
        selected = sorted(resources)[:_MAX_METRIC_RESOURCES]
        complete = complete and len(selected) == len(resources)
        values: dict[str, Decimal] = {}
        for resource_id in selected:
            try:
                document, _ = await self._get_json(
                    source="monitor-metrics",
                    url=f"{_MANAGEMENT}{resource_id}/providers/microsoft.insights/metrics",
                    params={
                        "api-version": "2018-01-01",
                        "metricnamespace": "microsoft.containerservice/managedclusters",
                        "metricnames": "node_cpu_usage_percentage",
                        "aggregation": "Average",
                        "interval": "PT1H",
                        "timespan": f"{start_at.isoformat()}/{end_at.isoformat()}",
                    },
                    token=token,
                    deadline_at=deadline_at,
                )
            except AnalyticsSourceError:
                complete = False
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
        return values, complete

    async def _get_json(
        self,
        *,
        source: str,
        url: str,
        params: Mapping[str, str] | None,
        token: str,
        deadline_at: datetime,
    ) -> tuple[dict[str, Any], int]:
        remaining = (deadline_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise AnalyticsSourceError(source, "deadline_exceeded")
        _require_management_url(url)
        try:
            response = await self._client.get(
                url,
                params=params,
                headers={
                    "Authorization": " ".join(("Bearer", token)),
                    "Accept": "application/json",
                },
                timeout=remaining,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise AnalyticsSourceError(source, "transport_error") from exc
        body = await response.aread()
        if response.status_code == 429:
            raise AnalyticsSourceError(source, "provider_rate_limited")
        if response.status_code == 503:
            raise AnalyticsSourceError(source, "provider_unavailable")
        if response.status_code != 200:
            raise AnalyticsSourceError(source, "source_unavailable")
        if len(body) > _MAX_BYTES:
            raise AnalyticsSourceError(source, "response_too_large")
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AnalyticsSourceError(source, "invalid_source_payload") from exc
        if not isinstance(document, dict):
            raise AnalyticsSourceError(source, "invalid_source_payload")
        return document, len(body)

    async def _post_json(
        self,
        *,
        source: str,
        url: str,
        payload: Mapping[str, object],
        token: str,
        deadline_at: datetime,
    ) -> tuple[dict[str, Any], int]:
        remaining = (deadline_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise AnalyticsSourceError(source, "deadline_exceeded")
        _require_management_url(url)
        try:
            response = await self._client.post(
                url,
                json=dict(payload),
                headers={
                    "Authorization": " ".join(("Bearer", token)),
                    "Accept": "application/json",
                },
                timeout=remaining,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise AnalyticsSourceError(source, "transport_error") from exc
        body = await response.aread()
        if response.status_code == 429:
            raise AnalyticsSourceError(source, "provider_rate_limited")
        if response.status_code == 503:
            raise AnalyticsSourceError(source, "provider_unavailable")
        if response.status_code != 200:
            raise AnalyticsSourceError(source, "source_unavailable")
        if len(body) > _MAX_BYTES:
            raise AnalyticsSourceError(source, "response_too_large")
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AnalyticsSourceError(source, "invalid_source_payload") from exc
        if not isinstance(document, dict):
            raise AnalyticsSourceError(source, "invalid_source_payload")
        return document, len(body)


async def run_scheduled_analytics(
    *,
    config: CostJobConfig,
    scope_id: str,
    venue: Literal["local", "deployed"],
    days: int,
    source: AzureScheduledAnalyticsSource,
    store: ScheduledAnalyticsStore,
    publisher: CostSamplePublisher | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ScheduledAnalyticsResult:
    """Run one bounded analytics attempt and durably record every terminal state."""

    if not 1 <= days <= 31:
        raise ValueError("Cost Analytics days MUST be in [1, 31]")
    now = clock or (lambda: datetime.now(UTC))
    started_at = now()
    window_end_at = started_at
    window_start_at = window_end_at - timedelta(days=days)
    deadline_at = started_at + config.attempt_timeout
    sources: tuple[CostEvidenceSourceFacet, ...] = ()
    counts = {"observations": 0, "trend": 0, "budgets": 0, "recommendations": 0, "utilization": 0}
    snapshot_id: str | None = None
    snapshot_stored = False
    published = 0
    limitations: tuple[str, ...] = ()
    status = CostAnalyticsRunStatus.FAILED
    failure_reason: str | None = None
    try:
        activation = await store.read_cost_activation(config.package_id)
        if activation is None or not activation.available or not activation.enabled:
            status = CostAnalyticsRunStatus.DISABLED
        elif (
            activation.ontology_release_id != config.ontology_release_id
            or activation.ontology_release_digest != config.ontology_release_digest
        ):
            raise AnalyticsSourceError("activation", "activation_revision_mismatch")
        else:
            batch = await source.collect(
                scope_id=scope_id,
                start_at=window_start_at,
                end_at=window_end_at,
                deadline_at=deadline_at,
            )
            sources = batch.sources
            limitations = batch.limitations
            negative_costs = usage_has_negative_costs(batch.usage_items)
            if negative_costs:
                limitations = tuple(sorted({*limitations, "negative_cost_unsupported"}))
                sources = tuple(
                    item.model_copy(
                        update={
                            "state": CostEvidenceState.PARTIAL,
                            "complete_count": 0,
                            "partial_count": item.complete_count + item.partial_count,
                            "reason": "negative_cost_unsupported",
                        }
                    )
                    if item.source_authority
                    in {"azure-consumption-usage-details", "azure-cost-management-query"}
                    else item
                    for item in sources
                )
            observations_complete = batch.usage_complete and not negative_costs
            observations = build_usage_observations(
                package_id=config.package_id,
                scope_id=scope_id,
                usage_items=batch.usage_items,
                collected_at=batch.collected_at,
                ontology_release_id=activation.ontology_release_id,
                ontology_release_digest=activation.ontology_release_digest,
                complete=observations_complete,
                source_authority=next(
                    (
                        item.source_authority
                        for item in sources
                        if item.source_authority
                        in {
                            "azure-consumption-usage-details",
                            "azure-cost-management-query",
                        }
                    ),
                    "azure-consumption-usage-details",
                ),
            )
            cursor = await store.read_cost_cursor(config.package_id, scope_id)
            expected_revision = int(getattr(cursor, "revision", 0))
            appended = await store.append_cost_page(
                CostObservationPage(
                    observations=observations,
                    next_resume_token=None,
                    complete=observations_complete,
                    source_authority="azure-consumption-usage-details",
                    bytes_read=batch.usage_bytes,
                    collected_at=batch.collected_at,
                ),
                package_id=config.package_id,
                scope_id=scope_id,
                expected_revision=expected_revision,
                coverage_through_at=window_end_at,
                retention_floor_at=window_start_at,
            )
            if not appended:
                raise AnalyticsSourceError("persistence", "observation_cursor_conflict")
            projection = build_azure_cost_analytics(
                usage_items=batch.usage_items,
                budget_items=batch.budget_items,
                advisor_items=batch.advisor_items,
                utilization_by_resource=batch.utilization_by_resource,
                observed_at=batch.collected_at,
                complete=observations_complete and not limitations,
                limitations=limitations,
                window_start_at=window_start_at,
                window_end_at=window_end_at,
                sources=sources,
            )
            snapshot_id, evidence_digest = analytics_identity(
                projection,
                package_id=config.package_id,
                scope_id=scope_id,
            )
            snapshot_stored = await store.append_cost_analytics_snapshot(
                snapshot_id=snapshot_id,
                package_id=config.package_id,
                scope_id=scope_id,
                observed_at=batch.collected_at,
                source_authority=projection.source_authority,
                complete=projection.complete,
                payload=projection.model_dump(mode="json"),
                evidence_digest=evidence_digest,
                retention_until=batch.collected_at + timedelta(days=400),
            )
            counts = {
                "observations": len(observations),
                "trend": len(projection.trend),
                "budgets": len(projection.budgets),
                "recommendations": len(projection.recommendations),
                "utilization": len(batch.utilization_by_resource),
            }
            if publisher is not None and observations:
                analyzer_config = replace(
                    config,
                    known_service_ids=frozenset(item.service_id for item in observations),
                    max_observation_age=timedelta(days=days + 1),
                )
                analyzed = await CostAnalyzerService(
                    config=analyzer_config,
                    activation=store,
                    store=store,
                    publisher=publisher,
                    clock=now,
                ).analyze(scope_id=scope_id, since=window_start_at, limit=1000)
                if analyzed.status != "complete":
                    raise AnalyticsSourceError("publisher", "analysis_publish_failed")
                published = analyzed.published
            status = (
                CostAnalyticsRunStatus.COMPLETE
                if projection.complete
                else CostAnalyticsRunStatus.PARTIAL
            )
    except AnalyticsSourceError as exc:
        failure_reason = exc.reason
        sources = (
            CostEvidenceSourceFacet(
                source_authority=exc.source,
                state=CostEvidenceState.UNAVAILABLE,
                reason=exc.reason,
            ),
        )
    except TimeoutError:
        failure_reason = "deadline_exceeded"
    except (TypeError, ValueError):
        failure_reason = "invalid_source_payload"
    except RuntimeError:
        failure_reason = "persistence_unavailable"
    except Exception:
        failure_reason = "internal_error"
    if status is CostAnalyticsRunStatus.FAILED:
        snapshot_id = None
    finished_at = now()
    receipt = _receipt(
        scope_id=scope_id,
        venue=venue,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        sources=sources,
        counts=counts,
        limitations=limitations,
        failure_reason=failure_reason,
        snapshot_id=snapshot_id,
    )
    await store.append_cost_analytics_run_receipt(receipt, scope_id=scope_id)
    return ScheduledAnalyticsResult(receipt, snapshot_stored=snapshot_stored, published=published)


def _receipt(
    *,
    scope_id: str,
    venue: Literal["local", "deployed"],
    window_start_at: datetime,
    window_end_at: datetime,
    started_at: datetime,
    finished_at: datetime,
    status: CostAnalyticsRunStatus,
    sources: tuple[CostEvidenceSourceFacet, ...],
    counts: Mapping[str, int],
    limitations: tuple[str, ...],
    failure_reason: str | None,
    snapshot_id: str | None,
) -> CostAnalyticsRunReceipt:
    values = {
        "scope_digest": f"sha256:{hashlib.sha256(scope_id.encode()).hexdigest()}",
        "venue": venue,
        "window_start_at": window_start_at.isoformat(),
        "window_end_at": window_end_at.isoformat(),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "status": status.value,
        "sources": [item.model_dump(mode="json") for item in sources],
        "counts": dict(counts),
        "limitations": list(limitations),
        "failure_reason": failure_reason,
        "snapshot_id": snapshot_id,
    }
    encoded = json.dumps(values, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    return CostAnalyticsRunReceipt(
        run_id=f"costrun:{digest}",
        receipt_digest=f"sha256:{digest}",
        scope_digest=str(values["scope_digest"]),
        venue=venue,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        sources=sources,
        observation_count=counts["observations"],
        trend_point_count=counts["trend"],
        budget_count=counts["budgets"],
        recommendation_count=counts["recommendations"],
        utilization_count=counts["utilization"],
        limitations=limitations,
        failure_reason=failure_reason,
        snapshot_id=snapshot_id,
    )


def _source_facet(
    source_authority: str,
    *,
    complete: bool,
    count: int,
    start_at: datetime,
    end_at: datetime,
    reason: str | None,
) -> CostEvidenceSourceFacet:
    return CostEvidenceSourceFacet(
        source_authority=source_authority,
        state=(
            CostEvidenceState.COMPLETE
            if complete
            else (CostEvidenceState.PARTIAL if count else CostEvidenceState.UNAVAILABLE)
        ),
        window_start_at=start_at,
        window_end_at=end_at,
        latest_source_at=end_at if complete or count else None,
        complete_count=count if complete else 0,
        partial_count=0 if complete else count,
        reason=reason,
    )


def _subscription_id(scope_id: str) -> str:
    parts = scope_id.strip("/").split("/")
    if (
        len(parts) != 2
        or parts[0].casefold() != "subscriptions"
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", parts[1]) is None
    ):
        raise ValueError("Cost Analytics scope MUST be subscriptions/<id>")
    return parts[1]


def _require_management_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "management.azure.com":
        raise AnalyticsSourceError("pagination", "invalid_next_link")


def _usage_item(row: Mapping[str, object]) -> Mapping[str, object]:
    raw_day = str(row.get("UsageDate") or "")
    day = (
        f"{raw_day[:4]}-{raw_day[4:6]}-{raw_day[6:8]}"
        if re.fullmatch(r"\d{8}", raw_day)
        else raw_day[:10]
    )
    service = str(row.get("ServiceName") or "").strip()
    currency = str(row.get("Currency") or "").strip().upper()
    try:
        amount = Decimal(str(row["Cost"]))
    except (KeyError, ArithmeticError, ValueError) as exc:
        raise AnalyticsSourceError("cost-management-query", "invalid_source_payload") from exc
    if (
        re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) is None
        or not service
        or len(currency) != 3
        or not amount.is_finite()
    ):
        raise AnalyticsSourceError("cost-management-query", "invalid_source_payload")
    return {
        "properties": {
            "date": day,
            "serviceFamily": service,
            "billingCurrencyCode": currency,
            "costInBillingCurrency": str(amount),
        }
    }


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_items(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


__all__ = [
    "AnalyticsSourceError",
    "AzureAnalyticsBatch",
    "AzureScheduledAnalyticsSource",
    "ScheduledAnalyticsResult",
    "ScheduledAnalyticsStore",
    "run_scheduled_analytics",
]
