"""Resource-group-scoped Azure Resource Graph configuration observation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.core.detection.configuration_drift import (
    ConfigurationObservation,
    ConfigurationResource,
    EvidenceCompleteness,
)
from fdai.delivery.azure.arg_query import ArgQueryError
from fdai.delivery.azure.arg_transport import fetch_arg_pages
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.workload_identity import WorkloadIdentity

_RESOURCE_GROUP = re.compile(r"^[A-Za-z0-9_.()-]{1,90}$")
_DEFAULT_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_API_VERSION: Final[str] = "2022-10-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"


@dataclass(frozen=True, slots=True)
class AzureConfigurationObservationConfig:
    """Immutable server-owned boundary for one drift observation."""

    scope_ref: str
    subscription_scope: str
    resource_group: str
    endpoint: str = _DEFAULT_ENDPOINT
    api_version: str = _DEFAULT_API_VERSION
    audience: str = _DEFAULT_AUDIENCE
    page_size: int = 1000
    max_pages: int = 8
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.scope_ref.strip() or not self.subscription_scope.strip():
            raise ValueError("scope_ref and subscription_scope MUST be non-empty")
        if _RESOURCE_GROUP.fullmatch(self.resource_group) is None:
            raise ValueError("resource_group is invalid")
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
            raise ValueError("endpoint MUST be an HTTPS origin")
        if not 1 <= self.page_size <= 1000:
            raise ValueError("page_size MUST be in [1, 1000]")
        if self.max_pages < 1 or self.timeout_seconds <= 0:
            raise ValueError("max_pages and timeout_seconds MUST be positive")


class AzureArgConfigurationObservationSource:
    """Collect a complete ARG snapshot without querying outside one resource group."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureConfigurationObservationConfig,
    ) -> None:
        self._identity = identity
        self._http = http_client
        self._config = config

    async def observe(self, *, scope: str) -> ConfigurationObservation:
        if scope != self._config.scope_ref:
            raise PermissionError("requested scope is outside the configured Azure scope")
        resources, _ = await fetch_arg_pages(
            identity=self._identity,
            http_client=self._http,
            audience=self._config.audience,
            endpoint=self._config.endpoint,
            api_version=self._config.api_version,
            subscriptions=(self._config.subscription_scope,),
            query=self._query(),
            resource_type="configuration-drift-scope",
            page_size=self._config.page_size,
            max_pages=self._config.max_pages,
            timeout_seconds=self._config.timeout_seconds,
            error_type=ArgQueryError,
            map_row=_map_row,
            project_links=lambda _row, _record: (),
        )
        observed_at = datetime.now(tz=UTC)
        return ConfigurationObservation(
            scope=self._config.scope_ref,
            observed_at=observed_at,
            source="Azure Resource Graph",
            completeness=EvidenceCompleteness.COMPLETE,
            resources=tuple(_configuration_resource(resource) for resource in resources),
        )

    def _query(self) -> str:
        group = self._config.resource_group.replace("'", "''")
        return (
            "Resources "
            f"| where resourceGroup =~ '{group}' "
            "| project id, type, name, location, kind, sku, properties, resourceGroup"
        )


def _map_row(row: Mapping[str, Any]) -> ResourceRecord | None:
    name = row.get("name")
    resource_type = row.get("type")
    location = row.get("location")
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(resource_type, str) or not resource_type:
        return None
    if not isinstance(location, str) or not location:
        return None
    attributes: dict[str, object] = {}
    kind = row.get("kind")
    if isinstance(kind, str) and kind:
        attributes["kind"] = kind
    sku = row.get("sku")
    if isinstance(sku, Mapping):
        for source_key, target_key in (("name", "sku_name"), ("tier", "sku_tier")):
            value = sku.get(source_key)
            if isinstance(value, str) and value:
                attributes[target_key] = value
    properties = row.get("properties")
    if isinstance(properties, Mapping):
        for source_key, target_key in (
            ("provisioningState", "provisioning_state"),
            ("powerState", "power_state"),
            ("publicNetworkAccess", "public_network_access"),
            ("kubernetesVersion", "kubernetes_version"),
            ("currentKubernetesVersion", "current_kubernetes_version"),
            ("version", "version"),
        ):
            value = properties.get(source_key)
            if isinstance(value, (str, bool, int, float)):
                attributes[target_key] = value
    return ResourceRecord(
        resource_id=f"{resource_type.casefold()}:{name}",
        type=resource_type,
        props={"name": name, "location": location, "attributes": attributes},
    )


def _configuration_resource(record: ResourceRecord) -> ConfigurationResource:
    name = record.props.get("name")
    location = record.props.get("location")
    attributes = record.props.get("attributes")
    if (
        not isinstance(name, str)
        or not isinstance(location, str)
        or not isinstance(attributes, Mapping)
    ):
        raise ArgQueryError("normalized ARG row is incomplete")
    return ConfigurationResource(
        local_name=name,
        resource_type=record.type,
        region=location,
        attributes=attributes,
    )


__all__ = [
    "AzureArgConfigurationObservationSource",
    "AzureConfigurationObservationConfig",
]
