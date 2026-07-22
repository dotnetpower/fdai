"""Bounded REST transport for Azure read investigations."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.delivery.azure.read_investigation.transport import AzureRow
from fdai.shared.providers.read_investigation import ReadToolLimits, ResourceSelector
from fdai.shared.providers.workload_identity import WorkloadIdentity

_ARG_API_VERSION: Final = "2022-10-01"
_ACTIVITY_API_VERSION: Final = "2015-04-01"
_RESOURCE_HEALTH_API_VERSION: Final = "2025-05-01"
_NETWORK_API_VERSION: Final = "2025-05-01"
_MANAGEMENT_AUDIENCE: Final = "https://management.azure.com/.default"
_LOGS_AUDIENCE: Final = "https://api.loganalytics.io/.default"


class AzureReadRestError(RuntimeError):
    """A bounded Azure REST query failed without exposing response data."""


@dataclass(frozen=True, slots=True)
class AzureReadScopeBinding:
    scope_ref: str
    subscription_id: str
    resource_groups: tuple[str, ...]
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("scope_ref", self.scope_ref),
            ("subscription_id", self.subscription_id),
        ):
            _bounded(name, value)
        if not self.resource_groups or len(set(self.resource_groups)) != len(self.resource_groups):
            raise ValueError("resource_groups MUST contain unique configured groups")
        for resource_group in self.resource_groups:
            _bounded("resource_group", resource_group)
        if self.workspace_id is not None:
            _bounded("workspace_id", self.workspace_id)


@dataclass(frozen=True, slots=True)
class AzureReadRestConfig:
    scopes: tuple[AzureReadScopeBinding, ...]
    resource_type_map: tuple[tuple[str, str], ...]
    management_endpoint: str = "https://management.azure.com"
    logs_endpoint: str = "https://api.loganalytics.io"
    timeout_seconds: float = 30.0
    max_attempts: int = 3
    max_raw_response_bytes: int = 1_000_000
    activity_retention_seconds: int = 90 * 24 * 3_600
    guest_log_retention_seconds: int = 30 * 24 * 3_600

    def __post_init__(self) -> None:
        if not self.scopes or len({scope.scope_ref for scope in self.scopes}) != len(self.scopes):
            raise ValueError("Azure read scopes MUST contain unique bindings")
        if not self.resource_type_map:
            raise ValueError("resource_type_map MUST NOT be empty")
        arm = [value.casefold() for value, _ in self.resource_type_map]
        neutral = [value for _, value in self.resource_type_map]
        if len(set(arm)) != len(arm) or len(set(neutral)) != len(neutral):
            raise ValueError("resource_type_map entries MUST be one-to-one")
        for endpoint in (self.management_endpoint, self.logs_endpoint):
            parsed = urlparse(endpoint)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("Azure read endpoints MUST use https")
        if not 0.1 <= self.timeout_seconds <= 120:
            raise ValueError("timeout_seconds MUST be in [0.1, 120]")
        if not 1 <= self.max_attempts <= 5:
            raise ValueError("max_attempts MUST be in [1, 5]")
        if not 1_024 <= self.max_raw_response_bytes <= 5_000_000:
            raise ValueError("max_raw_response_bytes MUST be in [1024, 5000000]")
        if not 3_600 <= self.activity_retention_seconds <= 365 * 24 * 3_600:
            raise ValueError("activity_retention_seconds MUST be in [3600, 31536000]")
        if not 3_600 <= self.guest_log_retention_seconds <= 365 * 24 * 3_600:
            raise ValueError("guest_log_retention_seconds MUST be in [3600, 31536000]")


class AzureRestReadTransport:
    """Execute fixed Azure read projections under a reader identity."""

    transport_id = "rest"

    def __init__(
        self,
        *,
        config: AzureReadRestConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._identity = identity
        self._http = http_client
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._monotonic = monotonic or time.monotonic
        self._scopes = {scope.scope_ref: scope for scope in config.scopes}
        self._neutral_by_arm = {
            arm.casefold(): neutral for arm, neutral in config.resource_type_map
        }
        self._arm_by_neutral = {neutral: arm for arm, neutral in config.resource_type_map}

    async def resolve_resources(
        self,
        selector: ResourceSelector,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        scope = self._scope(selector.scope_ref)
        requested_groups = scope.resource_groups
        if selector.resource_group is not None:
            matching_group = next(
                (
                    group
                    for group in scope.resource_groups
                    if group.casefold() == selector.resource_group.casefold()
                ),
                None,
            )
            if matching_group is None:
                raise PermissionError("requested resource group is outside the configured scope")
            requested_groups = (matching_group,)
        group_filter = ", ".join(f"'{_escaped(group)}'" for group in requested_groups)
        clauses = [
            f"name =~ '{_escaped(selector.name)}'",
            f"resourceGroup in~ ({group_filter})",
        ]
        if selector.resource_type is not None:
            arm_type = self._arm_by_neutral.get(selector.resource_type)
            if arm_type is None:
                return ()
            clauses.append(f"type =~ '{_escaped(arm_type)}'")
        query = (
            "Resources | where "
            + " and ".join(clauses)
            + " | project id, name, type, resourceGroup "
            + f"| take {limits.max_results + 1}"
        )
        rows = await self._arg(scope, query=query, limits=limits)
        output: list[AzureRow] = []
        for row in rows:
            arm_type = _string(row.get("type"))
            neutral_type = (
                self._neutral_by_arm.get(arm_type.casefold()) if arm_type is not None else None
            )
            if neutral_type is None:
                continue
            output.append(
                {
                    "id": row.get("id"),
                    "name": row.get("name"),
                    "type": neutral_type,
                    "resource_group": row.get("resourceGroup"),
                }
            )
        return output

    async def get_resource_state(
        self,
        provider_ref: str,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        scope = self._scope_for_resource(provider_ref)
        query = (
            f"Resources | where id =~ '{_escaped(provider_ref)}' "
            "| extend state=tostring(properties.extended.instanceView.powerState.code) "
            "| project state | take 1"
        )
        rows = await self._arg(scope, query=query, limits=limits)
        observed_at = self._clock().isoformat()
        return tuple(
            {
                "observed_at": observed_at,
                "status": "observed",
                "state": (_string(row.get("state")) or "unknown").removeprefix("PowerState/"),
            }
            for row in rows[:1]
        )

    async def query_resource_activity(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        scope = self._scope_for_resource(provider_ref)
        if lookback_seconds > self._config.activity_retention_seconds:
            raise AzureReadRestError("requested Activity Log lookback exceeds configured retention")
        start = self._clock() - timedelta(seconds=lookback_seconds)
        url = (
            f"{self._config.management_endpoint.rstrip('/')}/subscriptions/"
            f"{scope.subscription_id}/providers/Microsoft.Insights/"
            "eventtypes/management/values"
        )
        payload = await self._json_request(
            "GET",
            url,
            audience=_MANAGEMENT_AUDIENCE,
            limits=limits,
            params={
                "api-version": _ACTIVITY_API_VERSION,
                "$filter": (
                    f"eventTimestamp ge '{start.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}' "
                    f"and resourceUri eq '{_escaped(provider_ref)}'"
                ),
                "$select": ("eventTimestamp,status,operationName,caller,correlationId,claims"),
            },
        )
        values = payload.get("value")
        if not isinstance(values, list):
            raise AzureReadRestError("Activity Log response missing value array")
        rows: list[AzureRow] = [
            {
                "occurred_at": value.get("eventTimestamp"),
                "status": _nested(value, "status"),
                "operation": _nested(value, "operationName"),
                "caller": value.get("caller"),
                "caller_kind": _caller_kind(value),
                "correlation": value.get("correlationId"),
            }
            for value in values
            if isinstance(value, Mapping)
        ]
        if isinstance(payload.get("nextLink"), str):
            rows.append({"_truncated": True})
        return tuple(rows)

    async def query_resource_health(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        scope = self._scope_for_resource(provider_ref)
        query = (
            "HealthResources "
            f"| where tostring(properties.targetResourceId) =~ '{_escaped(provider_ref)}' "
            f"| where todatetime(properties.occurredTime) >= ago({lookback_seconds}s) "
            "| project occurred_at=tostring(properties.occurredTime), "
            "status=tostring(properties.availabilityState), "
            "health_kind=tostring(properties.reasonType) " + f"| take {limits.max_results + 1}"
        )
        rows = await self._arg(scope, query=query, limits=limits)
        if rows:
            return rows
        payload = await self._json_request(
            "GET",
            f"{self._config.management_endpoint.rstrip('/')}{provider_ref}/providers/"
            "Microsoft.ResourceHealth/availabilityStatuses/current",
            audience=_MANAGEMENT_AUDIENCE,
            limits=limits,
            params={"api-version": _RESOURCE_HEALTH_API_VERSION},
        )
        properties = payload.get("properties")
        if not isinstance(properties, Mapping):
            return ()
        occurred_at = properties.get("occurredTime") or properties.get("reportedTime")
        status = properties.get("availabilityState")
        if not isinstance(occurred_at, str) or not isinstance(status, str):
            return ()
        observed_at = _azure_timestamp(occurred_at)
        if observed_at is None or observed_at < self._clock() - timedelta(seconds=lookback_seconds):
            return ()
        return (
            {
                "occurred_at": occurred_at,
                "status": status,
                "health_kind": properties.get("reasonType") or "unknown",
            },
        )

    async def query_guest_shutdown_events(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        scope = self._scope_for_resource(provider_ref)
        if scope.workspace_id is None:
            raise AzureReadRestError("guest log workspace is not configured")
        if lookback_seconds > self._config.guest_log_retention_seconds:
            raise AzureReadRestError("requested guest log lookback exceeds configured retention")
        query = (
            "union isfuzzy=true "
            "(Event | where EventLog == 'System' and EventID in (1074, 6006) "
            "| project occurred_at=TimeGenerated, status='observed', _ResourceId), "
            "(Syslog | where SyslogMessage has 'shutdown' or SyslogMessage has 'poweroff' "
            "| project occurred_at=TimeGenerated, status='observed', _ResourceId) "
            f"| where _ResourceId =~ '{_escaped(provider_ref)}' "
            f"| where occurred_at >= ago({lookback_seconds}s) "
            f"| project occurred_at=tostring(occurred_at), status | take {limits.max_results + 1}"
        )
        payload = await self._json_request(
            "POST",
            f"{self._config.logs_endpoint.rstrip('/')}/v1/workspaces/{scope.workspace_id}/query",
            audience=_LOGS_AUDIENCE,
            limits=limits,
            json_body={"query": query},
        )
        return _log_rows(payload)

    async def query_network_security(
        self,
        provider_ref: str,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        self._scope_for_resource(provider_ref)
        if _resource_type(provider_ref) != "microsoft.network/networksecuritygroups":
            raise AzureReadRestError("network security query requires an NSG resource")
        payload = await self._json_request(
            "GET",
            f"{self._config.management_endpoint.rstrip('/')}{provider_ref}",
            audience=_MANAGEMENT_AUDIENCE,
            limits=limits,
            params={"api-version": _NETWORK_API_VERSION},
        )
        properties = payload.get("properties")
        if not isinstance(properties, Mapping):
            raise AzureReadRestError("NSG response missing properties")
        associations = _network_associations(properties)
        observed_at = self._clock().isoformat()
        rows: list[AzureRow] = []
        for collection_name, rule_kind in (
            ("securityRules", "custom"),
            ("defaultSecurityRules", "default"),
        ):
            rules = properties.get(collection_name)
            if not isinstance(rules, list):
                continue
            for rule in rules:
                if not isinstance(rule, Mapping):
                    continue
                rule_properties = rule.get("properties")
                if not isinstance(rule_properties, Mapping):
                    continue
                rows.append(
                    {
                        "observed_at": observed_at,
                        "status": rule_properties.get("access"),
                        "rule_name": rule.get("name"),
                        "rule_kind": rule_kind,
                        "direction": rule_properties.get("direction"),
                        "protocol": rule_properties.get("protocol"),
                        "source_prefixes": _joined_values(
                            rule_properties,
                            singular="sourceAddressPrefix",
                            plural="sourceAddressPrefixes",
                        ),
                        "source_ports": _joined_values(
                            rule_properties,
                            singular="sourcePortRange",
                            plural="sourcePortRanges",
                        ),
                        "destination_prefixes": _joined_values(
                            rule_properties,
                            singular="destinationAddressPrefix",
                            plural="destinationAddressPrefixes",
                        ),
                        "destination_ports": _joined_values(
                            rule_properties,
                            singular="destinationPortRange",
                            plural="destinationPortRanges",
                        ),
                        "priority": rule_properties.get("priority"),
                        "associations": associations,
                    }
                )
        if len(rows) > limits.max_results:
            return (*rows[: limits.max_results], {"_truncated": True})
        return tuple(rows)

    async def query_network_peerings(
        self,
        provider_ref: str,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        self._scope_for_resource(provider_ref)
        if _resource_type(provider_ref) != "microsoft.network/virtualnetworks":
            raise AzureReadRestError("network peering query requires a virtual network resource")
        payload = await self._json_request(
            "GET",
            f"{self._config.management_endpoint.rstrip('/')}{provider_ref}/virtualNetworkPeerings",
            audience=_MANAGEMENT_AUDIENCE,
            limits=limits,
            params={"api-version": _NETWORK_API_VERSION},
        )
        values = payload.get("value")
        if not isinstance(values, list):
            raise AzureReadRestError("VNet peering response missing value array")
        observed_at = self._clock().isoformat()
        rows: list[AzureRow] = []
        for peering in values[: limits.max_results]:
            if not isinstance(peering, Mapping):
                continue
            properties = peering.get("properties")
            if not isinstance(properties, Mapping):
                continue
            rows.append(
                {
                    "observed_at": observed_at,
                    "status": properties.get("peeringState"),
                    "peering_name": peering.get("name"),
                    "remote_vnet": _resource_name(properties.get("remoteVirtualNetwork")),
                    "sync_level": properties.get("peeringSyncLevel"),
                    "allow_vnet_access": properties.get("allowVirtualNetworkAccess"),
                    "allow_forwarded_traffic": properties.get("allowForwardedTraffic"),
                    "allow_gateway_transit": properties.get("allowGatewayTransit"),
                    "use_remote_gateways": properties.get("useRemoteGateways"),
                    "remote_address_prefixes": _address_prefixes(
                        properties.get("remoteVirtualNetworkAddressSpace")
                        or properties.get("remoteAddressSpace")
                    ),
                    "local_subnets": _joined_strings(properties.get("localSubnetNames")),
                    "remote_subnets": _joined_strings(properties.get("remoteSubnetNames")),
                }
            )
        if len(values) > limits.max_results or isinstance(payload.get("nextLink"), str):
            rows.append({"_truncated": True})
        return tuple(rows)

    async def _arg(
        self,
        scope: AzureReadScopeBinding,
        *,
        query: str,
        limits: ReadToolLimits,
    ) -> tuple[Mapping[str, object], ...]:
        payload = await self._json_request(
            "POST",
            f"{self._config.management_endpoint.rstrip('/')}/providers/"
            f"Microsoft.ResourceGraph/resources?api-version={_ARG_API_VERSION}",
            audience=_MANAGEMENT_AUDIENCE,
            limits=limits,
            json_body={
                "subscriptions": [scope.subscription_id],
                "query": query,
                "options": {"resultFormat": "objectArray", "$top": limits.max_results + 1},
            },
        )
        data = payload.get("data")
        if not isinstance(data, list):
            raise AzureReadRestError("Resource Graph response missing data array")
        return tuple(row for row in data if isinstance(row, Mapping))

    async def _json_request(
        self,
        method: str,
        url: str,
        *,
        audience: str,
        limits: ReadToolLimits,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any]:
        token = await self._identity.get_token(audience)
        deadline = self._monotonic() + min(
            limits.timeout_seconds,
            self._config.timeout_seconds,
        )
        response: httpx.Response | None = None
        for attempt in range(self._config.max_attempts):
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                break
            try:
                response = await self._http.request(
                    method,
                    url,
                    headers={"Authorization": f"Bearer {token.token}"},
                    params=params,
                    json=json_body,
                    timeout=remaining,
                )
            except httpx.HTTPError as exc:
                if attempt + 1 >= self._config.max_attempts:
                    raise AzureReadRestError(
                        f"Azure read request failed: {type(exc).__name__}"
                    ) from exc
                await _delay(attempt, deadline=deadline, monotonic=self._monotonic)
                continue
            if response.status_code not in {429, 500, 502, 503, 504}:
                break
            if attempt + 1 < self._config.max_attempts:
                await _delay(
                    attempt,
                    deadline=deadline,
                    monotonic=self._monotonic,
                    retry_after=(
                        _retry_after_seconds(response.headers.get("Retry-After"))
                        if response.status_code == 429
                        else None
                    ),
                )
        if response is None:
            raise AzureReadRestError("Azure read request timed out")
        if response.status_code >= 400:
            raise AzureReadRestError(f"Azure read request returned HTTP {response.status_code}")
        if len(response.content) > self._config.max_raw_response_bytes:
            raise AzureReadRestError("Azure read response exceeded its raw page cap")
        try:
            payload = response.json()
        except ValueError as exc:
            raise AzureReadRestError("Azure read response was not JSON") from exc
        if not isinstance(payload, Mapping):
            raise AzureReadRestError("Azure read response was not an object")
        return payload

    def _scope(self, scope_ref: str) -> AzureReadScopeBinding:
        try:
            return self._scopes[scope_ref]
        except KeyError as exc:
            raise PermissionError("requested Azure read scope is not configured") from exc

    def _scope_for_resource(self, provider_ref: str) -> AzureReadScopeBinding:
        parts = provider_ref.strip("/").split("/")
        if (
            len(parts) < 4
            or parts[0].casefold() != "subscriptions"
            or (parts[2].casefold() != "resourcegroups")
        ):
            raise PermissionError("resolved resource is outside the configured Azure read scope")
        subscription_id = parts[1].casefold()
        resource_group = parts[3].casefold()
        matches = [
            scope
            for scope in self._config.scopes
            if subscription_id == scope.subscription_id.casefold()
            and resource_group in {group.casefold() for group in scope.resource_groups}
        ]
        if len(matches) != 1:
            raise PermissionError("resolved resource is outside the configured Azure read scope")
        return matches[0]


async def _delay(
    attempt: int,
    *,
    deadline: float,
    monotonic: Callable[[], float],
    retry_after: float | None = None,
) -> None:
    remaining = deadline - monotonic()
    if remaining > 0:
        delay = (
            retry_after
            if retry_after is not None
            else min(0.25 * (2**attempt) + secrets.randbelow(101) / 1_000, 1.0)
        )
        await asyncio.sleep(min(delay, remaining))


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None or not value.isdigit():
        return None
    return float(value)


def _bounded(name: str, value: str) -> None:
    if not value.strip() or len(value) > 256 or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be a bounded identifier")


def _escaped(value: str) -> str:
    return value.replace("'", "''")


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _azure_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _resource_type(resource_id: str) -> str:
    parts = resource_id.strip("/").split("/")
    try:
        provider_index = next(
            index for index, part in enumerate(parts) if part.casefold() == "providers"
        )
        return f"{parts[provider_index + 1]}/{parts[provider_index + 2]}".casefold()
    except (StopIteration, IndexError) as exc:
        raise AzureReadRestError("resolved resource has an invalid provider type") from exc


def _joined_values(
    properties: Mapping[str, object],
    *,
    singular: str,
    plural: str,
) -> str:
    many = properties.get(plural)
    if isinstance(many, list):
        rendered = _joined_strings(many)
        if rendered != "none":
            return rendered
    one = properties.get(singular)
    return one[:512] if isinstance(one, str) and one else "unknown"


def _joined_strings(value: object) -> str:
    if not isinstance(value, list):
        return "none"
    rendered = ",".join(item for item in value if isinstance(item, str) and item)
    return rendered[:512] or "none"


def _resource_name(value: object) -> str:
    if not isinstance(value, Mapping):
        return "unknown"
    resource_id = value.get("id")
    if not isinstance(resource_id, str) or not resource_id:
        return "unknown"
    return resource_id.rstrip("/").rsplit("/", maxsplit=1)[-1][:256]


def _address_prefixes(value: object) -> str:
    if not isinstance(value, Mapping):
        return "none"
    return _joined_strings(value.get("addressPrefixes"))


def _network_associations(properties: Mapping[str, object]) -> str:
    associations: list[str] = []
    for collection, kind in (("networkInterfaces", "nic"), ("subnets", "subnet")):
        values = properties.get(collection)
        if not isinstance(values, list):
            continue
        for value in values:
            name = _resource_name(value)
            if name != "unknown":
                associations.append(f"{kind}:{name}")
    return ",".join(associations)[:512] or "none"


def _nested(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    if isinstance(value, Mapping):
        nested = value.get("value")
        return nested if isinstance(nested, str) else None
    return value if isinstance(value, str) else None


def _caller_kind(row: Mapping[str, object]) -> str:
    claims = row.get("claims")
    if not isinstance(claims, Mapping):
        return "unknown"
    if isinstance(claims.get("xms_mirid"), str):
        return "managed_identity"
    identity_type = str(claims.get("idtyp") or "").casefold()
    if identity_type == "user":
        return "user"
    if identity_type == "app":
        return "service_principal"
    if isinstance(claims.get("http://schemas.microsoft.com/identity/claims/objectidentifier"), str):
        return "user"
    if isinstance(claims.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn"), str):
        return "user"
    if isinstance(claims.get("appid"), str):
        return "service_principal"
    return "unknown"


def _log_rows(payload: Mapping[str, object]) -> tuple[AzureRow, ...]:
    tables = payload.get("tables")
    if not isinstance(tables, list) or not tables or not isinstance(tables[0], Mapping):
        return ()
    columns = tables[0].get("columns")
    rows = tables[0].get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return ()
    names: list[str] = []
    for item in columns:
        name = item.get("name") if isinstance(item, Mapping) else None
        if not isinstance(name, str):
            return ()
        names.append(name)
    return tuple(
        dict(zip(names, row, strict=True))
        for row in rows
        if isinstance(row, list) and len(row) == len(names)
    )


__all__ = [
    "AzureReadRestConfig",
    "AzureReadRestError",
    "AzureReadScopeBinding",
    "AzureRestReadTransport",
]
