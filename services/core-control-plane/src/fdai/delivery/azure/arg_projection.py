"""Normalize Azure Resource Graph rows into CSP-neutral graph records."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from fdai.delivery.azure.arg_relationships import (
    project_provider_relationships,
    provider_parent_id,
    provider_root_id,
)
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    EndpointOrientation,
    ProviderRelationshipMappingCatalog,
    load_provider_relationship_mapping_catalog,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
)
from fdai.shared.providers.inventory import LinkRecord, ResourceRecord

_RESOURCE_GROUP_TYPE: Final[str] = "resource-group"
_VNET_TYPE: Final[str] = "network.vnet"
_SUBNET_TYPE: Final[str] = "network.subnet"
_SUBNET_ARM_TYPE: Final[str] = "Microsoft.Network/virtualNetworks/subnets"
_MAX_ARM_SUBSCRIPTION_CHARS: Final[int] = 128
_MAX_ARM_RESOURCE_GROUP_CHARS: Final[int] = 90
_MAX_ARM_PROVIDER_TYPE_CHARS: Final[int] = 512
_RELATIONSHIP_MAPPING_ROOT: Final[Path] = Path(
    "rule-catalog/vocabulary/provider-relationship-mappings"
)
_LOGGER = logging.getLogger(__name__)


class ArmIdentityError(ValueError):
    """An Azure row contradicts its provider identity."""


class ArmScopeError(ArmIdentityError):
    """An Azure row contradicts the scope encoded in its provider identity."""


def to_neutral_id(arm_id: str) -> str:
    """Fold an ARM path into a stable CSP-neutral resource identifier."""
    trimmed = arm_id.strip()
    scope_prefix = _scope_prefix(trimmed)
    marker = "/resourceGroups/"
    idx = trimmed.lower().find(marker.lower())
    if idx == -1:
        parts = [part for part in trimmed.lower().strip("/").split("/") if part]
        suffix = "/".join(parts[2:] if parts[:1] == ["subscriptions"] else parts)
        # A bare subscription path folds onto the scope anchor itself; a
        # trailing slash would make the anchor unreferenceable by a parent.
        return f"{scope_prefix}/{suffix}" if suffix else scope_prefix
    return f"{scope_prefix}/resource-group{trimmed[idx + len(marker) - len('/') :].lower()}"


def parent_neutral_id(arm_id: str) -> str | None:
    """Return the containment parent of ``arm_id`` in CSP-neutral form.

    A resource inside a resource group reports that group; a resource group
    reports its subscription scope anchor; a subscription has no parent.
    """
    trimmed = arm_id.strip()
    if not trimmed:
        return None
    marker = "/resourceGroups/"
    idx = trimmed.lower().find(marker.lower())
    if idx == -1:
        return None
    after_marker = idx + len(marker)
    next_slash = trimmed.find("/", after_marker)
    if next_slash == -1:
        # The resource group itself is contained by its subscription scope.
        return _scope_prefix(trimmed)
    return to_neutral_id(trimmed[:next_slash])


def reviewed_containment_parent(
    arm_id: str,
    *,
    arm_type: str,
    arm_to_neutral: Mapping[str, str],
    catalog: ProviderRelationshipMappingCatalog,
) -> tuple[str, str] | None:
    """Resolve only reviewed provider-parent containment before RG fallback."""

    mapping_paths = {
        mapping.source_property_path
        for mapping in catalog.mappings
        if mapping.provider == "azure"
        and mapping.source_property_path in {"id.providerParent", "id.providerRoot"}
        and mapping.link_type == "contains"
        and mapping.endpoint_orientation is EndpointOrientation.REFERENCED_TO_OWNER
        and arm_type.casefold() in mapping.source_provider_types
    }
    if len(mapping_paths) > 1:
        raise ArmScopeError("ARM type has ambiguous containment mappings")
    if mapping_paths:
        mapping_path = next(iter(mapping_paths))
        parent_provider_id = (
            provider_root_id(arm_id)
            if mapping_path == "id.providerRoot"
            else provider_parent_id(arm_id)
        )
        parent_provider_type = (
            arm_id_to_type(parent_provider_id) if parent_provider_id is not None else None
        )
        parent_type = (
            arm_to_neutral.get(parent_provider_type.casefold())
            if parent_provider_type is not None
            else None
        )
        if parent_provider_id is None or parent_type is None:
            raise ArmScopeError("ARM provider parent cannot be resolved")
        return to_neutral_id(parent_provider_id), parent_type
    parent_id = parent_neutral_id(arm_id)
    return (parent_id, _RESOURCE_GROUP_TYPE) if parent_id is not None else None


def arm_scope_properties(
    arm_id: str,
    row: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Return exact subscription and resource-group scope embedded in an ARM id.

    Matching provider columns keep their original casing. Missing columns are
    filled from the identity, while contradictory values fail the observation.
    The returned values are bounded FDAI-derived identity fields and may be
    restored after vendor-property truncation.
    """

    parts = arm_id.strip("/").split("/")
    if len(parts) < 2 or parts[0].casefold() != "subscriptions":
        return {}
    if any(not part for part in parts):
        raise ArmScopeError("ARM provider path is malformed")
    subscription = _bounded_scope_segment(
        parts[1],
        "subscription",
        maximum=_MAX_ARM_SUBSCRIPTION_CHARS,
    )
    result = {
        "subscriptionId": _matching_scope_value(
            row,
            key="subscriptionId",
            derived=subscription,
        )
    }
    if len(parts) < 3 or parts[2].casefold() != "resourcegroups":
        if row is not None and row.get("resourceGroup") not in {None, ""}:
            raise ArmScopeError("ARM resourceGroup scope conflicts with the provider id")
        return result
    if len(parts) < 4:
        raise ArmScopeError("ARM resource-group scope is malformed")
    resource_group = _bounded_scope_segment(
        parts[3],
        "resource group",
        maximum=_MAX_ARM_RESOURCE_GROUP_CHARS,
    )
    result["resourceGroup"] = _matching_scope_value(
        row,
        key="resourceGroup",
        derived=resource_group,
    )
    return result


