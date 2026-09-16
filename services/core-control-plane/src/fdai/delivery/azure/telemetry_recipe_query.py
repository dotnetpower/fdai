"""Compile reviewed telemetry recipes into bounded Azure Monitor KQL."""

from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Final

import httpx

from fdai.core.rca.telemetry_evidence import (
    TelemetryEvidenceDisposition,
    TelemetryEvidenceNeed,
    TelemetryEvidenceReceipt,
    TelemetryLookbackProfile,
    TelemetryMechanism,
    build_telemetry_evidence_receipt,
)
from fdai.core.rca.telemetry_recipes import (
    DEFAULT_TELEMETRY_RECIPE_CATALOG,
    ReviewedTelemetryRecipeCatalog,
)
from fdai.delivery.azure.log_query import AzureLogAnalyticsQueryProvider
from fdai.delivery.azure.telemetry_workspace import (
    AzureTelemetryWorkspaceError,
    AzureTelemetryWorkspaceResolver,
)
from fdai.shared.providers.observation import LogQueryError

_MAX_ROWS_PER_ROUTE: Final[int] = 8
_LOOKBACKS: Final[dict[TelemetryLookbackProfile, timedelta]] = {
    TelemetryLookbackProfile.FIVE_MINUTES: timedelta(minutes=5),
    TelemetryLookbackProfile.FIFTEEN_MINUTES: timedelta(minutes=15),
    TelemetryLookbackProfile.ONE_HOUR: timedelta(hours=1),
}
_WINDOWS: Final[dict[TelemetryLookbackProfile, str]] = {
    TelemetryLookbackProfile.FIVE_MINUTES: "PT5M",
    TelemetryLookbackProfile.FIFTEEN_MINUTES: "PT15M",
    TelemetryLookbackProfile.ONE_HOUR: "PT1H",
}
_BANDS: Final[frozenset[str]] = frozenset({"low", "elevated", "high"})

_SOURCES: Final[dict[TelemetryMechanism, str]] = {
    TelemetryMechanism.FAILED_REQUESTS: (
        "AppRequests\n"
        "| project at=TimeGenerated, resource_id=tostring(coalesce("
        "Properties['cloud.resource_id'], column_ifexists('_ResourceId', ''))), "
        "magnitude=1.0, matched=tobool(column_ifexists('Success', true)) == false\n"
        "| where matched"
    ),
    TelemetryMechanism.ERROR_TIMELINE: (
        "union isfuzzy=true\n"
        "(AppExceptions | project at=TimeGenerated, resource_id=tostring(coalesce("
        "Properties['cloud.resource_id'], column_ifexists('_ResourceId', ''))), "
        "magnitude=1.0),\n"
        "(AppTraces | where toint(column_ifexists('SeverityLevel', 0)) >= 3 "
        "| project at=TimeGenerated, resource_id=tostring(coalesce("
        "Properties['cloud.resource_id'], column_ifexists('_ResourceId', ''))), "
        "magnitude=1.0)"
    ),
    TelemetryMechanism.DEPENDENCY_LATENCY: (
        "AppDependencies\n"
        "| project at=TimeGenerated, resource_id=tostring(coalesce("
        "Properties['cloud.resource_id'], column_ifexists('_ResourceId', ''))), "
        "magnitude=todouble(column_ifexists('DurationMs', 0.0))\n"
        "| where magnitude >= 1000.0"
    ),
    TelemetryMechanism.SLOW_TRACES: (
        "union isfuzzy=true\n"
        "(AppRequests | project at=TimeGenerated, resource_id=tostring(coalesce("
        "Properties['cloud.resource_id'], column_ifexists('_ResourceId', ''))), "
        "magnitude=todouble(column_ifexists('DurationMs', 0.0))),\n"
        "(AppDependencies | project at=TimeGenerated, resource_id=tostring(coalesce("
        "Properties['cloud.resource_id'], column_ifexists('_ResourceId', ''))), "
        "magnitude=todouble(column_ifexists('DurationMs', 0.0)))\n"
        "| where magnitude >= 1000.0"
    ),
    TelemetryMechanism.GUEST_SHUTDOWN: (
        "union isfuzzy=true\n"
        "(Event | project at=TimeGenerated, resource_id=tostring(column_ifexists("
        "'_ResourceId', '')), message=tostring(column_ifexists('RenderedDescription', ''))),\n"
        "(Syslog | project at=TimeGenerated, resource_id=tostring(column_ifexists("
        "'_ResourceId', '')), message=tostring(column_ifexists('SyslogMessage', '')))\n"
        "| where message has_any ('shutdown', 'power off', 'stopping')\n"
        "| project at, resource_id, magnitude=1.0"
    ),
    TelemetryMechanism.CONTAINER_RESTARTS: (
        "KubePodInventory\n"
        "| project at=TimeGenerated, resource_id=tostring(column_ifexists('_ResourceId', '')), "
        "magnitude=todouble(column_ifexists('ContainerRestartCount', 0.0))\n"
        "| where magnitude > 0.0"
    ),
    TelemetryMechanism.THROTTLING: (
        "AppRequests\n"
        "| project at=TimeGenerated, resource_id=tostring(coalesce("
        "Properties['cloud.resource_id'], column_ifexists('_ResourceId', ''))), "
        "magnitude=1.0, result_code=tostring(column_ifexists('ResultCode', ''))\n"
        "| where result_code == '429'"
    ),
    TelemetryMechanism.RESOURCE_SATURATION: (
        "Perf\n"
        "| project at=TimeGenerated, resource_id=tostring(column_ifexists('_ResourceId', '')), "
        "counter=tostring(column_ifexists('CounterName', '')), "
        "magnitude=todouble(column_ifexists('CounterValue', 0.0))\n"
        "| where counter in ('% Processor Time', '% Used Memory') and magnitude >= 70.0"
    ),
}


