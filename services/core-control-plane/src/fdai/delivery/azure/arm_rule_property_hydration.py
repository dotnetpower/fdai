"""Hydrate normalized Rule properties that live outside the Azure resource row.

Some evaluated properties are Azure extension or child resources rather than fields of the resource
itself: diagnostic settings, blob service data protection, SQL transparent data encryption, and the
PostgreSQL flexible server TLS parameter. This hydrator reads each one with a bounded ARM GET and
adds only the normalized property. A failed or malformed read leaves that property absent, so
Forseti records the pair as ``property_unobserved``; it never guesses a value and never fails the
inventory generation it decorates.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from fdai.delivery.azure.arm_inventory_transport import fetch_arm_json
from fdai.delivery.azure.arm_inventory_vm_state import ArmInventoryError
from fdai.delivery.azure.arm_role_assignment_hydration import (
    RoleAssignmentsUnavailableError,
    subscription_role_assignments,
)
from fdai.delivery.azure.inventory import ResourceQueryResult
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.workload_identity import WorkloadIdentity

DIAGNOSTIC_SETTINGS_API_VERSION = "2021-05-01-preview"
BLOB_SERVICE_API_VERSION = "2023-05-01"
SQL_TDE_API_VERSION = "2021-11-01"
POSTGRESQL_FLEXIBLE_API_VERSION = "2022-12-01"

_LOGGER = logging.getLogger("fdai.delivery.azure.arm_rule_property_hydration")
_DIAGNOSTIC_DESTINATIONS = (
    "workspaceId",
    "storageAccountId",
    "eventHubAuthorizationRuleId",
    "marketplacePartnerId",
)
_POSTGRESQL_FLEXIBLE_TYPE = "microsoft.dbforpostgresql/flexibleservers"

_Projection = Callable[[Mapping[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class _ExtensionRead:
    suffix: str
    api_version: str
    project: _Projection
    provider_type: str | None = None


def project_diagnostic_settings(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep settings that route at least one enabled log or metric to a destination."""

    value = payload.get("value")
    if not isinstance(value, Sequence) or isinstance(value, str):
        return {}
    settings: list[dict[str, Any]] = []
    for item in value:
        properties = item.get("properties") if isinstance(item, Mapping) else None
        if not isinstance(properties, Mapping):
            return {}
        destinations = sorted(
            key for key in _DIAGNOSTIC_DESTINATIONS if isinstance(properties.get(key), str)
        )
        enabled = sum(
            1
            for field in ("logs", "metrics")
            for entry in _entries(properties.get(field))
            if entry.get("enabled") is True
        )
        if destinations and enabled:
            settings.append({"destinations": destinations, "enabled_categories": enabled})
    return {"diagnostic_settings": settings}