def validated_arm_scope(
    arm_id: str,
    row: Mapping[str, Any],
    error: RuntimeError,
) -> dict[str, str]:
    """Return provider scope or translate validation failure to the caller boundary."""

    try:
        return arm_scope_properties(arm_id, row)
    except ArmScopeError as cause:
        raise error from cause


def add_neutral_resource_scope(properties: dict[str, Any]) -> None:
    """Project provider scope fields to CSP-neutral Resource properties."""

    resource_group = properties.get("resourceGroup")
    if isinstance(resource_group, str) and resource_group.strip():
        properties["resource_group"] = resource_group.strip()
    location = properties.get("location")
    if isinstance(location, str) and location.strip():
        properties["region"] = location.strip()


def _bounded_scope_segment(value: str, label: str, *, maximum: int) -> str:
    candidate = value.strip()
    if not candidate or len(candidate) > maximum:
        raise ArmScopeError(f"ARM {label} scope is malformed")
    return candidate


def _matching_scope_value(
    row: Mapping[str, Any] | None,
    *,
    key: str,
    derived: str,
) -> str:
    supplied = row.get(key) if row is not None else None
    if supplied is None or supplied == "":
        return derived
    if not isinstance(supplied, str):
        raise ArmScopeError(f"ARM {key} scope is malformed")
    supplied = _bounded_scope_segment(
        supplied,
        key,
        maximum=(
            _MAX_ARM_SUBSCRIPTION_CHARS
            if key == "subscriptionId"
            else _MAX_ARM_RESOURCE_GROUP_CHARS
        ),
    )
    if supplied.casefold() != derived.casefold():
        raise ArmScopeError(f"ARM {key} scope conflicts with the provider id")
    return supplied


