"""Normalize Azure Resource Graph rows into CSP-neutral graph records."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from fdai.delivery.azure.arg_relationships import project_provider_relationships
from fdai.rule_catalog.schema.provider_relationship_mapping import (
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
_RELATIONSHIP_MAPPING_ROOT: Final[Path] = Path(
    "rule-catalog/vocabulary/provider-relationship-mappings"
)
_LOGGER = logging.getLogger(__name__)


def to_neutral_id(arm_id: str) -> str:
    """Fold an ARM path into a stable CSP-neutral resource identifier."""
    trimmed = arm_id.strip()
    scope_prefix = _scope_prefix(trimmed)
    marker = "/resourceGroups/"
    idx = trimmed.lower().find(marker.lower())
    if idx == -1:
        parts = [part for part in trimmed.lower().strip("/").split("/") if part]
        suffix = "/".join(parts[2:] if parts[:1] == ["subscriptions"] else parts)
        return f"{scope_prefix}/{suffix}"
    return f"{scope_prefix}/resource-group{trimmed[idx + len(marker) - len('/') :].lower()}"


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
    for value in (
        row.get("powerState"),
        row.get("state"),
        nested.get("powerState"),
        instance_view_properties.get("powerState"),
        nested.get("state"),
        nested.get("status"),
        nested.get("userVisibleState"),
        nested.get("resourceState"),
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
    seen: set[str] = set()
    for raw_subnet in raw_subnets:
        if not isinstance(raw_subnet, Mapping):
            continue
        provider_ref = raw_subnet.get("id")
        if not isinstance(provider_ref, str):
            continue
        provider_type = arm_id_to_type(provider_ref)
        if provider_type is None or provider_type.casefold() != _SUBNET_ARM_TYPE.casefold():
            continue
        resource_id = to_neutral_id(provider_ref)
        if resource_id in seen:
            continue
        seen.add(resource_id)
        name = raw_subnet.get("name")
        props: dict[str, Any] = {
            "name": name if isinstance(name, str) and name else provider_ref.rsplit("/", 1)[-1],
        }
        resource_group = vnet.props.get("resourceGroup")
        if isinstance(resource_group, str) and resource_group:
            props["resourceGroup"] = resource_group
        records.append(
            ResourceRecord(
                resource_id=resource_id,
                type=_SUBNET_TYPE,
                props=props,
                provider_ref=provider_ref,
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
        _LOGGER.warning(
            "azure_arm_reverse_map_ambiguous_types",
            extra={"count": len(ambiguous), "arm_types": ambiguous},
        )
    return {
        arm_type: type_ids[0] for arm_type, type_ids in by_arm_type.items() if len(type_ids) == 1
    }


def arm_id_to_type(arm_id: str) -> str | None:
    """Extract the ``Microsoft.X/Y[/Z]`` type suffix from an ARM id."""
    marker = "/providers/"
    idx = arm_id.lower().find(marker)
    if idx == -1:
        return None
    parts = arm_id[idx + len(marker) :].split("/")
    if len(parts) < 2:
        return None
    provider = parts[0]
    type_segments = [parts[index] for index in range(1, len(parts), 2)]
    if not type_segments:
        return None
    return f"{provider}/{'/'.join(type_segments)}"


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
    )
    return tuple(link for link in result.links if link.link_type == link_type)