def _entries(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def project_blob_service(payload: Mapping[str, Any]) -> dict[str, Any]:
    properties = payload.get("properties")
    if not isinstance(properties, Mapping):
        return {}
    projected: dict[str, Any] = {}
    retention = properties.get("deleteRetentionPolicy")
    if isinstance(retention, Mapping) and isinstance(retention.get("enabled"), bool):
        projected["blob_soft_delete_enabled"] = retention["enabled"]
    if isinstance(properties.get("isVersioningEnabled"), bool):
        projected["blob_versioning_enabled"] = properties["isVersioningEnabled"]
    return projected


def project_sql_tde(payload: Mapping[str, Any]) -> dict[str, Any]:
    properties = payload.get("properties")
    state = properties.get("state") if isinstance(properties, Mapping) else None
    if not isinstance(state, str) or state.casefold() not in {"enabled", "disabled"}:
        return {}
    return {"tde_enabled": state.casefold() == "enabled"}


def project_postgresql_secure_transport(payload: Mapping[str, Any]) -> dict[str, Any]:
    properties = payload.get("properties")
    value = properties.get("value") if isinstance(properties, Mapping) else None
    if not isinstance(value, str) or value.casefold() not in {"on", "off"}:
        return {}
    return {"ssl_enforcement": "enabled" if value.casefold() == "on" else "disabled"}


def _diagnostics(prefix: str = "") -> _ExtensionRead:
    return _ExtensionRead(
        suffix=f"{prefix}/providers/Microsoft.Insights/diagnosticSettings",
        api_version=DIAGNOSTIC_SETTINGS_API_VERSION,
        project=project_diagnostic_settings,
    )


_READS: Mapping[str, tuple[_ExtensionRead, ...]] = {
    # Storage logs are configured on the blob service, not the account.
    "object-storage": (
        _ExtensionRead("/blobServices/default", BLOB_SERVICE_API_VERSION, project_blob_service),
        _diagnostics("/blobServices/default"),
    ),
    "kubernetes-cluster": (_diagnostics(),),
    "postgresql-server": (
        _diagnostics(),
        _ExtensionRead(
            "/configurations/require_secure_transport",
            POSTGRESQL_FLEXIBLE_API_VERSION,
            project_postgresql_secure_transport,
            provider_type=_POSTGRESQL_FLEXIBLE_TYPE,
        ),
    ),
    "secret-store": (_diagnostics(),),
    "sql-database": (
        _diagnostics(),
        _ExtensionRead("/transparentDataEncryption/current", SQL_TDE_API_VERSION, project_sql_tde),
    ),
}

_MANAGED_IDENTITY = "managed-identity"
HYDRATED_RESOURCE_TYPES = frozenset({*_READS, _MANAGED_IDENTITY})


class ArmHydrationConfig(Protocol):
    """The ARM inventory limits the hydrator reuses."""

    @property
    def arm_endpoint(self) -> str: ...
    @property
    def audience(self) -> str: ...
    @property
    def timeout_seconds(self) -> float: ...
    @property
    def max_response_bytes(self) -> int: ...
    @property
    def max_attempts(self) -> int: ...
    @property
    def max_child_collections(self) -> int: ...


class ArmRulePropertyHydrator:
    """Add normalized extension properties to one primary inventory query result."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        arm_endpoint: str,
        audience: str,
        timeout_seconds: float,
        max_response_bytes: int,
        max_attempts: int,
        max_reads: int,
    ) -> None:
        self._identity = identity
        self._http = http_client
        self._endpoint = arm_endpoint.rstrip("/")
        self._audience = audience
        self._timeout = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._max_attempts = max_attempts
        self._max_reads = max_reads

    @classmethod
    def for_config(
        cls,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: ArmHydrationConfig,
    ) -> ArmRulePropertyHydrator:
        """Reuse the ARM inventory endpoint, retry, size, and child-collection limits."""

        return cls(
            identity=identity,
            http_client=http_client,
            arm_endpoint=config.arm_endpoint,
            audience=config.audience,
            timeout_seconds=config.timeout_seconds,
            max_response_bytes=config.max_response_bytes,
            max_attempts=config.max_attempts,
            max_reads=config.max_child_collections,
        )

    async def hydrate(self, result: ResourceQueryResult) -> ResourceQueryResult:
        """Return ``result`` with extension properties added where every read succeeded.

        Reads stop at ``max_reads`` per call; resources beyond the bound keep their rows as-is.
        """

        reads_left = self._max_reads
        failures = 0
        token = await self._identity.get_token(self._audience)
        headers = {"Authorization": f"Bearer {token.token}", "Accept": "application/json"}
        if any(item.type == _MANAGED_IDENTITY for item in result.resources):
            return await self._hydrate_role_assignments(result, headers)
        resources: list[ResourceRecord] = []
        for resource in result.resources:
            plan = self._plan(resource)
            if not plan or reads_left < len(plan) or resource.provider_ref is None:
                resources.append(resource)
                continue
            reads_left -= len(plan)
            added: dict[str, Any] = {}
            for read in plan:
                try:
                    payload, _ = await fetch_arm_json(
                        client=self._http,
                        url=self._url(resource.provider_ref, read),
                        headers=headers,
                        resource_type=resource.type,
                        timeout_seconds=self._timeout,
                        max_response_bytes=self._max_response_bytes,
                        max_attempts=self._max_attempts,
                    )
                except ArmInventoryError:
                    failures += 1
                    continue
                added.update(read.project(payload))
            missing = {key: value for key, value in added.items() if key not in resource.props}
            resources.append(
                dataclasses.replace(resource, props={**resource.props, **missing})
                if missing
                else resource
            )
        if failures or reads_left <= 0:
            _LOGGER.warning(
                "arm_rule_property_hydration_partial",
                extra={"failed_reads": failures, "read_budget_exhausted": reads_left <= 0},
            )
        return dataclasses.replace(result, resources=tuple(resources))

    async def _hydrate_role_assignments(
        self,
        result: ResourceQueryResult,
        headers: Mapping[str, str],
    ) -> ResourceQueryResult:
        """Attach ``role_assignments`` per identity, all or nothing per subscription."""

        reads_left = self._max_reads

        async def read_json(url: str) -> Mapping[str, Any] | None:
            nonlocal reads_left
            if reads_left <= 0:
                raise RoleAssignmentsUnavailableError("role assignment read budget exhausted")
            reads_left -= 1
            try:
                payload, _ = await fetch_arm_json(
                    client=self._http,
                    url=url,
                    headers=headers,
                    resource_type=_MANAGED_IDENTITY,
                    timeout_seconds=self._timeout,
                    max_response_bytes=self._max_response_bytes,
                    max_attempts=self._max_attempts,
                )
            except ArmInventoryError as exc:
                raise RoleAssignmentsUnavailableError("role assignment read failed") from exc
            return payload

        by_subscription: dict[str, dict[str, list[dict[str, Any]]] | None] = {}
        for subscription in sorted(
            {
                str(item.props.get("subscriptionId"))
                for item in result.resources
                if item.type == _MANAGED_IDENTITY and item.props.get("subscriptionId")
            }
        ):
            try:
                by_subscription[subscription] = await subscription_role_assignments(
                    endpoint=self._endpoint,
                    subscription_id=subscription,
                    read_json=read_json,
                )
            except RoleAssignmentsUnavailableError:
                by_subscription[subscription] = None
        unavailable = sum(value is None for value in by_subscription.values())
        if unavailable:
            _LOGGER.warning(
                "arm_role_assignment_hydration_unavailable",
                extra={"unavailable_subscriptions": unavailable},
            )
        resources: list[ResourceRecord] = []
        for resource in result.resources:
            assignments = by_subscription.get(str(resource.props.get("subscriptionId")))
            principal = _principal_id(resource)
            if (
                resource.type != _MANAGED_IDENTITY
                or assignments is None
                or principal is None
                or "role_assignments" in resource.props
            ):
                resources.append(resource)
                continue
            projected = assignments.get(principal, [])
            resources.append(
                dataclasses.replace(
                    resource, props={**resource.props, "role_assignments": projected}
                )
            )
        return dataclasses.replace(result, resources=tuple(resources))

    def _plan(self, resource: ResourceRecord) -> tuple[_ExtensionRead, ...]:
        if resource.props.get("_truncated") is True:
            return ()
        provider_type = str(resource.props.get("providerType", "")).casefold()
        return tuple(
            read
            for read in _READS.get(resource.type, ())
            if read.provider_type is None or read.provider_type == provider_type
        )

    def _url(self, provider_ref: str, read: _ExtensionRead) -> str:
        encoded = quote(f"{provider_ref}{read.suffix}", safe="/")
        return f"{self._endpoint}{encoded}?api-version={read.api_version}"


def _principal_id(resource: ResourceRecord) -> str | None:
    properties = resource.props.get("properties")
    principal = properties.get("principalId") if isinstance(properties, Mapping) else None
    return principal.casefold() if isinstance(principal, str) and principal else None


__all__ = [
    "HYDRATED_RESOURCE_TYPES",
    "ArmRulePropertyHydrator",
    "project_blob_service",
    "project_diagnostic_settings",
    "project_postgresql_secure_transport",
    "project_sql_tde",
]