def _scope_prefix(arm_id: str) -> str:
    parts = [part for part in arm_id.strip("/").split("/") if part]
    subscription = (
        parts[1].lower() if len(parts) > 1 and parts[0].lower() == "subscriptions" else "unknown"
    )
    digest = hashlib.sha256(subscription.encode("utf-8")).hexdigest()[:16]
    return f"scope-{digest}"


def truncate_props(props: Mapping[str, Any], *, max_bytes: int) -> dict[str, Any]:
    """Cap serialized properties so untrusted vendor data stays inert."""
    encoded = json.dumps(props, default=str, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= max_bytes:
        return dict(json.loads(encoded))

    trimmed = dict(props)
    for key in ("properties", "tags"):
        trimmed.pop(key, None)
        rerun = json.dumps(trimmed, default=str, ensure_ascii=False, separators=(",", ":"))
        if len(rerun.encode("utf-8")) <= max_bytes:
            result = dict(json.loads(rerun))
            result["_truncated"] = True
            return result

    return {"_truncated": True, "resource_id_hint": props.get("name")}


def resource_operational_status(row: Mapping[str, Any]) -> str | None:
    """Return an observed service or power state without inferring health."""

    properties = row.get("properties")
    nested = properties if isinstance(properties, Mapping) else {}
    extended = nested.get("extended")
    extended_properties = extended if isinstance(extended, Mapping) else {}
    instance_view = extended_properties.get("instanceView")
    instance_view_properties = instance_view if isinstance(instance_view, Mapping) else {}
    direct_instance_view = nested.get("instanceView")
    direct_instance_view_properties = (
        direct_instance_view if isinstance(direct_instance_view, Mapping) else {}
    )
    for value in (
        row.get("powerState"),
        row.get("state"),
        nested.get("powerState"),
        instance_view_properties.get("powerState"),
        nested.get("state"),
        nested.get("status"),
        nested.get("runningStatus"),
        nested.get("operationalState"),
        nested.get("dnsResolverState"),
        nested.get("diskState"),
        nested.get("snapshotAccessState"),
        nested.get("userVisibleState"),
        nested.get("resourceState"),
        nested.get("virtualNetworkLinkState"),
        direct_instance_view_properties.get("powerState"),
        direct_instance_view_properties.get("executionState"),
        nested.get("registrationStatus"),
    ):
        state = _state_text(value)
        if state is not None:
            return state
    return None


def _state_text(value: object) -> str | None:
    candidate = value.get("code") if isinstance(value, Mapping) else value
    return candidate.strip() if isinstance(candidate, str) and candidate.strip() else None


def extract_rg_contains_links(
    resources: Sequence[ResourceRecord],
) -> tuple[LinkRecord, ...]:
    """Emit one ``contains(resource-group, resource)`` edge per RG resource."""
    rg_marker = "/resourceGroups/"
    seen: set[tuple[str, str, str]] = set()
    links: list[LinkRecord] = []
    for record in resources:
        arm_id = record.provider_ref
        if not arm_id:
            continue
        marker_idx = arm_id.lower().find(rg_marker.lower())
        if marker_idx == -1:
            continue
        after_marker = marker_idx + len(rg_marker)
        next_slash = arm_id.find("/", after_marker)
        if next_slash == -1:
            continue
        rg_neutral_id = to_neutral_id(arm_id[:next_slash])
        key = (rg_neutral_id, "contains", record.resource_id)
        if key in seen:
            continue
        seen.add(key)
        links.append(
            LinkRecord(
                from_id=rg_neutral_id,
                from_type=_RESOURCE_GROUP_TYPE,
                link_type="contains",
                to_id=record.resource_id,
                to_type=record.type,
            )
        )
    return tuple(links)


def materialize_nested_subnets(
    vnet: ResourceRecord,
) -> tuple[tuple[ResourceRecord, ...], tuple[LinkRecord, ...]]:
    """Promote observed VNet subnet payloads into inventory graph records."""
    if vnet.type != _VNET_TYPE:
        return (), ()
    properties = vnet.props.get("properties")
    if not isinstance(properties, Mapping):
        return (), ()
    raw_subnets = properties.get("subnets")
    if not isinstance(raw_subnets, Sequence) or isinstance(raw_subnets, (str, bytes)):
        return (), ()

    records: list[ResourceRecord] = []
    links: list[LinkRecord] = []
    seen: dict[str, Mapping[str, Any]] = {}
    for raw_subnet in raw_subnets:
        if not isinstance(raw_subnet, Mapping):
            raise ArmScopeError("nested subnet observation MUST be an object")
        provider_ref = raw_subnet.get("id")
        if not isinstance(provider_ref, str):
            raise ArmScopeError("nested subnet observation MUST have a provider id")
        provider_type = arm_id_to_type(provider_ref)
        if provider_type is None or provider_type.casefold() != _SUBNET_ARM_TYPE.casefold():
            raise ArmScopeError("nested subnet observation has an invalid provider type")
        parent_provider_ref = provider_parent_id(provider_ref)
        if (
            vnet.provider_ref is None
            or parent_provider_ref is None
            or parent_provider_ref.casefold() != vnet.provider_ref.casefold()
        ):
            raise ArmScopeError("subnet provider parent conflicts with the observed VNet")
        resource_id = to_neutral_id(provider_ref)
        if resource_id in seen:
            if seen[resource_id] != raw_subnet:
                raise ArmScopeError("nested subnet observation has conflicting duplicates")
            continue
        seen[resource_id] = raw_subnet
        name = raw_subnet.get("name")
        props: dict[str, Any] = {
            "name": name if isinstance(name, str) and name else provider_ref.rsplit("/", 1)[-1],
        }
        nested_properties = raw_subnet.get("properties")
        if isinstance(nested_properties, Mapping):
            props["properties"] = dict(nested_properties)
        props.update(arm_scope_properties(provider_ref, raw_subnet))
        props["providerType"] = provider_type
        props["parent_id"] = vnet.resource_id
        records.append(
            ResourceRecord(
                resource_id=resource_id,
                type=_SUBNET_TYPE,
                props=props,
                provider_ref=provider_ref,
                last_seen=vnet.last_seen,
            )
        )
        links.append(
            LinkRecord(
                from_id=vnet.resource_id,
                from_type=_VNET_TYPE,
                link_type="contains",
                to_id=resource_id,
                to_type=_SUBNET_TYPE,
            )
        )
    return tuple(records), tuple(links)


def build_arm_to_neutral_map(registry: ResourceTypeRegistry) -> dict[str, str]:
    """Build an unambiguous case-insensitive ARM type reverse map."""
    by_arm_type: dict[str, list[str]] = {}
    for entry in registry:
        if entry.azure_arm_type is not None:
            by_arm_type.setdefault(entry.azure_arm_type.lower(), []).append(entry.id)
    ambiguous = sorted(arm_type for arm_type, type_ids in by_arm_type.items() if len(type_ids) > 1)
    if ambiguous:
        _LOGGER.debug(
            "azure_arm_reverse_map_ambiguous_types",
            extra={"count": len(ambiguous), "arm_types": ambiguous},
        )
    return {
        arm_type: type_ids[0] for arm_type, type_ids in by_arm_type.items() if len(type_ids) == 1
    }


def arm_id_to_type(arm_id: str) -> str | None:
    """Extract the ``Microsoft.X/Y[/Z]`` type suffix from an ARM id."""
    parts = arm_id.strip("/").split("/")
    if any(not part for part in parts):
        return None
    if len(parts) == 2 and parts[0].casefold() == "subscriptions":
        return "Microsoft.Resources/subscriptions"
    if (
        len(parts) == 4
        and parts[0].casefold() == "subscriptions"
        and parts[2].casefold() == "resourcegroups"
    ):
        return "Microsoft.Resources/resourceGroups"
    marker = "/providers/"
    idx = arm_id.lower().rfind(marker)
    if idx == -1:
        return None
    parts = arm_id[idx + len(marker) :].split("/")
    if len(parts) < 3 or len(parts) % 2 == 0:
        return None
    provider = parts[0]
    type_segments = [parts[index] for index in range(1, len(parts), 2)]
    if not type_segments:
        return None
    return f"{provider}/{'/'.join(type_segments)}"


def arm_provider_type(arm_id: str, supplied: object = None) -> str:
    """Return a bounded provider type that exactly matches the ARM id."""

    derived = arm_id_to_type(arm_id)
    if (
        derived is None
        or len(derived) > _MAX_ARM_PROVIDER_TYPE_CHARS
        or any(ord(character) < 32 for character in derived)
    ):
        raise ArmIdentityError("ARM provider type is malformed")
    if supplied is None:
        return derived
    if not isinstance(supplied, str):
        raise ArmIdentityError("ARM provider type is malformed")
    candidate = supplied.strip()
    if (
        not candidate
        or len(candidate) > _MAX_ARM_PROVIDER_TYPE_CHARS
        or any(ord(character) < 32 for character in candidate)
    ):
        raise ArmIdentityError("ARM provider type is malformed")
    if candidate.casefold() != derived.casefold():
        raise ArmIdentityError("ARM provider type conflicts with the provider id")
    return candidate


def extract_attached_to_links_from_row(
    row: Mapping[str, Any],
    *,
    child: ResourceRecord,
    arm_to_neutral: Mapping[str, str],
) -> tuple[LinkRecord, ...]:
    """Project ``attached_to`` through the reviewed relationship catalog."""

    return _mapped_links(
        row,
        child=child,
        arm_to_neutral=arm_to_neutral,
        link_type="attached_to",
    )


def extract_peered_with_links_from_row(
    row: Mapping[str, Any],
    *,
    child: ResourceRecord,
    arm_to_neutral: Mapping[str, str],
) -> tuple[LinkRecord, ...]:
    """Project directed peering observations through the reviewed catalog."""

    return _mapped_links(
        row,
        child=child,
        arm_to_neutral=arm_to_neutral,
        link_type="peered_with",
    )


def extract_routes_to_links_from_row(
    row: Mapping[str, Any],
    *,
    child: ResourceRecord,
    arm_to_neutral: Mapping[str, str],
) -> tuple[LinkRecord, ...]:
    """Project exact-resource routes through the reviewed catalog."""

    return _mapped_links(
        row,
        child=child,
        arm_to_neutral=arm_to_neutral,
        link_type="routes_to",
    )


def extract_depends_on_links_from_row(
    row: Mapping[str, Any],
    *,
    child: ResourceRecord,
    arm_to_neutral: Mapping[str, str],
    acr_resolver: Callable[[str], str | None],
) -> tuple[LinkRecord, ...]:
    """Project soft dependencies through the reviewed relationship catalog."""

    return _mapped_links(
        row,
        child=child,
        arm_to_neutral=arm_to_neutral,
        link_type="depends_on",
        external_reference_resolver=acr_resolver,
    )


def _mapped_links(
    row: Mapping[str, Any],
    *,
    child: ResourceRecord,
    arm_to_neutral: Mapping[str, str],
    link_type: str,
    external_reference_resolver: Callable[[str], str | None] | None = None,
) -> tuple[LinkRecord, ...]:
    catalog = load_provider_relationship_mapping_catalog(_RELATIONSHIP_MAPPING_ROOT)
    result = project_provider_relationships(
        row,
        owner=child,
        arm_to_neutral=arm_to_neutral,
        catalog=catalog,
        arm_id_to_type=arm_id_to_type,
        to_neutral_id=to_neutral_id,
        external_reference_resolver=external_reference_resolver,
        source_identity="azure-resource-graph",
    )
    return tuple(link for link in result.links if link.link_type == link_type)
