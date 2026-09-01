"""Bounded Azure Service Health events for one server-owned subscription."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import httpx

from fdai.core.ontology_platform.service_health_queries import (
    ServiceHealthCollection,
    ServiceHealthObservation,
)
from fdai.delivery.azure.arg_transport import (
    ArgRateLimiter,
    ArgThrottleGate,
    fetch_arg_row_pages,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_MANAGEMENT_AUDIENCE: Final = "https://management.azure.com/.default"
_ARG_API_VERSION: Final = "2022-10-01"
_DOTNET_UNIX_EPOCH_TICKS: Final = 621_355_968_000_000_000
_DOTNET_TICKS_PER_MICROSECOND: Final = 10
_EVENT_TYPES = {
    "serviceissue": "service_issue",
    "plannedmaintenance": "planned_maintenance",
    "healthadvisory": "health_advisory",
}


class ServiceHealthError(RuntimeError):
    """Report a bounded provider failure without retaining provider content."""


@dataclass(frozen=True, slots=True)
class AzureServiceHealthConfig:
    """Server-owned subscription and request ceilings for Service Health reads."""

    subscription_id: str
    endpoint: str = "https://management.azure.com"
    timeout_seconds: float = 10.0
    max_events: int = 64
    max_impacts: int = 256
    max_response_bytes: int = 2_097_152

    def __post_init__(self) -> None:
        try:
            canonical = str(UUID(self.subscription_id))
        except (AttributeError, ValueError) as exc:
            raise ValueError("subscription_id MUST be a canonical UUID") from exc
        if canonical != self.subscription_id.casefold():
            raise ValueError("subscription_id MUST be a canonical UUID")
        if not self.endpoint.startswith("https://"):
            raise ValueError("Service Health endpoint MUST use https")
        if not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("Service Health timeout_seconds MUST be in [0.1, 30]")
        if not 1 <= self.max_events <= 64:
            raise ValueError("Service Health max_events MUST be in [1, 64]")
        if not 1 <= self.max_impacts <= 256:
            raise ValueError("Service Health max_impacts MUST be in [1, 256]")
        if not 1_024 <= self.max_response_bytes <= 5_000_000:
            raise ValueError("Service Health max_response_bytes MUST be in [1024, 5000000]")


@dataclass(frozen=True, slots=True)
class _Event:
    aliases: tuple[str, ...]
    event_type: str
    title: str
    level: str | None
    status: str
    impact_start_at: datetime
    evidence_ref: str


@dataclass(frozen=True, slots=True)
class _Impact:
    event_alias: str
    resource_name: str | None
    resource_type: str | None
    resource_group: str | None
    region: str | None
    status: str | None
    evidence_ref: str


class AzureServiceHealthReader:
    """Read active events and impacted resources under exact configured scope."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureServiceHealthConfig,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._identity: Final = identity
        self._http: Final = http_client
        self._config: Final = config
        self._now: Final = now or (lambda: datetime.now(UTC))
        self._throttle_gate = ArgThrottleGate()
        self._rate_limiter = ArgRateLimiter()

    async def read_active(self) -> ServiceHealthCollection:
        """Return active events or a typed unavailable or incomplete collection."""

        observed_at = self._now()
        if observed_at.tzinfo is None:
            raise ValueError("Service Health reader clock MUST be timezone-aware")
        try:
            raw_events = await self._query(
                query=_active_events_query(self._config.max_events),
                result_name="semantic-service-health-events",
                record_limit=self._config.max_events + 1,
            )
        except ServiceHealthError:
            return self._result(
                observed_at=observed_at,
                observations=(),
                complete=False,
                limitation="source_unavailable",
            )

        events: list[_Event] = []
        malformed = False
        for row in raw_events[: self._config.max_events]:
            event, scheduled_future = _event(row, observed_at=observed_at)
            if event is None:
                malformed = malformed or not scheduled_future
            else:
                events.append(event)
        event_limited = len(raw_events) > self._config.max_events
        if not events:
            limitation = (
                "service_health_response_invalid"
                if malformed
                else "result_limit"
                if event_limited
                else None
            )
            return self._result(
                observed_at=observed_at,
                observations=(),
                complete=limitation is None,
                limitation=limitation,
            )

        alias_owner: dict[str, _Event] = {}
        ambiguous_alias = False
        for event in events:
            for alias in event.aliases:
                prior = alias_owner.get(alias)
                if prior is not None and prior != event:
                    ambiguous_alias = True
                else:
                    alias_owner[alias] = event

        impact_unavailable = False
        raw_impacts: tuple[Mapping[str, Any], ...] = ()
        try:
            raw_impacts = await self._query(
                query=_active_impacts_query(
                    tuple(sorted(alias_owner)),
                    self._config.max_impacts,
                ),
                result_name="semantic-service-health-impacts",
                record_limit=self._config.max_impacts + 1,
            )
        except ServiceHealthError:
            impact_unavailable = True

        impacts_by_event: dict[str, list[_Impact]] = {event.evidence_ref: [] for event in events}
        widened = False
        impact_malformed = False
        if not impact_unavailable:
            for row in raw_impacts[: self._config.max_impacts]:
                scope_state = _impact_scope_state(
                    row.get("targetResourceId"),
                    subscription_id=self._config.subscription_id,
                )
                if scope_state == "widened":
                    widened = True
                    continue
                if scope_state == "malformed":
                    impact_malformed = True
                    continue
                impact = _impact(row)
                if impact is None:
                    impact_malformed = True
                    continue
                event = alias_owner.get(impact.event_alias)
                if event is None:
                    impact_malformed = True
                    continue
                impacts_by_event[event.evidence_ref].append(impact)

        observations: list[ServiceHealthObservation] = []
        for event in events:
            impacts = sorted(
                {item.evidence_ref: item for item in impacts_by_event[event.evidence_ref]}.values(),
                key=lambda item: (item.resource_name or "", item.evidence_ref),
            )
            if not impacts:
                observations.append(
                    _observation(
                        event,
                        observed_at=observed_at,
                        impact=None,
                        impact_count=None if impact_unavailable else 0,
                    )
                )
                continue
            for impact in impacts:
                observations.append(
                    _observation(
                        event,
                        observed_at=observed_at,
                        impact=impact,
                        impact_count=len(impacts),
                    )
                )
        observations.sort(
            key=lambda item: (
                item.impact_start_at,
                item.event_evidence_ref,
                item.resource_name or "",
            )
        )
        output_limited = len(observations) > self._config.max_impacts
        observations = observations[: self._config.max_impacts]
        limitation = (
            "provider_scope_mismatch"
            if widened
            else "service_health_response_invalid"
            if malformed or impact_malformed or ambiguous_alias
            else "result_limit"
            if event_limited or len(raw_impacts) > self._config.max_impacts or output_limited
            else "impact_source_unavailable"
            if impact_unavailable
            else None
        )
        return self._result(
            observed_at=observed_at,
            observations=tuple(observations),
            complete=limitation is None,
            limitation=limitation,
        )

    async def _query(
        self,
        *,
        query: str,
        result_name: str,
        record_limit: int,
    ) -> tuple[Mapping[str, Any], ...]:
        return await fetch_arg_row_pages(
            identity=self._identity,
            http_client=self._http,
            audience=_MANAGEMENT_AUDIENCE,
            endpoint=self._config.endpoint,
            api_version=_ARG_API_VERSION,
            subscriptions=(self._config.subscription_id,),
            query=query,
            result_name=result_name,
            page_size=record_limit,
            max_pages=1,
            max_records=record_limit,
            timeout_seconds=self._config.timeout_seconds,
            error_type=ServiceHealthError,
            throttle_gate=self._throttle_gate,
            rate_limiter=self._rate_limiter,
            max_response_bytes=self._config.max_response_bytes,
            max_total_response_bytes=self._config.max_response_bytes,
        )

    def _result(
        self,
        *,
        observed_at: datetime,
        observations: tuple[ServiceHealthObservation, ...],
        complete: bool,
        limitation: str | None,
    ) -> ServiceHealthCollection:
        material = "|".join(
            (
                observed_at.isoformat(),
                *(item.event_evidence_ref for item in observations),
                "complete" if complete else limitation or "incomplete",
            )
        )
        return ServiceHealthCollection(
            observations=observations,
            observed_at=observed_at,
            complete=complete,
            limitation=limitation,
            attempt_ref=f"azure-service-health:{hashlib.sha256(material.encode()).hexdigest()}",
        )


