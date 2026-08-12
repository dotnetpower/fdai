"""Direct Azure Resource Manager list fallback for inventory discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import quote, urlparse

import httpx

from fdai.delivery.azure.arg_projection import (
    extract_rg_contains_links,
    to_neutral_id,
    truncate_props,
)
from fdai.delivery.azure.inventory import ResourceQueryFn
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.shared.providers.inventory import LinkRecord, ResourceRecord
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_API_VERSION: Final[str] = "2021-04-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"


class ArmInventoryError(RuntimeError):
    """A direct ARM inventory shard could not complete safely."""


@dataclass(frozen=True, slots=True)
class AzureArmInventoryFactoryConfig:
    """Configure bounded direct ARM list fallback queries."""

    subscription_scopes: tuple[str, ...]
    arm_endpoint: str = _DEFAULT_ENDPOINT
    api_version: str = _DEFAULT_API_VERSION
    audience: str = _DEFAULT_AUDIENCE
    max_pages: int = 64
    timeout_seconds: float = 30.0
    max_props_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if not self.subscription_scopes:
            raise ValueError("subscription_scopes MUST NOT be empty")
        parsed = urlparse(self.arm_endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("arm_endpoint MUST be an absolute HTTPS URL")
        if self.max_pages < 1 or self.timeout_seconds <= 0:
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

    def build_query_fn(self) -> ResourceQueryFn:
        """Return one injected inventory shard reader with bounded pagination."""

        async def _fetch(
            resource_type: str,
        ) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
            try:
                entry = self._resource_types.get(resource_type)
            except KeyError:
                raise ArmInventoryError(f"unknown resource_type {resource_type!r}") from None
            if entry.azure_arm_type is None:
                return (), ()
            token = await self._identity.get_token(self._config.audience)
            headers = {"Authorization": f"Bearer {token.token}", "Accept": "application/json"}
            resources: list[ResourceRecord] = []
            for subscription in self._config.subscription_scopes:
                rows = await self._fetch_pages(
                    self._initial_url(
                        subscription=subscription,
                        resource_type=resource_type,
                        arm_type=entry.azure_arm_type,
                    ),
                    headers=headers,
                    resource_type=resource_type,
                )
                resources.extend(
                    _map_arm_row(
                        row,
                        resource_type=resource_type,
                        max_props_bytes=self._config.max_props_bytes,
                    )
                    for row in rows
                )
            return tuple(resources), extract_rg_contains_links(resources)

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
