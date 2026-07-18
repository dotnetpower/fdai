"""Normalize Azure Resource Graph rows into CSP-neutral graph records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.shared.providers.inventory import LinkRecord, ResourceRecord

_RESOURCE_GROUP_TYPE: Final[str] = "resource-group"


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


_ATTACHED_TO_PROPERTY_KEYS: Final[tuple[str, ...]] = (
    "subnet",
    "networkSecurityGroup",
    "publicIPAddress",
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
    for key in _ATTACHED_TO_PROPERTY_KEYS:
        nested = properties.get(key)
        if not isinstance(nested, Mapping):
            continue
        ref_id = nested.get("id")
        if not isinstance(ref_id, str) or not ref_id:
            continue
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
