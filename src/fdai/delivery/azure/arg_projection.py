"""Normalize Azure Resource Graph rows into CSP-neutral graph records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Final

from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.shared.providers.inventory import LinkRecord, ResourceRecord

_RESOURCE_GROUP_TYPE: Final[str] = "resource-group"
_VNET_TYPE: Final[str] = "network.vnet"
_SUBNET_TYPE: Final[str] = "network.subnet"
_SUBNET_ARM_TYPE: Final[str] = "Microsoft.Network/virtualNetworks/subnets"


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


_ATTACHED_TO_PROPERTY_KEYS: Final[tuple[str, ...]] = (
    "subnet",
    "networkSecurityGroup",
    "publicIPAddress",
)
_ATTACHED_TO_COLLECTION_KEYS: Final[tuple[str, ...]] = (
    "frontendIPConfigurations",
    "ipConfigurations",
)


def build_arm_to_neutral_map(registry: ResourceTypeRegistry) -> dict[str, str]:
    """Build a case-insensitive ARM type to neutral type reverse map."""
    return {
        entry.azure_arm_type.lower(): entry.id
        for entry in registry
        if entry.azure_arm_type is not None
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
    """Project whitelisted hard attachment references from one ARG row."""
    properties = row.get("properties")
    if not isinstance(properties, Mapping):
        return ()

    seen: set[tuple[str, str, str]] = set()
    links: list[LinkRecord] = []
    for ref_id in _attachment_ids(properties):
        arm_type = arm_id_to_type(ref_id)
        if arm_type is None:
            continue
        to_type = arm_to_neutral.get(arm_type.lower())
        if to_type is None:
            continue
        target_neutral = to_neutral_id(ref_id)
        dedup_key = (child.resource_id, "attached_to", target_neutral)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        links.append(
            LinkRecord(
                from_id=child.resource_id,
                from_type=child.type,
                link_type="attached_to",
                to_id=target_neutral,
                to_type=to_type,
            )
        )
    return tuple(links)


def _attachment_property_maps(properties: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    yield properties
    for collection_key in _ATTACHED_TO_COLLECTION_KEYS:
        collection = properties.get(collection_key)
        if not isinstance(collection, Sequence) or isinstance(collection, (str, bytes)):
            continue
        for entry in collection:
            if not isinstance(entry, Mapping):
                continue
            nested = entry.get("properties")
            if isinstance(nested, Mapping):
                yield nested


def _attachment_ids(properties: Mapping[str, Any]) -> Iterable[str]:
    for attachment_properties in _attachment_property_maps(properties):
        for key in _ATTACHED_TO_PROPERTY_KEYS:
            nested = attachment_properties.get(key)
            if isinstance(nested, Mapping) and isinstance(nested.get("id"), str):
                yield nested["id"]

    network_profile = properties.get("networkProfile")
    if isinstance(network_profile, Mapping):
        network_interfaces = network_profile.get("networkInterfaces")
        if isinstance(network_interfaces, Sequence) and not isinstance(
            network_interfaces, (str, bytes)
        ):
            for network_interface in network_interfaces:
                if isinstance(network_interface, Mapping) and isinstance(
                    network_interface.get("id"), str
                ):
                    yield network_interface["id"]

    storage_profile = properties.get("storageProfile")
    if not isinstance(storage_profile, Mapping):
        return
    os_disk = storage_profile.get("osDisk")
    if isinstance(os_disk, Mapping):
        managed_disk = os_disk.get("managedDisk")
        if isinstance(managed_disk, Mapping) and isinstance(managed_disk.get("id"), str):
            yield managed_disk["id"]
    data_disks = storage_profile.get("dataDisks")
    if isinstance(data_disks, Sequence) and not isinstance(data_disks, (str, bytes)):
        for data_disk in data_disks:
            if not isinstance(data_disk, Mapping):
                continue
            managed_disk = data_disk.get("managedDisk")
            if isinstance(managed_disk, Mapping) and isinstance(managed_disk.get("id"), str):
                yield managed_disk["id"]


_DEPENDS_ON_ID_PROPERTY_KEYS: Final[tuple[str, ...]] = ("storageAccount",)
_DEPENDS_ON_ARM_ID_STRING_KEYS: Final[tuple[str, ...]] = ("workspaceResourceId",)


def extract_depends_on_links_from_row(
    row: Mapping[str, Any],
    *,
    child: ResourceRecord,
    arm_to_neutral: Mapping[str, str],
    acr_resolver: Callable[[str], str | None],
) -> tuple[LinkRecord, ...]:
    """Project whitelisted soft dependency references from one ARG row."""
    properties = row.get("properties")
    if not isinstance(properties, Mapping):
        return ()

    seen: set[tuple[str, str, str]] = set()
    links: list[LinkRecord] = []

    def try_emit(ref_id: str) -> None:
        arm_type = arm_id_to_type(ref_id)
        if arm_type is None:
            return
        to_type = arm_to_neutral.get(arm_type.lower())
        if to_type is None:
            return
        target_neutral = to_neutral_id(ref_id)
        dedup_key = (child.resource_id, "depends_on", target_neutral)
        if dedup_key in seen:
            return
        seen.add(dedup_key)
        links.append(
            LinkRecord(
                from_id=child.resource_id,
                from_type=child.type,
                link_type="depends_on",
                to_id=target_neutral,
                to_type=to_type,
            )
        )

    for key in _DEPENDS_ON_ID_PROPERTY_KEYS:
        nested = properties.get(key)
        if not isinstance(nested, Mapping):
            continue
        ref_id = nested.get("id")
        if isinstance(ref_id, str) and ref_id:
            try_emit(ref_id)

    for key in _DEPENDS_ON_ARM_ID_STRING_KEYS:
        ref_id = properties.get(key)
        if isinstance(ref_id, str) and ref_id:
            try_emit(ref_id)

    login_server = properties.get("acrLoginServer")
    if isinstance(login_server, str) and login_server:
        resolved = acr_resolver(login_server)
        if resolved is not None:
            try_emit(resolved)

    return tuple(links)
