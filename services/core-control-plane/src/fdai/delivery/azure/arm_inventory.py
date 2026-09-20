"""Direct Azure Resource Manager list fallback for inventory discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote, urlparse

import httpx

from fdai.delivery.azure.arg_projection import (
    ArmIdentityError,
    ArmScopeError,
    arm_id_to_type,
    arm_provider_type,
    arm_scope_properties,
    build_arm_to_neutral_map,
    extract_rg_contains_links,
    parent_neutral_id,
    to_neutral_id,
    truncate_props,
)
from fdai.delivery.azure.arg_relationships import project_provider_relationships
from fdai.delivery.azure.arm_inventory_transport import fetch_arm_json
from fdai.delivery.azure.arm_inventory_vm_state import (
    ArmInventoryError,
)
from fdai.delivery.azure.arm_inventory_vm_state import (
    project_vmss_instance_state as _project_vmss_instance_state,
)
from fdai.delivery.azure.arm_inventory_vm_state import (
    validate_child_identity as _validate_child_identity,
)
from fdai.delivery.azure.arm_inventory_vm_state import (
    with_vm_run_command_state as _with_vm_run_command_state,
)
from fdai.delivery.azure.inventory import ResourceQueryFn, ResourceQueryResult
from fdai.delivery.azure.model_deployment import (
    MODEL_DEPLOYMENT_RESOURCE_TYPE,
    model_deployment_summary,
)
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    load_provider_relationship_mapping_catalog,
)
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry, resolve_azure_resource_type
from fdai.shared.providers.inventory import LinkRecord, RelationshipDrop, ResourceRecord
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_API_VERSION: Final[str] = "2021-04-01"
_DEFAULT_NETWORK_API_VERSION: Final[str] = "2024-05-01"
_DEFAULT_COMPUTE_API_VERSION: Final[str] = "2024-11-01"
_DEFAULT_CONTAINER_SERVICE_API_VERSION: Final[str] = "2026-05-01"
_DEFAULT_COGNITIVE_SERVICES_API_VERSION: Final[str] = "2024-10-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_PRIVATE_DNS_ZONE_GROUP_RESOURCE_TYPE: Final[str] = "network.private-dns-zone-group"
_PRIVATE_ENDPOINT_ARM_TYPE: Final[str] = "Microsoft.Network/privateEndpoints"
_AKS_AGENT_POOL_RESOURCE_TYPE: Final[str] = "kubernetes-node-pool"
_AKS_CLUSTER_RESOURCE_TYPE: Final[str] = "kubernetes-cluster"
_AKS_CLUSTER_ARM_TYPE: Final[str] = "Microsoft.ContainerService/managedClusters"
_COGNITIVE_ACCOUNT_ARM_TYPE: Final[str] = "Microsoft.CognitiveServices/accounts"
_VM_SCALE_SET_RESOURCE_TYPE: Final[str] = "compute.vm-scale-set"
_VM_SCALE_SET_ARM_TYPE: Final[str] = "Microsoft.Compute/virtualMachineScaleSets"
_VM_SCALE_SET_VM_RESOURCE_TYPE: Final[str] = "compute.vm"
_VM_SCALE_SET_NIC_RESOURCE_TYPE: Final[str] = "network.interface"
_VM_RUN_COMMAND_RESOURCE_TYPE: Final[str] = "compute.vm-run-command"
_VM_RUN_COMMAND_ARM_TYPE: Final[str] = "Microsoft.Compute/virtualMachines/runCommands"
_ARM_NETWORK_SOURCE_IDENTITY: Final[str] = "azure-resource-manager-network"
_ARM_NETWORK_SOURCE_SCHEMA_DIGEST: Final[str] = (
    "sha256:85f648ec3f355e57c946e3e7fafad89e5b06ac8b8804eaa6ebba779a6aa939fb"
)
_ARM_CONTAINER_SERVICE_SOURCE_IDENTITY: Final[str] = "azure-resource-manager-containerservice"
_ARM_CONTAINER_SERVICE_SOURCE_SCHEMA_DIGEST: Final[str] = (
    "sha256:7b74cb3dcbf1ca43b3c7f33edbddb5520e16f3ee9a6de9a9078345d93873b125"
)
_ARM_COMPUTE_SOURCE_IDENTITY: Final[str] = "azure-resource-manager-compute"
_ARM_COMPUTE_SOURCE_SCHEMA_DIGEST: Final[str] = (
    "sha256:44ea8b46d77361961316a4ce86a558768481461d8a022293cd2f4a691f16527f"
)
_ARM_COGNITIVE_SERVICES_SOURCE_IDENTITY: Final[str] = "azure-resource-manager-cognitiveservices"
_ARM_COGNITIVE_SERVICES_SOURCE_SCHEMA_DIGEST: Final[str] = (
    "sha256:77fa461069def180b2196856b142c37f7b0ef775798e211f4a5ad64ab145d1e4"
)
_DEFAULT_RELATIONSHIP_MAPPING_ROOT: Final[Path] = Path(
    "rule-catalog/vocabulary/provider-relationship-mappings"
)


@dataclass(frozen=True, slots=True)
class AzureArmInventoryFactoryConfig:
    """Configure bounded direct ARM list fallback queries."""

    subscription_scopes: tuple[str, ...]
    arm_endpoint: str = _DEFAULT_ENDPOINT
    api_version: str = _DEFAULT_API_VERSION
    network_api_version: str = _DEFAULT_NETWORK_API_VERSION
    compute_api_version: str = _DEFAULT_COMPUTE_API_VERSION
    container_service_api_version: str = _DEFAULT_CONTAINER_SERVICE_API_VERSION
    cognitive_services_api_version: str = _DEFAULT_COGNITIVE_SERVICES_API_VERSION
    audience: str = _DEFAULT_AUDIENCE
    max_pages: int = 64
    max_child_collections: int = 2_048
    timeout_seconds: float = 30.0
    max_props_bytes: int = 64 * 1024
    max_response_bytes: int = 10_000_000
    max_total_response_bytes: int = 64_000_000
    max_records: int = 50_000
    max_attempts: int = 3
    relationship_mapping_root: Path = _DEFAULT_RELATIONSHIP_MAPPING_ROOT

    def __post_init__(self) -> None:
        if not self.subscription_scopes:
            raise ValueError("subscription_scopes MUST NOT be empty")
        parsed = urlparse(self.arm_endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("arm_endpoint MUST be an absolute HTTPS URL")
        if (
            self.max_pages < 1
            or self.max_child_collections < 1
            or not isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("ARM page and timeout limits MUST be positive")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in (
                self.max_response_bytes,
                self.max_total_response_bytes,
                self.max_records,
                self.max_attempts,
            )
        ):
            raise ValueError("ARM response and retry limits MUST be positive integers")
        if self.max_props_bytes < 1024:
            raise ValueError("max_props_bytes MUST be >= 1024")
        if (
            not self.compute_api_version.strip()
            or not self.container_service_api_version.strip()
            or not self.cognitive_services_api_version.strip()
        ):
            raise ValueError("ARM child API versions MUST be non-empty")


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
                elif resource_type == _AKS_AGENT_POOL_RESOURCE_TYPE:
                    rows = await self._fetch_aks_agent_pools(
                        subscription=subscription,
                        headers=headers,
                    )
                elif resource_type == MODEL_DEPLOYMENT_RESOURCE_TYPE:
                    rows = await self._fetch_model_deployments(
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
                rows = self._select_resource_rows(rows, resource_type=resource_type)
                mapped_resources = tuple(
                    _map_arm_row(
                        row,
                        resource_type=resource_type,
                        max_props_bytes=self._config.max_props_bytes,
                    )
                    for row in rows
                )
                resources.extend(mapped_resources)
                source_identity, observed_schema_digest = _relationship_source(resource_type)
                for row, resource in zip(rows, mapped_resources, strict=True):
                    projected = project_provider_relationships(
                        row,
                        owner=resource,
                        arm_to_neutral=self._arm_to_neutral,
                        catalog=self._relationship_mappings,
                        arm_id_to_type=arm_id_to_type,
                        to_neutral_id=to_neutral_id,
                        source_identity=source_identity,
                        observed_schema_digest=observed_schema_digest,
                    )
                    links.extend(projected.links)
                    relationship_drops.extend(projected.dropped)
            mapped_keys = {(link.from_id, link.link_type, link.to_id) for link in links}
            mapped_containment_targets = {
                link.to_id
                for link in links
                if link.link_type == "contains" and link.mapping_evidence is not None
            }
            links.extend(
                link
                for link in extract_rg_contains_links(resources)
                if resource_type != _PRIVATE_DNS_ZONE_GROUP_RESOURCE_TYPE
                if link.to_id not in mapped_containment_targets
                if (link.from_id, link.link_type, link.to_id) not in mapped_keys
            )
            return ResourceQueryResult(
                resources=tuple(resources),
                links=tuple(links),
                relationship_drops=tuple(relationship_drops),
            )

        return _fetch

    def _select_resource_rows(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        resource_type: str,
    ) -> tuple[Mapping[str, Any], ...]:
        expected = self._resource_types.get(resource_type).azure_arm_type
        selected: list[Mapping[str, Any]] = []
        for row in rows:
            try:
                provider_type = arm_provider_type(str(row["id"]), row.get("type"))
            except ArmIdentityError as exc:
                raise ArmInventoryError("ARM row has conflicting provider type") from exc
            if expected is None or provider_type.casefold() != expected.casefold():
                raise ArmInventoryError("ARM row does not match the requested provider type")
            resolved = resolve_azure_resource_type(
                self._resource_types, arm_type=provider_type, kind=row.get("kind")
            )
            if resolved is None:
                raise ArmInventoryError("ARM row has an unresolved resource kind")
            if resolved == resource_type:
                selected.append(row)
        return tuple(selected)

    def build_child_overlay_query_fn(self, primary_query: ResourceQueryFn) -> ResourceQueryFn:
        """Overlay ARM-only child collections onto a primary inventory query."""

        arm_query = self.build_query_fn()

        async def _fetch(
            resource_type: str,
        ) -> ResourceQueryResult | tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
            if resource_type == _VM_SCALE_SET_RESOURCE_TYPE:
                primary = _as_query_result(await primary_query(resource_type))
                children = await self._fetch_vm_scale_set_children(
                    allowed_scale_set_ids=frozenset(
                        resource.provider_ref.casefold()
                        for resource in primary.resources
                        if resource.type == _VM_SCALE_SET_RESOURCE_TYPE
                        and resource.provider_ref is not None
                    )
                )
                return ResourceQueryResult(
                    resources=(*primary.resources, *children.resources),
                    links=(*primary.links, *children.links),
                    relationship_drops=(
                        *primary.relationship_drops,
                        *children.relationship_drops,
                    ),
                )
            if resource_type == _VM_RUN_COMMAND_RESOURCE_TYPE:
                primary = _as_query_result(await primary_query(resource_type))
                return await self._hydrate_vm_run_command_states(primary)
            if resource_type in {
                _AKS_AGENT_POOL_RESOURCE_TYPE,
                MODEL_DEPLOYMENT_RESOURCE_TYPE,
                _PRIVATE_DNS_ZONE_GROUP_RESOURCE_TYPE,
            }:
                return await arm_query(resource_type)
            return await primary_query(resource_type)

        return _fetch

    async def _fetch_vm_scale_set_children(
        self,
        *,
        allowed_scale_set_ids: frozenset[str],
    ) -> ResourceQueryResult:
        """Collect VMSS VM and NIC children under one bounded ARM compute observation."""

        token = await self._identity.get_token(self._config.audience)
        headers = {"Authorization": f"Bearer {token.token}", "Accept": "application/json"}
        typed_rows: list[tuple[Mapping[str, Any], str, str]] = []
        collection_count = 0
        for subscription in self._config.subscription_scopes:
            scale_sets = await self._fetch_pages(
                self._initial_url(
                    subscription=subscription,
                    resource_type=_VM_SCALE_SET_RESOURCE_TYPE,
                    arm_type=_VM_SCALE_SET_ARM_TYPE,
                ),
                headers=headers,
                resource_type=_VM_SCALE_SET_RESOURCE_TYPE,
            )
            for scale_set in scale_sets:
                scale_set_id = str(scale_set["id"])
                if scale_set_id.casefold() not in allowed_scale_set_ids:
                    continue
                collection_count += 1
                self._validate_child_collection_count(collection_count)
                virtual_machines = await self._fetch_pages(
                    self._child_url(scale_set_id, "virtualMachines", expand="instanceView"),
                    headers=headers,
                    resource_type=_VM_SCALE_SET_VM_RESOURCE_TYPE,
                )
                for virtual_machine in virtual_machines:
                    _validate_child_identity(
                        str(virtual_machine["id"]),
                        parent_id=scale_set_id,
                        collection="virtualMachines",
                    )
                    virtual_machine = _project_vmss_instance_state(virtual_machine)
                    virtual_machine_id = str(virtual_machine["id"])
                    typed_rows.append(
                        (virtual_machine, _VM_SCALE_SET_VM_RESOURCE_TYPE, scale_set_id)
                    )
                    collection_count += 1
                    self._validate_child_collection_count(collection_count)
                    network_interfaces = await self._fetch_pages(
                        self._child_url(virtual_machine_id, "networkInterfaces"),
                        headers=headers,
                        resource_type=_VM_SCALE_SET_NIC_RESOURCE_TYPE,
                    )
                    for network_interface in network_interfaces:
                        _validate_child_identity(
                            str(network_interface["id"]),
                            parent_id=virtual_machine_id,
                            collection="networkInterfaces",
                        )
                    typed_rows.extend(
                        (network_interface, _VM_SCALE_SET_NIC_RESOURCE_TYPE, virtual_machine_id)
                        for network_interface in network_interfaces
                    )

        mapped = tuple(
            (
                row,
                _map_arm_row(
                    row,
                    resource_type=resource_type,
                    max_props_bytes=self._config.max_props_bytes,
                    parent_provider_id=parent_provider_id,
                ),
            )
            for row, resource_type, parent_provider_id in typed_rows
        )
        resolved_neutral_types = {
            record.provider_ref.casefold(): record.type
            for _row, record in mapped
            if record.provider_ref is not None
        }
        links: list[LinkRecord] = []
        drops: list[RelationshipDrop] = []
        for row, resource in mapped:
            projected = project_provider_relationships(
                row,
                owner=resource,
                arm_to_neutral=self._arm_to_neutral,
                catalog=self._relationship_mappings,
                arm_id_to_type=arm_id_to_type,
                to_neutral_id=to_neutral_id,
                resolved_neutral_types=resolved_neutral_types,
                source_identity=_ARM_COMPUTE_SOURCE_IDENTITY,
                observed_schema_digest=_ARM_COMPUTE_SOURCE_SCHEMA_DIGEST,
            )
            links.extend(projected.links)
            drops.extend(projected.dropped)
        return ResourceQueryResult(
            resources=tuple(record for _row, record in mapped),
            links=tuple(links),
            relationship_drops=tuple(drops),
        )

    async def _hydrate_vm_run_command_states(
        self,
        primary: ResourceQueryResult,
    ) -> ResourceQueryResult:
        """Retain only exact execution state from each Run Command instance view."""

        commands = tuple(
            resource
            for resource in primary.resources
            if resource.type == _VM_RUN_COMMAND_RESOURCE_TYPE
        )
        self._validate_child_collection_count(len(commands))
        if not commands:
            return primary
        token = await self._identity.get_token(self._config.audience)
        headers = {"Authorization": f"Bearer {token.token}", "Accept": "application/json"}
        hydrated: dict[str, ResourceRecord] = {}
        for command in commands:
            provider_ref = command.provider_ref
            if provider_ref is None:
                raise ArmInventoryError("ARM VM Run Command has no provider identity")
            row = await self._fetch_exact(
                provider_ref,
                headers=headers,
                resource_type=_VM_RUN_COMMAND_RESOURCE_TYPE,
                expand="instanceView",
            )
            if str(row["id"]).casefold() != provider_ref.casefold():
                raise ArmInventoryError("ARM VM Run Command response changed resource identity")
            try:
                provider_type = arm_provider_type(str(row["id"]), row.get("type"))
            except ArmIdentityError as exc:
                raise ArmInventoryError(
                    "ARM VM Run Command response has invalid resource identity"
                ) from exc
            if provider_type.casefold() != _VM_RUN_COMMAND_ARM_TYPE.casefold():
                raise ArmInventoryError("ARM VM Run Command response changed resource type")
            hydrated[command.resource_id] = _with_vm_run_command_state(command, row)
        return ResourceQueryResult(
            resources=tuple(
                hydrated.get(resource.resource_id, resource) for resource in primary.resources
            ),
            links=primary.links,
            relationship_drops=primary.relationship_drops,
        )

    def _child_url(self, parent_id: str, collection: str, *, expand: str | None = None) -> str:
        encoded_parent_id = quote(parent_id, safe="/")
        url = (
            f"{self._config.arm_endpoint.rstrip('/')}{encoded_parent_id}/{collection}"
            f"?api-version={self._config.compute_api_version}"
        )
        return f"{url}&$expand={quote(expand, safe='')}" if expand is not None else url

    def _validate_child_collection_count(self, count: int) -> None:
        if count > self._config.max_child_collections:
            raise ArmInventoryError(
                f"ARM child collection cap ({self._config.max_child_collections}) exceeded"
            )

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

    async def _fetch_model_deployments(
        self,
        *,
        subscription: str,
        headers: Mapping[str, str],
    ) -> tuple[Mapping[str, Any], ...]:
        """List model deployments through each bounded Cognitive Services account."""

        accounts = await self._fetch_pages(
            self._initial_url(
                subscription=subscription,
                resource_type="llm-endpoint",
                arm_type=_COGNITIVE_ACCOUNT_ARM_TYPE,
            ),
            headers=headers,
            resource_type="llm-endpoint",
        )
        if len(accounts) > self._config.max_child_collections:
            raise ArmInventoryError(
                "ARM Cognitive Services child collection cap "
                f"({self._config.max_child_collections}) exceeded"
            )

        rows: list[Mapping[str, Any]] = []
        for account in accounts:
            account_id = str(account["id"])
            encoded_account_id = quote(account_id, safe="/")
            url = (
                f"{self._config.arm_endpoint.rstrip('/')}{encoded_account_id}/deployments"
                f"?api-version={self._config.cognitive_services_api_version}"
            )
            rows.extend(
                await self._fetch_pages(
                    url,
                    headers=headers,
                    resource_type=MODEL_DEPLOYMENT_RESOURCE_TYPE,
                )
            )
        return tuple(rows)

    async def _fetch_aks_agent_pools(
        self,
        *,
        subscription: str,
        headers: Mapping[str, str],
    ) -> tuple[Mapping[str, Any], ...]:
        """List AgentPools through each bounded AKS cluster child collection."""

        clusters = await self._fetch_pages(
            self._initial_url(
                subscription=subscription,
                resource_type=_AKS_CLUSTER_RESOURCE_TYPE,
                arm_type=_AKS_CLUSTER_ARM_TYPE,
            ),
            headers=headers,
            resource_type=_AKS_CLUSTER_RESOURCE_TYPE,
        )
        if len(clusters) > self._config.max_child_collections:
            raise ArmInventoryError(
                f"ARM AKS child collection cap ({self._config.max_child_collections}) exceeded"
            )

        rows: list[Mapping[str, Any]] = []
        for cluster in clusters:
            parent_id = str(cluster["id"])
            encoded_parent_id = quote(parent_id, safe="/")
            url = (
                f"{self._config.arm_endpoint.rstrip('/')}{encoded_parent_id}"
                "/agentPools"
                f"?api-version={self._config.container_service_api_version}"
            )
            rows.extend(
                await self._fetch_pages(
                    url,
                    headers=headers,
                    resource_type=_AKS_AGENT_POOL_RESOURCE_TYPE,
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
        seen: set[str] = set()
        total_bytes = 0
        for page in range(self._config.max_pages):
            self._validate_next_link(current)
            if current in seen:
                raise ArmInventoryError("ARM pagination continuation did not advance")
            seen.add(current)
            payload, response_bytes = await self._read_json(
                current, headers=headers, resource_type=resource_type
            )
            total_bytes += response_bytes
            if total_bytes > self._config.max_total_response_bytes:
                raise ArmInventoryError("ARM collection exceeded its total byte limit")
            rows = payload.get("value")
            if not isinstance(rows, list):
                raise ArmInventoryError(
                    f"ARM payload missing value array for {resource_type!r} (page {page})"
                )
            if len(collected) + len(rows) > self._config.max_records:
                raise ArmInventoryError("ARM collection exceeded its record limit")
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

    async def _fetch_exact(
        self,
        resource_id: str,
        *,
        headers: Mapping[str, str],
        resource_type: str,
        expand: str | None = None,
    ) -> Mapping[str, Any]:
        encoded_id = quote(resource_id, safe="/")
        url = (
            f"{self._config.arm_endpoint.rstrip('/')}{encoded_id}"
            f"?api-version={self._config.compute_api_version}"
        )
        if expand is not None:
            url += f"&$expand={quote(expand, safe='')}"
        payload, _response_bytes = await self._read_json(
            url, headers=headers, resource_type=resource_type
        )
        if not isinstance(payload, Mapping) or not isinstance(payload.get("id"), str):
            raise ArmInventoryError(f"ARM exact response is malformed for {resource_type!r}")
        return payload

    async def _read_json(
        self, url: str, *, headers: Mapping[str, str], resource_type: str
    ) -> tuple[Mapping[str, Any], int]:
        return await fetch_arm_json(
            client=self._http,
            url=url,
            headers=headers,
            resource_type=resource_type,
            timeout_seconds=self._config.timeout_seconds,
            max_response_bytes=self._config.max_response_bytes,
            max_attempts=self._config.max_attempts,
        )

    def _validate_next_link(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.lower() != self._endpoint_host:
            raise ArmInventoryError("ARM nextLink changed scheme or host")


def _map_arm_row(
    row: Mapping[str, Any],
    *,
    resource_type: str,
    max_props_bytes: int,
    parent_provider_id: str | None = None,
) -> ResourceRecord:
    arm_id = str(row["id"])
    try:
        scope = arm_scope_properties(arm_id, row)
    except ArmScopeError as exc:
        raise ArmInventoryError(
            f"ARM row for {resource_type!r} has conflicting provider scope"
        ) from exc
    raw_props = {
        key: row[key]
        for key in ("name", "location", "sku", "tags", "properties", "managedBy")
        if row.get(key) is not None
    }
    if resource_type == MODEL_DEPLOYMENT_RESOURCE_TYPE:
        raw_props.update(model_deployment_summary(row))
    props = truncate_props(raw_props, max_bytes=max_props_bytes)
    try:
        provider_type = arm_provider_type(arm_id, row.get("type"))
    except ArmIdentityError as exc:
        raise ArmInventoryError(
            f"ARM row for {resource_type!r} has conflicting provider type"
        ) from exc
    props["providerType"] = provider_type
    props.update(scope)
    # Lifted after truncation so the containment anchor survives a large
    # vendor payload; `Resource.parent_id` is what scoped questions read.
    parent_id: str | None
    if parent_provider_id is not None:
        parent_id = to_neutral_id(parent_provider_id)
    elif resource_type in {
        _AKS_AGENT_POOL_RESOURCE_TYPE,
        MODEL_DEPLOYMENT_RESOURCE_TYPE,
        _PRIVATE_DNS_ZONE_GROUP_RESOURCE_TYPE,
    }:
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


def _as_query_result(
    value: ResourceQueryResult | tuple[Sequence[ResourceRecord], Sequence[LinkRecord]],
) -> ResourceQueryResult:
    if isinstance(value, ResourceQueryResult):
        return value
    resources, links = value
    return ResourceQueryResult(resources=tuple(resources), links=tuple(links))


def _relationship_source(resource_type: str) -> tuple[str, str]:
    if resource_type == MODEL_DEPLOYMENT_RESOURCE_TYPE:
        return (
            _ARM_COGNITIVE_SERVICES_SOURCE_IDENTITY,
            _ARM_COGNITIVE_SERVICES_SOURCE_SCHEMA_DIGEST,
        )
    if resource_type == _AKS_AGENT_POOL_RESOURCE_TYPE:
        return (
            _ARM_CONTAINER_SERVICE_SOURCE_IDENTITY,
            _ARM_CONTAINER_SERVICE_SOURCE_SCHEMA_DIGEST,
        )
    return _ARM_NETWORK_SOURCE_IDENTITY, _ARM_NETWORK_SOURCE_SCHEMA_DIGEST


__all__ = [
    "ArmInventoryError",
    "AzureArmInventoryFactory",
    "AzureArmInventoryFactoryConfig",
]