def _active_events_query(max_events: int) -> str:
    return (
        "ServiceHealthResources "
        "| where type =~ 'microsoft.resourcehealth/events' "
        "| where tostring(properties['Status']) =~ 'Active' "
        "| project eventName=tostring(name), "
        "trackingId=tostring(properties['TrackingId']), "
        "eventType=tostring(properties['EventType']), "
        "status=tostring(properties['Status']), "
        "level=tostring(properties['Level']), "
        "title=tostring(properties['Title']), "
        "impactStartTime=tostring(properties['ImpactStartTime']) "
        "| order by impactStartTime asc "
        f"| take {max_events + 1}"
    )


def _active_impacts_query(aliases: tuple[str, ...], max_impacts: int) -> str:
    values = ", ".join(f"'{_kusto_literal(item)}'" for item in aliases)
    return (
        "ServiceHealthResources "
        "| where type =~ 'microsoft.resourcehealth/events/impactedresources' "
        "| extend parentEventId=tostring(split(id, '/impactedResources/')[0]) "
        "| extend eventTrackingId=tostring(split(parentEventId, '/events/')[1]) "
        f"| where eventTrackingId in~ ({values}) "
        "| project eventTrackingId, "
        "targetResourceId=tostring(properties['targetResourceId']), "
        "resourceName=tostring(properties['resourceName']), "
        "resourceGroup=tostring(properties['resourceGroup']), "
        "targetResourceType=tostring(properties['targetResourceType']), "
        "targetRegion=tostring(properties['targetRegion']), "
        "status=tostring(properties['status']) "
        f"| take {max_impacts + 1}"
    )