class AzureMonitorTelemetryRecipeProvider:
    """Execute only reviewed recipes over exact server-resolved workspaces."""

    def __init__(
        self,
        *,
        query_provider: AzureLogAnalyticsQueryProvider,
        workspace_resolver: AzureTelemetryWorkspaceResolver,
        catalog: ReviewedTelemetryRecipeCatalog = DEFAULT_TELEMETRY_RECIPE_CATALOG,
    ) -> None:
        self._query_provider = query_provider
        self._workspace_resolver = workspace_resolver
        self._catalog = catalog

    async def gather(self, need: TelemetryEvidenceNeed) -> TelemetryEvidenceReceipt:
        """Resolve, compile, and execute one exact recipe without retries."""

        recipe = self._catalog.get(need.recipe_id, need.recipe_version)
        if need.expected_output_schema_digest != recipe.output_schema_digest:
            raise ValueError("telemetry evidence need targets a substituted output schema")
        if need.lookback is not recipe.default_lookback:
            raise ValueError("telemetry evidence need changed the reviewed lookback")
        started = time.monotonic()
        try:
            resolution = await self._workspace_resolver.resolve(
                need.resource_ref,
                at=need.evidence_cutoff,
            )
        except AzureTelemetryWorkspaceError:
            return self._failure_receipt(
                need,
                disposition=TelemetryEvidenceDisposition.UNAVAILABLE,
                route_count=0,
                queried_route_count=0,
                recipe_cost=recipe.estimated_cost_units,
                started=started,
            )
        providers = _providers(self._query_provider, resolution.workspace_ids)
        route_count = len(providers)
        estimated_cost = route_count * recipe.estimated_cost_units
        if route_count > need.max_query_count:
            raise ValueError("telemetry evidence routes exceed the query budget")
        if estimated_cost > need.max_cost_units:
            raise ValueError("telemetry evidence routes exceed the cost budget")
        since = need.evidence_cutoff - _LOOKBACKS[need.lookback]
        query = _compile_recipe_kql(
            mechanism=recipe.mechanism,
            resource_id=resolution.provider_resource_id,
            since=since,
            until=need.evidence_cutoff,
        )
        facts: set[str] = set()
        observed_until: datetime | None = None
        row_count = 0
        queried = 0
        successful = 0
        truncated = False
        for provider in providers:
            queried += 1
            try:
                result = await provider.query_log(
                    query=query,
                    window=_WINDOWS[need.lookback],
                    max_rows=_MAX_ROWS_PER_ROUTE,
                )
                route_facts, route_observed_until = _result_facts(
                    result.rows,
                    mechanism=recipe.mechanism,
                    evidence_cutoff=need.evidence_cutoff,
                )
            except (LogQueryError, ValueError) as exc:
                disposition = (
                    TelemetryEvidenceDisposition.PARTIAL
                    if successful
                    else _failure_disposition(exc)
                )
                return self._failure_receipt(
                    need,
                    disposition=disposition,
                    route_count=route_count,
                    queried_route_count=queried,
                    recipe_cost=recipe.estimated_cost_units,
                    started=started,
                )
            successful += 1
            row_count += len(result.rows)
            facts.update(route_facts)
            truncated = truncated or result.truncated
            if route_observed_until is not None and (
                observed_until is None or route_observed_until > observed_until
            ):
                observed_until = route_observed_until

        if truncated:
            disposition = TelemetryEvidenceDisposition.TRUNCATED
        elif row_count:
            disposition = TelemetryEvidenceDisposition.COMPLETE
        else:
            disposition = TelemetryEvidenceDisposition.COMPLETE_NO_DATA
            observed_until = need.evidence_cutoff
        return build_telemetry_evidence_receipt(
            need=need,
            observed_until=observed_until,
            disposition=disposition,
            route_count=route_count,
            queried_route_count=queried,
            row_count=row_count,
            latency_ms=_latency_ms(started),
            estimated_cost_units=estimated_cost,
            actual_cost_units=queried * recipe.estimated_cost_units,
            fact_tokens=tuple(sorted(facts)),
            complete=disposition
            in {
                TelemetryEvidenceDisposition.COMPLETE,
                TelemetryEvidenceDisposition.COMPLETE_NO_DATA,
            },
            truncated=truncated,
        )

    @staticmethod
    def _failure_receipt(
        need: TelemetryEvidenceNeed,
        *,
        disposition: TelemetryEvidenceDisposition,
        route_count: int,
        queried_route_count: int,
        recipe_cost: int,
        started: float,
    ) -> TelemetryEvidenceReceipt:
        return build_telemetry_evidence_receipt(
            need=need,
            observed_until=None,
            disposition=disposition,
            route_count=route_count,
            queried_route_count=queried_route_count,
            row_count=0,
            latency_ms=_latency_ms(started),
            estimated_cost_units=route_count * recipe_cost,
            actual_cost_units=queried_route_count * recipe_cost,
            fact_tokens=(),
            complete=False,
            truncated=False,
        )


