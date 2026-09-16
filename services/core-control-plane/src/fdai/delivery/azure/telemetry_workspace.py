"""Resolve exact Azure resources to bounded Log Analytics workspace routes."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx

from fdai.delivery.azure.arg_projection import arm_id_to_type
from fdai.delivery.azure.deployment_history import AzureResourceIdentityResolver
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "management.azure.com",
        "management.azure.us",
        "management.usgovcloudapi.net",
        "management.chinacloudapi.cn",
        "management.microsoftazure.de",
    }
)
_AUDIENCE_BY_HOST: Final[dict[str, str]] = {
    host: f"https://{host}/.default" for host in _ALLOWED_HOSTS
}
_API_VERSION = re.compile(r"^\d{4}-\d{2}-\d{2}(?:-preview)?$")
_SUBSCRIPTION_SCOPE = re.compile(
    r"^/subscriptions/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}(?:/|$)",
    re.IGNORECASE,
)
_WORKSPACE_TYPE: Final[str] = "microsoft.operationalinsights/workspaces"
_APP_INSIGHTS_TYPE: Final[str] = "microsoft.insights/components"


class AzureTelemetryWorkspaceError(RuntimeError):
    """An exact telemetry workspace route could not be proved."""


@dataclass(frozen=True, slots=True)
class AzureTelemetryWorkspaceResolution:
    """Exact provider identity and additional workspace customer IDs."""

    provider_resource_id: str
    inventory_generation: str
    workspace_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.provider_resource_id or not self.inventory_generation:
            raise ValueError("telemetry workspace resolution identity MUST be non-empty")
        if len(set(self.workspace_ids)) != len(self.workspace_ids):
            raise ValueError("telemetry workspace resolution contains duplicate workspaces")
        if self.workspace_ids != tuple(sorted(self.workspace_ids)):
            raise ValueError("telemetry workspace resolution MUST be canonical")


class AzureTelemetryWorkspaceResolver(Protocol):
    """Resolve one neutral resource to its exact Azure telemetry routes."""

    async def resolve(
        self,
        resource_ref: str,
        *,
        at: datetime,
    ) -> AzureTelemetryWorkspaceResolution: ...


@dataclass(frozen=True, slots=True)
class AzureMonitorTelemetryWorkspaceConfig:
    """Server-owned ARM endpoint and bounded route-discovery limits."""

    endpoint: str = _DEFAULT_ENDPOINT
    audience: str = _DEFAULT_AUDIENCE
    diagnostic_settings_api_version: str = "2021-05-01-preview"
    application_insights_api_version: str = "2020-02-02"
    workspace_api_version: str = "2022-10-01"
    timeout_seconds: float = 15.0
    maximum_workspaces: int = 3
    maximum_response_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        endpoint = urlparse(self.endpoint)
        if (
            endpoint.scheme != "https"
            or endpoint.hostname not in _ALLOWED_HOSTS
            or endpoint.port not in {None, 443}
            or endpoint.path not in {"", "/"}
            or endpoint.query
            or endpoint.fragment
            or endpoint.username is not None
            or endpoint.password is not None
        ):
            raise ValueError("telemetry workspace endpoint MUST be an approved Azure origin")
        if self.audience != _AUDIENCE_BY_HOST[endpoint.hostname]:
            raise ValueError("telemetry workspace audience MUST match the Azure endpoint cloud")
        versions = (
            self.diagnostic_settings_api_version,
            self.application_insights_api_version,
            self.workspace_api_version,
        )
        if any(_API_VERSION.fullmatch(version) is None for version in versions):
            raise ValueError("telemetry workspace API versions MUST be dated Azure versions")
        if not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("telemetry workspace timeout_seconds MUST be in [0.1, 30]")
        if not 1 <= self.maximum_workspaces <= 3:
            raise ValueError("telemetry workspace maximum_workspaces MUST be in [1, 3]")
        if not 1 <= self.maximum_response_bytes <= 4 * 1024 * 1024:
            raise ValueError("telemetry workspace response byte bound is invalid")


class AzureMonitorTelemetryWorkspaceResolver:
    """Read Diagnostic Settings and workspace-based App Insights relationships."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        resource_identities: AzureResourceIdentityResolver,
        http_client: httpx.AsyncClient,
        config: AzureMonitorTelemetryWorkspaceConfig | None = None,
    ) -> None:
        self._identity = identity
        self._resource_identities = resource_identities
        self._http = http_client
        self._config = config or AzureMonitorTelemetryWorkspaceConfig()

    async def resolve(
        self,
        resource_ref: str,
        *,
        at: datetime,
    ) -> AzureTelemetryWorkspaceResolution:
        """Return exact workspace customer IDs or fail without widening scope."""

        try:
            identity = await self._resource_identities.resolve(resource_ref, at=at)
        except Exception as exc:  # noqa: BLE001 - normalize persistence at the provider boundary
            raise AzureTelemetryWorkspaceError(
                "telemetry resource identity resolution failed"
            ) from exc
        if identity is None:
            raise AzureTelemetryWorkspaceError("telemetry resource identity is unavailable")
        provider_id = _validate_resource_id(identity.provider_resource_id)
        try:
            token = await self._identity.get_token(self._config.audience)
        except Exception as exc:  # noqa: BLE001 - normalize identity adapters
            raise AzureTelemetryWorkspaceError("telemetry workspace identity failed") from exc
        headers = {"Authorization": f"Bearer {token.token}", "Accept": "application/json"}

        workspace_resources = list(await self._diagnostic_workspaces(provider_id, headers))
        provider_type = arm_id_to_type(provider_id)
        if provider_type is None:  # pragma: no cover - guaranteed by _validate_resource_id
            raise AzureTelemetryWorkspaceError("telemetry resource type is unavailable")
        if provider_type.casefold() == _APP_INSIGHTS_TYPE:
            component_workspace = await self._application_insights_workspace(provider_id, headers)
            if component_workspace is not None:
                workspace_resources.append(component_workspace)
        workspace_resources = list(_canonical_resource_ids(workspace_resources))
        if len(workspace_resources) > self._config.maximum_workspaces:
            raise AzureTelemetryWorkspaceError("telemetry workspace route count exceeded")

        customer_ids = {
            await self._workspace_customer_id(workspace_id, headers)
            for workspace_id in sorted(workspace_resources, key=str.casefold)
        }
        return AzureTelemetryWorkspaceResolution(
            provider_resource_id=provider_id,
            inventory_generation=identity.inventory_generation,
            workspace_ids=tuple(sorted(customer_ids)),
        )

    async def _diagnostic_workspaces(
        self,
        provider_id: str,
        headers: Mapping[str, str],
    ) -> tuple[str, ...]:
        payload = await self._get(
            f"{provider_id}/providers/Microsoft.Insights/diagnosticSettings",
            api_version=self._config.diagnostic_settings_api_version,
            headers=headers,
        )
        values = payload.get("value") if isinstance(payload, Mapping) else None
        if not isinstance(values, list):
            raise AzureTelemetryWorkspaceError("Diagnostic Settings response is malformed")
        if payload.get("nextLink") not in {None, ""}:
            raise AzureTelemetryWorkspaceError("Diagnostic Settings response is partial")
        workspaces: list[str] = []
        for item in values:
            properties = item.get("properties") if isinstance(item, Mapping) else None
            if not isinstance(properties, Mapping):
                raise AzureTelemetryWorkspaceError("Diagnostic Settings row is malformed")
            _validate_diagnostic_setting_identity(item, provider_id=provider_id)
            workspace_id = properties.get("workspaceId")
            if workspace_id is None:
                continue
            if not isinstance(workspace_id, str):
                raise AzureTelemetryWorkspaceError("Diagnostic Settings workspace is malformed")
            workspaces.append(_validate_workspace_id(workspace_id))
        return tuple(workspaces)

    async def _application_insights_workspace(
        self,
        provider_id: str,
        headers: Mapping[str, str],
    ) -> str | None:
        payload = await self._get(
            provider_id,
            api_version=self._config.application_insights_api_version,
            headers=headers,
        )
        _validate_response_identity(
            payload,
            expected_id=provider_id,
            expected_type=_APP_INSIGHTS_TYPE,
        )
        properties = payload.get("properties")
        if not isinstance(properties, Mapping):
            raise AzureTelemetryWorkspaceError("Application Insights response is malformed")
        workspace_id = properties.get("WorkspaceResourceId", properties.get("workspaceResourceId"))
        if workspace_id is None:
            return None
        if not isinstance(workspace_id, str):
            raise AzureTelemetryWorkspaceError("Application Insights workspace is malformed")
        return _validate_workspace_id(workspace_id)

    async def _workspace_customer_id(
        self,
        workspace_id: str,
        headers: Mapping[str, str],
    ) -> str:
        payload = await self._get(
            workspace_id,
            api_version=self._config.workspace_api_version,
            headers=headers,
        )
        _validate_response_identity(
            payload,
            expected_id=workspace_id,
            expected_type=_WORKSPACE_TYPE,
        )
        properties = payload.get("properties")
        customer_id = properties.get("customerId") if isinstance(properties, Mapping) else None
        if not isinstance(customer_id, str):
            raise AzureTelemetryWorkspaceError("Log Analytics workspace identity is malformed")
        try:
            return str(UUID(customer_id))
        except ValueError as exc:
            raise AzureTelemetryWorkspaceError(
                "Log Analytics workspace customer id is malformed"
            ) from exc

    async def _get(
        self,
        path: str,
        *,
        api_version: str,
        headers: Mapping[str, str],
    ) -> Any:
        try:
            response = await self._http.get(
                f"{self._config.endpoint.rstrip('/')}{path}",
                params={"api-version": api_version},
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise AzureTelemetryWorkspaceError("telemetry workspace ARM request failed") from exc
        if response.status_code >= 400:
            raise AzureTelemetryWorkspaceError(
                f"telemetry workspace ARM request returned HTTP {response.status_code}"
            )
        if len(response.content) > self._config.maximum_response_bytes:
            raise AzureTelemetryWorkspaceError("telemetry workspace ARM response exceeded limit")
        try:
            return response.json()
        except ValueError as exc:
            raise AzureTelemetryWorkspaceError(
                "telemetry workspace ARM response was not JSON"
            ) from exc


def _validate_resource_id(value: str) -> str:
    normalized = value.strip()
    if (
        _SUBSCRIPTION_SCOPE.match(normalized) is None
        or len(normalized) > 2_048
        or any(ord(character) < 32 for character in normalized)
        or any(character in normalized for character in ("?", "#", "\\"))
        or "//" in normalized
        or normalized.endswith("/")
        or arm_id_to_type(normalized) is None
    ):
        raise AzureTelemetryWorkspaceError("telemetry resource identity is not a bounded ARM id")
    return normalized


def _canonical_resource_ids(values: list[str]) -> tuple[str, ...]:
    by_identity: dict[str, str] = {}
    for value in values:
        by_identity.setdefault(value.casefold(), value)
    return tuple(by_identity[key] for key in sorted(by_identity))


def _validate_diagnostic_setting_identity(
    payload: Mapping[str, Any],
    *,
    provider_id: str,
) -> None:
    resource_id = payload.get("id")
    resource_type = payload.get("type")
    prefix = f"{provider_id}/providers/Microsoft.Insights/diagnosticSettings/"
    if (
        not isinstance(resource_id, str)
        or not resource_id.casefold().startswith(prefix.casefold())
        or "/" in resource_id[len(prefix) :]
        or not isinstance(resource_type, str)
        or resource_type.casefold() != "microsoft.insights/diagnosticsettings"
    ):
        raise AzureTelemetryWorkspaceError("Diagnostic Settings identity mismatch")


def _validate_workspace_id(value: str) -> str:
    normalized = _validate_resource_id(value)
    resource_type = arm_id_to_type(normalized)
    if resource_type is None or resource_type.casefold() != _WORKSPACE_TYPE:
        raise AzureTelemetryWorkspaceError("telemetry destination is not Log Analytics")
    return normalized


def _validate_response_identity(
    payload: Any,
    *,
    expected_id: str,
    expected_type: str,
) -> None:
    if not isinstance(payload, Mapping):
        raise AzureTelemetryWorkspaceError("telemetry workspace ARM response is malformed")
    resource_id = payload.get("id")
    resource_type = payload.get("type")
    if (
        not isinstance(resource_id, str)
        or resource_id.casefold() != expected_id.casefold()
        or not isinstance(resource_type, str)
        or resource_type.casefold() != expected_type
    ):
        raise AzureTelemetryWorkspaceError("telemetry workspace ARM identity mismatch")


__all__ = [
    "AzureMonitorTelemetryWorkspaceConfig",
    "AzureMonitorTelemetryWorkspaceResolver",
    "AzureTelemetryWorkspaceError",
    "AzureTelemetryWorkspaceResolution",
    "AzureTelemetryWorkspaceResolver",
]
