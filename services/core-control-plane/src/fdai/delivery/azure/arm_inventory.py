"""Direct Azure Resource Manager list fallback for inventory discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote, urlparse

import httpx

from fdai.delivery.azure.arg_projection import (
    arm_id_to_type,
    build_arm_to_neutral_map,
    extract_rg_contains_links,
    parent_neutral_id,
    to_neutral_id,
    truncate_props,
)
from fdai.delivery.azure.arg_relationships import project_provider_relationships
from fdai.delivery.azure.inventory import ResourceQueryFn, ResourceQueryResult
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    load_provider_relationship_mapping_catalog,
)
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.shared.providers.inventory import LinkRecord, RelationshipDrop, ResourceRecord
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_API_VERSION: Final[str] = "2021-04-01"
_DEFAULT_NETWORK_API_VERSION: Final[str] = "2024-05-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_PRIVATE_DNS_ZONE_GROUP_RESOURCE_TYPE: Final[str] = "network.private-dns-zone-group"
_PRIVATE_ENDPOINT_ARM_TYPE: Final[str] = "Microsoft.Network/privateEndpoints"
_ARM_NETWORK_SOURCE_IDENTITY: Final[str] = "azure-resource-manager-network"
_ARM_NETWORK_SOURCE_SCHEMA_DIGEST: Final[str] = (
    "sha256:85f648ec3f355e57c946e3e7fafad89e5b06ac8b8804eaa6ebba779a6aa939fb"
)
_DEFAULT_RELATIONSHIP_MAPPING_ROOT: Final[Path] = Path(
    "rule-catalog/vocabulary/provider-relationship-mappings"
)


class ArmInventoryError(RuntimeError):
    """A direct ARM inventory shard could not complete safely."""


@dataclass(frozen=True, slots=True)
class AzureArmInventoryFactoryConfig:
    """Configure bounded direct ARM list fallback queries."""

    subscription_scopes: tuple[str, ...]
    arm_endpoint: str = _DEFAULT_ENDPOINT
    api_version: str = _DEFAULT_API_VERSION
    network_api_version: str = _DEFAULT_NETWORK_API_VERSION
    audience: str = _DEFAULT_AUDIENCE
    max_pages: int = 64
    max_child_collections: int = 2_048
    timeout_seconds: float = 30.0
    max_props_bytes: int = 64 * 1024
    relationship_mapping_root: Path = _DEFAULT_RELATIONSHIP_MAPPING_ROOT

    def __post_init__(self) -> None:
        if not self.subscription_scopes:
            raise ValueError("subscription_scopes MUST NOT be empty")
        parsed = urlparse(self.arm_endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("arm_endpoint MUST be an absolute HTTPS URL")
        if self.max_pages < 1 or self.max_child_collections < 1 or self.timeout_seconds <= 0:
            raise ValueError("ARM page and timeout limits MUST be positive")
        if self.max_props_bytes < 1024:
            raise ValueError("max_props_bytes MUST be >= 1024")


class AzureArmInventoryFactory:
    """Build a resource-type shard reader over ARM list REST APIs."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        resource_types: ResourceTypeRegistry,
        http_client: httpx.AsyncClient,
        config: AzureArmInventoryFactoryConfig,
    ) -> None:
        self._identity = identity
        self._resource_types = resource_types
        self._http = http_client
        self._config = config
        self._endpoint_host = urlparse(config.arm_endpoint).netloc.lower()
        self._arm_to_neutral = build_arm_to_neutral_map(resource_types)
        self._relationship_mappings = load_provider_relationship_mapping_catalog(
            config.relationship_mapping_root
        )

    def build_query_fn(self) -> ResourceQueryFn:
        """Return one injected inventory shard reader with bounded pagination."""

        async def _fetch(resource_type: str) -> ResourceQueryResult:
            try:
                entry = self._resource_types.get(resource_type)
            except KeyError:
                raise ArmInventoryError(f"unknown resource_type {resource_type!r}") from None
            if entry.azure_arm_type is None:
                return ResourceQueryResult()
            token = await self._identity.get_token(self._config.audience)
            headers = {"Authorization": f"Bearer {token.token}", "Accept": "application/json"}
            resources: list[ResourceRecord] = []
            links: list[LinkRecord] = []
            relationship_drops: list[RelationshipDrop] = []
            for subscription in self._config.subscription_scopes:
                if resource_type == _PRIVATE_DNS_ZONE_GROUP_RESOURCE_TYPE:
                    rows = await self._fetch_private_dns_zone_groups(
                        subscription=subscription,
                        headers=headers,
                    )
                else:
                    rows = await self._fetch_pages(
                        self._initial_url(
                            subscription=subscription,
                            resource_type=resource_type,
                            arm_type=entry.azure_arm_type,
                        ),
                        headers=headers,
                        resource_type=resource_type,
                    )
                mapped_resources = tuple(
                    _map_arm_row(
                        row,
                        resource_type=resource_type,
                        max_props_bytes=self._config.max_props_bytes,
                    )
                    for row in rows
                )
                resources.extend(mapped_resources)
                for row, resource in zip(rows, mapped_resources, strict=True):
                    projected = project_provider_relationships(
                        row,
                        owner=resource,
                        arm_to_neutral=self._arm_to_neutral,
                        catalog=self._relationship_mappings,
                        arm_id_to_type=arm_id_to_type,
                        to_neutral_id=to_neutral_id,
                        source_identity=_ARM_NETWORK_SOURCE_IDENTITY,
                        observed_schema_digest=_ARM_NETWORK_SOURCE_SCHEMA_DIGEST,
                    )
                    links.extend(projected.links)
                    relationship_drops.extend(projected.dropped)
            mapped_keys = {(link.from_id, link.link_type, link.to_id) for link in links}
            links.extend(
                link
                for link in extract_rg_contains_links(resources)
                if resource_type != _PRIVATE_DNS_ZONE_GROUP_RESOURCE_TYPE
                if (link.from_id, link.link_type, link.to_id) not in mapped_keys
            )
            return ResourceQueryResult(
                resources=tuple(resources),
                links=tuple(links),
                relationship_drops=tuple(relationship_drops),
            )

        return _fetch

    def build_child_overlay_query_fn(self, primary_query: ResourceQueryFn) -> ResourceQueryFn:
        """Overlay ARM-only child collections onto a primary inventory query."""

        arm_query = self.build_query_fn()

        async def _fetch(
            resource_type: str,
        ) -> ResourceQueryResult | tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
            if resource_type == _PRIVATE_DNS_ZONE_GROUP_RESOURCE_TYPE:
                return await arm_query(resource_type)
            return await primary_query(resource_type)

        return _fetch

    def _initial_url(self, *, subscription: str, resource_type: str, arm_type: str) -> str:
        root = self._config.arm_endpoint.rstrip("/")
        encoded_subscription = quote(subscription, safe="")
        if resource_type == "resource-group":
            return (
                f"{root}/subscriptions/{encoded_subscription}/resourcegroups"
                f"?api-version={self._config.api_version}"
            )
        filter_value = quote(f"resourceType eq '{arm_type}'", safe="")
        return (
            f"{root}/subscriptions/{encoded_subscription}/resources"
            f"?api-version={self._config.api_version}&$filter={filter_value}"
        )

    async def _fetch_private_dns_zone_groups(
        self,
        *,
        subscription: str,
        headers: Mapping[str, str],
    ) -> tuple[Mapping[str, Any], ...]:
        """List DNS zone groups through each bounded Private Endpoint child collection."""

        private_endpoints = await self._fetch_pages(
            self._initial_url(
                subscription=subscription,
                resource_type="network.private-endpoint",
                arm_type=_PRIVATE_ENDPOINT_ARM_TYPE,
            ),
            headers=headers,
            resource_type="network.private-endpoint",
        )
        if len(private_endpoints) > self._config.max_child_collections:
            raise ArmInventoryError(
                "ARM Private Endpoint child collection cap "
                f"({self._config.max_child_collections}) exceeded"
            )

        rows: list[Mapping[str, Any]] = []
        for private_endpoint in private_endpoints:
            parent_id = str(private_endpoint["id"])
            encoded_parent_id = quote(parent_id, safe="/")
            url = (
                f"{self._config.arm_endpoint.rstrip('/')}{encoded_parent_id}"
                "/privateDnsZoneGroups"
                f"?api-version={self._config.network_api_version}"
            )
            rows.extend(
                await self._fetch_pages(
                    url,
                    headers=headers,
                    resource_type=_PRIVATE_DNS_ZONE_GROUP_RESOURCE_TYPE,
                )
            )
        return tuple(rows)

    async def _fetch_pages(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        resource_type: str,
    ) -> tuple[Mapping[str, Any], ...]:
        collected: list[Mapping[str, Any]] = []
        current = url
        for page in range(self._config.max_pages):
            self._validate_next_link(current)
            try:
                response = await self._http.get(
                    current,
                    headers=headers,
                    timeout=self._config.timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise ArmInventoryError(
                    f"ARM request failed for {resource_type!r} (page {page}): {type(exc).__name__}"
                ) from exc
            if response.status_code >= 400:
                raise ArmInventoryError(
                    f"ARM returned HTTP {response.status_code} for {resource_type!r} (page {page})"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise ArmInventoryError(
                    f"ARM returned non-JSON for {resource_type!r} (page {page})"
                ) from exc
            rows = payload.get("value")
            if not isinstance(rows, list):
                raise ArmInventoryError(
                    f"ARM payload missing value array for {resource_type!r} (page {page})"
                )
            for row_index, row in enumerate(rows):
                if not isinstance(row, Mapping):
                    raise ArmInventoryError(
                        f"ARM row {row_index} is not an object for {resource_type!r} (page {page})"
                    )
                if not isinstance(row.get("id"), str) or not row["id"]:
                    raise ArmInventoryError(
                        f"ARM row {row_index} has no resource id for {resource_type!r} "
                        f"(page {page})"
                    )
                collected.append(row)
            next_link = payload.get("nextLink")
            if next_link is None:
                break
            if not isinstance(next_link, str) or not next_link:
                raise ArmInventoryError(
                    f"ARM nextLink is malformed for {resource_type!r} (page {page})"
                )
            current = next_link
        else:
            raise ArmInventoryError(
                f"ARM pagination cap ({self._config.max_pages}) exceeded for {resource_type!r}"
            )
        return tuple(collected)

    def _validate_next_link(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.lower() != self._endpoint_host:
            raise ArmInventoryError("ARM nextLink changed scheme or host")


def _map_arm_row(
    row: Mapping[str, Any],
    *,
    resource_type: str,
    max_props_bytes: int,
) -> ResourceRecord:
    arm_id = str(row["id"])
    props = truncate_props(
        {
            key: row[key]
            for key in ("name", "location", "tags", "properties", "managedBy")
            if row.get(key) is not None
        },
        max_bytes=max_props_bytes,
    )
    # Lifted after truncation so the containment anchor survives a large
    # vendor payload; `Resource.parent_id` is what scoped questions read.
    parent_id: str | None
    if resource_type == _PRIVATE_DNS_ZONE_GROUP_RESOURCE_TYPE:
        parent_id = to_neutral_id(arm_id.rsplit("/", 2)[0])
    else:
        parent_id = parent_neutral_id(arm_id)
    if parent_id is not None:
        props["parent_id"] = parent_id
    return ResourceRecord(
        resource_id=to_neutral_id(arm_id),
        type=resource_type,
        props=props,
        provider_ref=arm_id,
        last_seen=datetime.now(tz=UTC).isoformat(),
    )


__all__ = [
    "ArmInventoryError",
    "AzureArmInventoryFactory",
    "AzureArmInventoryFactoryConfig",
]