def _event(row: Mapping[str, Any], *, observed_at: datetime) -> tuple[_Event | None, bool]:
    tracking_id = _bounded_text(row.get("trackingId"), 256)
    event_name = _bounded_text(row.get("eventName"), 256)
    aliases = tuple(
        sorted({value.casefold() for value in (tracking_id, event_name) if value is not None})
    )
    event_type_raw = _bounded_text(row.get("eventType"), 64)
    status_raw = _bounded_text(row.get("status"), 64)
    impact_start_at = _timestamp(row.get("impactStartTime"))
    if not aliases or event_type_raw is None or status_raw is None or impact_start_at is None:
        return None, False
    event_type = _EVENT_TYPES.get(_alphanumeric(event_type_raw))
    status = _machine_token(status_raw)
    if event_type is None or status != "active":
        return None, False
    if impact_start_at > observed_at:
        return None, True
    title = _bounded_text(row.get("title"), 512) or event_name
    if title is None:
        return None, False
    level_raw = _bounded_text(row.get("level"), 64)
    material = "|".join((*aliases, event_type, status, impact_start_at.isoformat()))
    return (
        _Event(
            aliases=aliases,
            event_type=event_type,
            title=title,
            level=_machine_token(level_raw) if level_raw is not None else None,
            status=status,
            impact_start_at=impact_start_at,
            evidence_ref=f"azure-service-health:{hashlib.sha256(material.encode()).hexdigest()}",
        ),
        False,
    )


def _impact(row: Mapping[str, Any]) -> _Impact | None:
    event_alias = _bounded_text(row.get("eventTrackingId"), 256)
    if event_alias is None:
        return None
    fields = (
        _bounded_text(row.get("resourceName"), 256),
        _bounded_text(row.get("targetResourceType"), 256),
        _bounded_text(row.get("resourceGroup"), 256),
        _bounded_text(row.get("targetRegion"), 128),
        _bounded_text(row.get("status"), 64),
    )
    if not any(fields):
        return None
    resource_name, resource_type, resource_group, region, status_raw = fields
    status = _machine_token(status_raw) if status_raw is not None else None
    material = "|".join((event_alias.casefold(), *(value or "" for value in fields)))
    return _Impact(
        event_alias=event_alias.casefold(),
        resource_name=resource_name,
        resource_type=resource_type,
        resource_group=resource_group,
        region=region,
        status=status,
        evidence_ref=(
            f"azure-service-health-impact:{hashlib.sha256(material.encode()).hexdigest()}"
        ),
    )


def _observation(
    event: _Event,
    *,
    observed_at: datetime,
    impact: _Impact | None,
    impact_count: int | None,
) -> ServiceHealthObservation:
    return ServiceHealthObservation(
        event_type=event.event_type,
        title=event.title,
        level=event.level,
        status=event.status,
        impact_start_at=event.impact_start_at,
        observed_at=observed_at,
        impacted_resource_count=impact_count,
        resource_name=None if impact is None else impact.resource_name,
        resource_type=None if impact is None else impact.resource_type,
        resource_group=None if impact is None else impact.resource_group,
        region=None if impact is None else impact.region,
        impact_status=None if impact is None else impact.status,
        event_evidence_ref=event.evidence_ref,
        impact_evidence_ref=None if impact is None else impact.evidence_ref,
    )


def _impact_scope_state(value: object, *, subscription_id: str) -> str:
    if value is None or value == "":
        return "valid"
    if not isinstance(value, str) or len(value) > 2048:
        return "malformed"
    folded = value.strip().casefold().rstrip("/")
    root = f"/subscriptions/{subscription_id}".casefold()
    return "valid" if folded == root or folded.startswith(f"{root}/") else "widened"


def _bounded_text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized and len(normalized) <= maximum else None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    if value.isascii() and value.isdigit():
        ticks_since_unix_epoch = int(value) - _DOTNET_UNIX_EPOCH_TICKS
        if ticks_since_unix_epoch < 0:
            return None
        try:
            return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
                microseconds=ticks_since_unix_epoch // _DOTNET_TICKS_PER_MICROSECOND
            )
        except OverflowError:
            return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _alphanumeric(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _machine_token(value: str) -> str:
    return "_".join(value.casefold().replace("-", " ").split())[:64] or "unknown"


def _kusto_literal(value: str) -> str:
    return value.replace("'", "''")


__all__ = [
    "AzureServiceHealthConfig",
    "AzureServiceHealthReader",
    "ServiceHealthError",
]