def _providers(
    base: AzureLogAnalyticsQueryProvider,
    discovered_workspace_ids: tuple[str, ...],
) -> tuple[AzureLogAnalyticsQueryProvider, ...]:
    ids: dict[str, str] = {}
    for workspace_id in (*discovered_workspace_ids, base.workspace_id):
        ids.setdefault(workspace_id.casefold(), workspace_id)
    return tuple(
        base if workspace_id == base.workspace_id else base.for_workspace(workspace_id)
        for workspace_id in ids.values()
    )


def _compile_recipe_kql(
    *,
    mechanism: TelemetryMechanism,
    resource_id: str,
    since: datetime,
    until: datetime,
) -> str:
    source = _SOURCES[mechanism]
    return "\n".join(
        (
            source,
            f"| where at between (datetime({since.astimezone(UTC).isoformat()}) .. "
            f"datetime({until.astimezone(UTC).isoformat()}))",
            f"| where resource_id =~ {_kql_string(resource_id)}",
            "| summarize signal_count=count(), observed_until=max(at), "
            "max_magnitude=max(magnitude)",
            "| where signal_count > 0",
            "| extend band=case(signal_count >= 20 or max_magnitude >= 90.0, 'high', "
            "signal_count >= 5 or max_magnitude >= 70.0, 'elevated', 'low')",
            "| project signal_count, observed_until, band",
        )
    )


def _result_facts(
    rows: tuple[Mapping[str, object], ...],
    *,
    mechanism: TelemetryMechanism,
    evidence_cutoff: datetime,
) -> tuple[tuple[str, ...], datetime | None]:
    facts: set[str] = set()
    observed_until: datetime | None = None
    for row in rows:
        if set(row) != {"signal_count", "observed_until", "band"}:
            raise ValueError("telemetry recipe returned an unexpected output schema")
        count = row["signal_count"]
        band = row["band"]
        if type(count) is not int or count < 1:
            raise ValueError("telemetry recipe signal_count is invalid")
        if not isinstance(band, str) or band not in _BANDS:
            raise ValueError("telemetry recipe band is invalid")
        at = _timestamp(row["observed_until"])
        if at > evidence_cutoff:
            raise ValueError("telemetry recipe observed future evidence")
        observed_until = at if observed_until is None or at > observed_until else observed_until
        facts.update((f"mechanism:{mechanism.value}", f"signal_count_band:{band}"))
    return tuple(sorted(facts)), observed_until


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("telemetry recipe observed_until is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("telemetry recipe observed_until is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("telemetry recipe observed_until MUST include timezone")
    return parsed.astimezone(UTC)


def _failure_disposition(exc: BaseException) -> TelemetryEvidenceDisposition:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, httpx.TimeoutException):
            return TelemetryEvidenceDisposition.TIMED_OUT
        current = current.__cause__
    message = str(exc).casefold()
    if "http 401" in message or "http 403" in message:
        return TelemetryEvidenceDisposition.UNAUTHORIZED
    return TelemetryEvidenceDisposition.UNAVAILABLE


def _latency_ms(started: float) -> int:
    return min(int((time.monotonic() - started) * 1_000), 300_000)


def _kql_string(value: str) -> str:
    if not value or len(value) > 2_048 or any(ord(character) < 32 for character in value):
        raise ValueError("telemetry recipe resource id is invalid")
    return "'" + value.replace("'", "''") + "'"


__all__ = ["AzureMonitorTelemetryRecipeProvider"]
