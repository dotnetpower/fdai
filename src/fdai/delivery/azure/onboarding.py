"""Azure Resource Graph probe for post-provision onboarding verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.core.onboarding import (
    ObservedResource,
    ObservedRoleAssignment,
    OnboardingProbeError,
    OnboardingResourceKind,
)
from fdai.delivery.azure.arg_transport import ArgThrottleGate, fetch_arg_row_pages
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_API_VERSION: Final[str] = "2022-10-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_DEFAULT_PAGE_SIZE: Final[int] = 1000
_DEFAULT_MAX_PAGES: Final[int] = 8

_TYPE_TO_KIND: Final[dict[str, OnboardingResourceKind]] = {
    "microsoft.managedidentity/userassignedidentities": OnboardingResourceKind.EXECUTOR_IDENTITY,
    "microsoft.app/containerapps": OnboardingResourceKind.RUNTIME,
    "microsoft.containerregistry/registries": OnboardingResourceKind.CONTAINER_REGISTRY,
    "microsoft.dbforpostgresql/flexibleservers": OnboardingResourceKind.STATE_STORE,
    "microsoft.eventhub/namespaces": OnboardingResourceKind.EVENT_BUS,
    "microsoft.keyvault/vaults": OnboardingResourceKind.SECRET_STORE,
    "microsoft.operationalinsights/workspaces": OnboardingResourceKind.OBSERVABILITY_LOGS,
    "microsoft.insights/components": OnboardingResourceKind.OBSERVABILITY_APM,
}


@dataclass(frozen=True, slots=True)
class AzureOnboardingProbeConfig:
    subscription_id: str
    resource_group: str
    executor_principal_id: str
    event_role_definition_id: str
    secret_role_definition_id: str
    endpoint: str = _DEFAULT_ENDPOINT
    api_version: str = _DEFAULT_API_VERSION
    audience: str = _DEFAULT_AUDIENCE
    page_size: int = _DEFAULT_PAGE_SIZE
    max_pages: int = _DEFAULT_MAX_PAGES
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        for name in (
            "subscription_id",
            "resource_group",
            "executor_principal_id",
            "event_role_definition_id",
            "secret_role_definition_id",
        ):
            value = getattr(self, name)
            if not value or "'" in value or len(value) > 256:
                raise ValueError(f"{name} MUST be a bounded non-empty identifier")
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("endpoint MUST be an absolute HTTPS URL")
        if not 1 <= self.page_size <= 1000:
            raise ValueError("page_size MUST be in [1, 1000]")
        if self.max_pages < 1:
            raise ValueError("max_pages MUST be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be positive")


class AzureResourceProbe:
    """Observe the FDAI resource set and executor role assignments via ARG."""

    def __init__(
        self,
        *,
        config: AzureOnboardingProbeConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._identity = identity
        self._http = http_client
        self._throttle_gate = ArgThrottleGate()

    async def observed_resources(self) -> tuple[ObservedResource, ...]:
        query = (
            "Resources "
            f"| where subscriptionId =~ '{self._config.subscription_id}' "
            f"| where resourceGroup =~ '{self._config.resource_group}' "
            "| order by id asc | project id, type"
        )
        rows = await self._query(query)
        kinds = {
            kind
            for row in rows
            if isinstance(row.get("type"), str)
            if (kind := _TYPE_TO_KIND.get(str(row["type"]).lower())) is not None
        }
        return tuple(ObservedResource(kind=kind) for kind in sorted(kinds, key=str))

    async def observed_role_assignments(self) -> tuple[ObservedRoleAssignment, ...]:
        query = (
            "AuthorizationResources "
            "| where type =~ 'microsoft.authorization/roleassignments' "
            f"| where tostring(properties.principalId) =~ '{self._config.executor_principal_id}' "
            "| order by id asc "
            "| project id, roleDefinitionId=tostring(properties.roleDefinitionId), "
            "scope=tostring(properties.scope)"
        )
        rows = await self._query(query)
        observed: set[tuple[str, OnboardingResourceKind]] = set()
        for row in rows:
            role_definition_id = str(row.get("roleDefinitionId") or "").lower()
            scope = str(row.get("scope") or "").lower()
            if role_definition_id.endswith(self._config.event_role_definition_id.lower()):
                observed.add(("event_bus_data_owner", OnboardingResourceKind.EVENT_BUS))
            if role_definition_id.endswith(self._config.secret_role_definition_id.lower()) and (
                "/providers/microsoft.keyvault/vaults/" in scope
            ):
                observed.add(("secret_reader", OnboardingResourceKind.SECRET_STORE))
        return tuple(
            ObservedRoleAssignment(principal_ref="executor", role=role, scope_kind=scope_kind)
            for role, scope_kind in sorted(observed, key=lambda item: item[0])
        )

    async def _query(self, query: str) -> tuple[dict[str, Any], ...]:
        rows = await fetch_arg_row_pages(
            identity=self._identity,
            http_client=self._http,
            audience=self._config.audience,
            endpoint=self._config.endpoint,
            api_version=self._config.api_version,
            subscriptions=(self._config.subscription_id,),
            query=query,
            result_name="onboarding verification",
            page_size=self._config.page_size,
            max_pages=self._config.max_pages,
            timeout_seconds=self._config.timeout_seconds,
            error_type=OnboardingProbeError,
            throttle_gate=self._throttle_gate,
        )
        return tuple(dict(row) for row in rows)


__all__ = ["AzureOnboardingProbeConfig", "AzureResourceProbe"]
