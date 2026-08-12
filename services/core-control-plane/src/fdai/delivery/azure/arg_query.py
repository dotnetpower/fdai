"""Azure Resource Graph query factory - turns a
:class:`~fdai.shared.providers.inventory.Inventory` shard call into a
real Kusto-over-ARG REST request.

Design boundaries
-----------------

- ``core/`` never imports this module. It sits under ``delivery/azure/`` and
  is bound at the composition root through the existing
  :type:`~fdai.delivery.azure.inventory.ResourceQueryFn` seam
  (a plain async callable). The
  :class:`~fdai.delivery.azure.inventory.AzureResourceGraphInventory`
  keeps its bounded-concurrency + atomic-promote fence guarantees; this
  file adds only the "how do I fetch one shard from ARG" concern.
- Identity flows through the injected
  :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`
  Protocol - no ``DefaultAzureCredential``, no ``azure-identity`` import.
  A fork MAY plug in IRSA / SPIFFE / GCP-WIF under the same seam.
- HTTP transport is an injected :class:`httpx.AsyncClient`. Tests pass a
  client backed by :class:`httpx.MockTransport`; production wires a
  long-lived shared client at the composition root.
- Kusto query and CSP-neutral → ARM-type mapping come from
  :class:`~fdai.rule_catalog.schema.resource_type.ResourceTypeRegistry`
  (the ``azure_arm_type`` field). Resource types with ``azure_arm_type is None``
  are not shardable from ARG and are silently skipped by the factory.

What this cut ships (Step 3d)
-----------------------------

- Bearer-token authenticated ``POST`` against the ARG REST endpoint under
  a bounded per-request timeout.
- ``$skipToken`` pagination - the loop halts on an empty token or an empty
  ``data`` page.
- Response → :class:`ResourceRecord` mapping (``resource_id`` = CSP-neutral
  path; ``provider_ref`` = raw ARM id; ``props`` carries a length-bounded
  subset of the ARG row).
- **``contains`` link extraction** from the ARM id hierarchy: every
  resource inside a resource-group emits a ``contains(rg, resource)``
  edge. Purely a function of the ARM id - never reads untrusted vendor
  ``properties`` for this - so the blast-radius seam has a real edge
  set without a trust boundary.
- **``attached_to`` link extraction** from a narrow whitelist of
  well-known ``properties`` paths (``subnet.id`` /
  ``networkSecurityGroup.id`` / ``publicIPAddress.id``). The referenced
  target's CSP-neutral ``resource_type`` is resolved through the
  vocabulary's ``azure_arm_type`` reverse map; targets whose ARM type
  is not in the vocabulary are dropped rather than emitted with an
  unknown ``to_type``.
- **``depends_on`` link extraction** from a separate soft-dependency
  whitelist (``storageAccount.id`` / ``workspaceResourceId`` /
  ``acrLoginServer``). The first two carry ARM ids and resolve through
  the same reverse map as ``attached_to``; ``acrLoginServer`` is a DNS
  name that requires a login-server → ARM id registry lookup and is
  skipped when the resolver cannot map it (the current default -
  positive resolution lands when the ACR registry is wired).

Safety / cost invariants
------------------------

- **Bounded pagination**: :attr:`AzureArgQueryFactoryConfig.max_pages` caps
  the number of ``$skipToken`` follows so a runaway subscription cannot
  starve the event loop.
- **Bounded record size**: property maps are truncated at
  :attr:`AzureArgQueryFactoryConfig.max_props_bytes` to keep untrusted
  vendor properties inert.
- **Fail-closed on partial**: a non-2xx response or a malformed page
  raises :class:`ArgQueryError`. The
  :class:`~fdai.delivery.azure.inventory.AzureResourceGraphInventory`
  cancels outstanding shards and skips the ``final=True`` fence, so the
  caller retains the previous graph - matches ``csp-neutrality.md § 5``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.delivery.azure.arg_projection import (
    arm_id_to_type as _arm_id_to_type,  # noqa: F401 - tested compatibility import
)
from fdai.delivery.azure.arg_projection import (
    build_arm_to_neutral_map as _build_arm_to_neutral_map,
)
from fdai.delivery.azure.arg_projection import (
    extract_rg_contains_links as _extract_rg_contains_links,  # noqa: F401 - D1 compatibility
)
from fdai.delivery.azure.arg_projection import (
    materialize_nested_subnets as _materialize_nested_subnets,
)
from fdai.delivery.azure.arg_projection import resource_operational_status
from fdai.delivery.azure.arg_projection import (
    to_neutral_id as _to_neutral_id,
)
from fdai.delivery.azure.arg_projection import (
    truncate_props as _truncate_props,
)
from fdai.delivery.azure.arg_relationships import (
    RelationshipProjectionResult,
    project_provider_relationships,
)
from fdai.delivery.azure.arg_transport import ArgThrottleGate, fetch_arg_pages
from fdai.delivery.azure.inventory import ResourceQueryFn, ResourceQueryResult
from fdai.delivery.inventory_schedule import (
    VM_SHUTDOWN_SCHEDULE_TYPE,
    project_vm_shutdown_schedule,
)
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    ProviderRelationshipMappingCatalog,
    load_provider_relationship_mapping_catalog,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    resolve_azure_resource_type,
)
from fdai.shared.providers.inventory import LinkRecord, ResourceRecord
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ARG_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_ARG_API_VERSION: Final[str] = "2022-10-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_DEFAULT_PAGE_SIZE: Final[int] = 1000
_DEFAULT_MAX_PAGES: Final[int] = 32
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_PROPS_BYTES: Final[int] = 64 * 1024
_DEFAULT_RELATIONSHIP_MAPPING_ROOT: Final[Path] = Path(
    "rule-catalog/vocabulary/provider-relationship-mappings"
)


class ArgQueryError(RuntimeError):
    """Raised when an ARG shard query fails or returns unusable output.

    The message is safe to log - it never carries raw response bodies or
    tenant-identifying values, only the failing shard's resource_type,
    HTTP status, and a short-truncated reason string.
    """


@dataclass(frozen=True, slots=True)
class AzureArgQueryFactoryConfig:
    """Configuration for the ARG query factory.

    Every value has a documented default so the composition root
    only needs to supply what a fork wants to override.
    """

    subscription_scopes: tuple[str, ...]
    """Subscription (or management-group) ids the ARG query runs over.

    MUST NOT be empty; ARG rejects the request when no scope is supplied,
    and an empty scope is almost always an environment-loading bug.
    """

    arg_endpoint: str = _DEFAULT_ARG_ENDPOINT
    """Root URL for the ARM control plane; ``azure-china`` / ``us-gov`` clouds override this."""

    arg_api_version: str = _DEFAULT_ARG_API_VERSION
    """ARG REST API version.

    Pinned by the adapter, not the SDK - a version bump is an intentional,
    reviewable change (contract diff), never a mid-flight upgrade.
    """

    audience: str = _DEFAULT_AUDIENCE
    """OIDC audience the executor requests from :class:`WorkloadIdentity`."""

    page_size: int = _DEFAULT_PAGE_SIZE
    """ARG `$top` value; the API caps this at 1000."""

    max_pages: int = _DEFAULT_MAX_PAGES
    """Upper bound on ``$skipToken`` follow-ups per shard.

    Ceiling defense against a runaway result set. Exceeding it raises
    :class:`ArgQueryError` - the caller retries with a narrower query
    rather than silently truncating.
    """

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    """Per-HTTP-request timeout applied to every page fetch."""

    max_props_bytes: int = _DEFAULT_MAX_PROPS_BYTES
    """Cap on the serialized size of the untrusted ``props`` map per record.

    Vendor properties (tags, descriptions) are inert data and MUST be
    length-bounded before they flow into the ontology graph.
    """

    relationship_mapping_root: Path = _DEFAULT_RELATIONSHIP_MAPPING_ROOT
    """Reviewed provider relationship mapping catalog loaded at adapter startup."""


class AzureArgQueryFactory:
    """Build a :type:`ResourceQueryFn` bound to a WorkloadIdentity + HTTP client."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        resource_types: ResourceTypeRegistry,
        http_client: httpx.AsyncClient,
        config: AzureArgQueryFactoryConfig,
    ) -> None:
        if not config.subscription_scopes:
            raise ValueError("AzureArgQueryFactoryConfig.subscription_scopes MUST NOT be empty")
        if config.page_size < 1 or config.page_size > 1000:
            raise ValueError("page_size MUST be in [1, 1000]")
        if config.max_pages < 1:
            raise ValueError("max_pages MUST be >= 1")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if config.max_props_bytes < 1024:
            raise ValueError("max_props_bytes MUST be >= 1024")
        parsed_endpoint = urlparse(config.arg_endpoint)
        if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc:
            raise ValueError("arg_endpoint MUST be an absolute HTTPS URL")
        if not config.audience.startswith("https://"):
            raise ValueError("audience MUST be an HTTPS URI")

        self._identity: Final[WorkloadIdentity] = identity
        self._resource_types: Final[ResourceTypeRegistry] = resource_types
        self._http: Final[httpx.AsyncClient] = http_client
        self._config: Final[AzureArgQueryFactoryConfig] = config
        self._throttle_gate = ArgThrottleGate()
        # Pre-compute the ARM-type → neutral-id reverse map once. Every
        # `attached_to` extraction hits this map per referenced id; a
        # fresh iteration per row would be O(vocabulary_size * rows).
        self._arm_to_neutral: Final[Mapping[str, str]] = _build_arm_to_neutral_map(resource_types)
        self._relationship_mappings: Final[ProviderRelationshipMappingCatalog] = (
            load_provider_relationship_mapping_catalog(config.relationship_mapping_root)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_query_fn(self) -> ResourceQueryFn:
        """Return a :type:`ResourceQueryFn` closed over this factory's state."""

        async def _fetch(
            resource_type: str,
        ) -> ResourceQueryResult:
            query_resource_type = (
                "network.vnet" if resource_type == "network.subnet" else resource_type
            )
            arm_type = self._resolve_arm_type(query_resource_type)
            if arm_type is None:
                # The vocabulary does not declare an ARM path for this
                # CSP-neutral type - nothing to fetch from Azure. This is
                # a legitimate no-op, not an error (e.g. a future
                # `secret-store` variant with no direct ARM equivalent).
                return ResourceQueryResult()

            shard = await self._fetch_all_pages(
                resource_type=query_resource_type, arm_type=arm_type
            )
            if resource_type == "network.subnet":
                subnet_records: list[ResourceRecord] = []
                for vnet in shard.resources:
                    nested_records, _legacy_links = _materialize_nested_subnets(vnet)
                    subnet_records.extend(nested_records)
                subnet_ids = {record.resource_id for record in subnet_records}
                subnet_links = tuple(
                    link
                    for link in shard.links
                    if link.link_type == "contains" and link.to_id in subnet_ids
                )
                return ResourceQueryResult(
                    resources=tuple(subnet_records),
                    links=subnet_links,
                    relationship_drops=shard.relationship_drops,
                )
            return shard

        return _fetch

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_arm_type(self, resource_type: str) -> str | None:
        try:
            entry = self._resource_types.get(resource_type)
        except KeyError:
            # Unknown resource_type is a caller bug, not our concern here;
            # the Inventory shard set comes from the same vocabulary.
            raise ArgQueryError(
                f"unknown resource_type {resource_type!r} (not in vocabulary)"
            ) from None
        return entry.azure_arm_type

    def _build_query(self, *, arm_type: str) -> str:
        # Kusto: quote the arm_type as a case-insensitive equality; project
        # only the fields the mapper reads. Adding fields is a versioned
        # change, not an ad-hoc query mutation.
        # `arm_type` is enum-constrained via ResourceTypeRegistry so a
        # quote-escape isn't reachable, but we still guard by rejecting
        # any embedded single-quote at the boundary.
        if "'" in arm_type:
            raise ArgQueryError(f"illegal character in ARM type {arm_type!r}")
        resource_groups = arm_type.lower() == "microsoft.resources/resourcegroups"
        table = "ResourceContainers" if resource_groups else "Resources"
        query_type = (
            "microsoft.resources/subscriptions/resourcegroups" if resource_groups else arm_type
        )
        return (
            f"{table} | where type =~ '{query_type}' "
            "| order by id asc "
            "| project id, type, name, location, kind, sku, tags, properties, "
            "resourceGroup, subscriptionId"
        )

    async def _fetch_all_pages(self, *, resource_type: str, arm_type: str) -> ResourceQueryResult:
        query = self._build_query(arm_type=arm_type)
        return await fetch_arg_pages(
            identity=self._identity,
            http_client=self._http,
            audience=self._config.audience,
            endpoint=self._config.arg_endpoint,
            api_version=self._config.arg_api_version,
            subscriptions=self._config.subscription_scopes,
            query=query,
            resource_type=resource_type,
            page_size=self._config.page_size,
            max_pages=self._config.max_pages,
            timeout_seconds=self._config.timeout_seconds,
            error_type=ArgQueryError,
            map_row=lambda row: self._map_row(row, resource_type=resource_type),
            project_links=self._project_links,
            throttle_gate=self._throttle_gate,
        )

    def _project_links(
        self, row: Mapping[str, Any], record: ResourceRecord
    ) -> RelationshipProjectionResult:
        return project_provider_relationships(
            row,
            owner=record,
            arm_to_neutral=self._arm_to_neutral,
            catalog=self._relationship_mappings,
            arm_id_to_type=_arm_id_to_type,
            to_neutral_id=_to_neutral_id,
            external_reference_resolver=_resolve_acr_login_server_to_arm_id,
        )

    def _map_row(self, row: Mapping[str, Any], *, resource_type: str) -> ResourceRecord | None:
        arm_id = row.get("id")
        if not isinstance(arm_id, str) or not arm_id:
            raise ArgQueryError(f"ARG row for {resource_type!r} lacks a provider id")
        arm_type = self._resource_types.get(resource_type).azure_arm_type
        if arm_type is None:
            return None
        resolved_type = resolve_azure_resource_type(
            self._resource_types,
            arm_type=arm_type,
            kind=row.get("kind"),
        )
        if (
            resolved_type is None
            and sum(
                1
                for entry in self._resource_types
                if entry.azure_arm_type is not None
                and entry.azure_arm_type.casefold() == arm_type.casefold()
            )
            > 1
        ):
            raise ArgQueryError("shared Azure ARM type row has ambiguous kind")
        if resolved_type != resource_type:
            return None

        neutral_id = _to_neutral_id(arm_id)
        props: dict[str, Any] = {"providerType": arm_type}
        subscription_id = row.get("subscriptionId")
        if isinstance(subscription_id, str) and subscription_id:
            props["subscriptionId"] = subscription_id
        for key in ("name", "location", "kind", "sku", "tags", "properties", "resourceGroup"):
            if key in row and row[key] is not None:
                props[key] = row[key]
        if status := resource_operational_status(row):
            props["status"] = status
        if resource_type == VM_SHUTDOWN_SCHEDULE_TYPE:
            schedule = project_vm_shutdown_schedule(props)
            if schedule is None:
                return None
            props.update(schedule)
            nested_value = props.get("properties")
            nested_schedule = dict(nested_value) if isinstance(nested_value, Mapping) else {}
            nested_schedule.pop("targetResourceId", None)
            props["properties"] = nested_schedule

        props = _truncate_props(props, max_bytes=self._config.max_props_bytes)

        return ResourceRecord(
            resource_id=neutral_id,
            type=resource_type,
            props=props,
            provider_ref=arm_id,
            last_seen=datetime.now(tz=UTC).isoformat(),
        )


def _resolve_acr_login_server_to_arm_id(login_server: str) -> str | None:
    """Placeholder for the ACR login-server → ARM id registry lookup.

    Returns ``None`` in this cycle - no resolver is wired yet, so every
    ``properties.acrLoginServer`` reference is treated as unresolvable
    and dropped by :func:`_extract_depends_on_links_from_row`. Tests
    monkeypatch this hook to exercise the resolvable path when the
    registry lookup is wired.
    """
    # `login_server` is untrusted vendor text; the guard here is
    # intentionally boring so it stays inert.
    del login_server
    return None


def _extract_attached_to_links_from_row(
    row: Mapping[str, Any],
    *,
    child: ResourceRecord,
    arm_to_neutral: Mapping[str, str],
) -> tuple[LinkRecord, ...]:
    """Compatibility facade over reviewed ``attached_to`` mappings."""

    catalog = load_provider_relationship_mapping_catalog(_DEFAULT_RELATIONSHIP_MAPPING_ROOT)
    result = project_provider_relationships(
        row,
        owner=child,
        arm_to_neutral=arm_to_neutral,
        catalog=catalog,
        arm_id_to_type=_arm_id_to_type,
        to_neutral_id=_to_neutral_id,
        external_reference_resolver=_resolve_acr_login_server_to_arm_id,
    )
    return tuple(link for link in result.links if link.link_type == "attached_to")


def _extract_depends_on_links_from_row(
    row: Mapping[str, Any],
    *,
    child: ResourceRecord,
    arm_to_neutral: Mapping[str, str],
) -> tuple[LinkRecord, ...]:
    """Compatibility wrapper retaining the facade-level resolver hook."""
    catalog = load_provider_relationship_mapping_catalog(_DEFAULT_RELATIONSHIP_MAPPING_ROOT)
    result = project_provider_relationships(
        row,
        owner=child,
        arm_to_neutral=arm_to_neutral,
        catalog=catalog,
        arm_id_to_type=_arm_id_to_type,
        to_neutral_id=_to_neutral_id,
        external_reference_resolver=_resolve_acr_login_server_to_arm_id,
    )
    return tuple(link for link in result.links if link.link_type == "depends_on")


# Guard against accidental widening: this file MUST NOT introduce
# `azure-mgmt-*` imports. The single dependency is `httpx`.


__all__ = [
    "ArgQueryError",
    "AzureArgQueryFactory",
    "AzureArgQueryFactoryConfig",
    "_build_arm_to_neutral_map",
    "_to_neutral_id",
    "_truncate_props",
]
