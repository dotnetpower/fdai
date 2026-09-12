"""Validate exact image-plan VM selections against subscription SKU metadata.

This prerequisite never selects a replacement or proves quota, capacity, or an effect.
Missing or ambiguous plan/provider evidence blocks rather than granting eligibility.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NoReturn

from genesis_checks import CheckError

_SKU = re.compile(r"Standard_[A-Za-z0-9_]{1,64}")
_LOCATION = re.compile(r"[A-Za-z][A-Za-z0-9]{0,63}")
_ZONE = re.compile(r"[1-9][0-9]?")
_ADDRESSES = frozenset(
    {"azurerm_linux_virtual_machine.builder", "azurerm_linux_virtual_machine.verifier"}
)
PLAN_INVALID = "runner_image_sku_plan_invalid"
EVIDENCE_INVALID = "runner_image_sku_evidence_incomplete"
SKU_RESTRICTED = "runner_image_sku_restricted_review_required"


@dataclass(frozen=True, slots=True)
class PlannedVmSku:
    """One resolved create selection from the caller's verified binary plan."""

    size: str
    region: str
    zone: str | None


def image_vm_selections(projection: bytes, *, region: str) -> tuple[PlannedVmSku, ...]:
    """Require both exact create-only VM selections, with no unknown size/location/zone."""

    if not _LOCATION.fullmatch(region):
        raise CheckError(PLAN_INVALID, 3)
    try:
        plan = load_sku_json(projection, max_bytes=64 * 1024 * 1024)
    except CheckError:
        raise CheckError(PLAN_INVALID, 3) from None
    changes = plan.get("resource_changes")
    if (
        plan.get("format_version") not in ("1.1", "1.2")
        or plan.get("complete") is not True
        or plan.get("errored") is not False
        or plan.get("applyable") is not True
        or plan.get("deferred_changes") not in (None, [])
        or not isinstance(changes, list)
        or not 2 <= len(changes) <= 128
    ):
        raise CheckError(PLAN_INVALID, 3)
    selections: dict[str, PlannedVmSku] = {}
    for entry in changes:
        if not isinstance(entry, dict):
            raise CheckError(PLAN_INVALID, 3)
        address = entry.get("address")
        vm_type = entry.get("type") == "azurerm_linux_virtual_machine"
        if not isinstance(address, str):
            raise CheckError(PLAN_INVALID, 3)
        if not vm_type and address not in _ADDRESSES:
            continue
        if not vm_type or address not in _ADDRESSES or address in selections:
            raise CheckError(PLAN_INVALID, 3)
        change = entry.get("change")
        if not isinstance(change, dict) or change.get("actions") != ["create"]:
            raise CheckError(PLAN_INVALID, 3)
        after = change.get("after")
        unknown = change.get("after_unknown", {})
        if (
            entry.get("mode") != "managed"
            or not isinstance(after, dict)
            or not isinstance(unknown, dict)
            or any(unknown.get(key, False) is not False for key in ("size", "location", "zone"))
        ):
            raise CheckError(PLAN_INVALID, 3)
        size, location, zone = after.get("size"), after.get("location"), after.get("zone")
        if (
            not isinstance(size, str)
            or _SKU.fullmatch(size) is None
            or not isinstance(location, str)
            or location.casefold() != region.casefold()
            or (zone is not None and (not isinstance(zone, str) or _ZONE.fullmatch(zone) is None))
        ):
            raise CheckError(PLAN_INVALID, 3)
        selections[address] = PlannedVmSku(size, region.casefold(), zone)
    if set(selections) != _ADDRESSES:
        raise CheckError(PLAN_INVALID, 3)
    return tuple(selections[address] for address in sorted(selections))


def selection_sizes(value: object) -> tuple[str, str]:
    """Validate the optional, review-bound selection record before displaying or using it."""

    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "build_vm_size",
            "verify_vm_size",
            "policy_digest",
            "sku_evidence_digest",
            "quota_evidence_digest",
            "checked_at",
            "capacity_reserved",
        }
        or value["schema_version"] != "fdai.runner-image-sku-selection.v1"
        or value["capacity_reserved"] is not False
    ):
        raise CheckError(PLAN_INVALID, 3)
    for key in ("policy_digest", "sku_evidence_digest", "quota_evidence_digest"):
        if not isinstance(value[key], str) or re.fullmatch(r"[0-9a-f]{64}", value[key]) is None:
            raise CheckError(PLAN_INVALID, 3)
    for key in ("build_vm_size", "verify_vm_size"):
        if not isinstance(value[key], str) or _SKU.fullmatch(value[key]) is None:
            raise CheckError(PLAN_INVALID, 3)
    stamp = value["checked_at"]
    if not isinstance(stamp, str):
        raise CheckError(PLAN_INVALID, 3)
    try:
        timestamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        raise CheckError(PLAN_INVALID, 3) from None
    if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
        raise CheckError(PLAN_INVALID, 3)
    return value["build_vm_size"], value["verify_vm_size"]


def require_selection_projection(projection: bytes, *, region: str, selection: object) -> None:
    """Keep automatically chosen sizes in the exact binary plan, with no inferred zone."""

    sizes = selection_sizes(selection)
    actual = image_vm_selections(projection, region=region)
    if tuple(item.size for item in actual) != sizes or any(
        item.zone is not None for item in actual
    ):
        raise CheckError(PLAN_INVALID, 3)


def load_sku_json(data: bytes, *, max_bytes: int) -> dict[str, object]:
    """Decode bounded evidence without duplicate keys, nonfinite numbers, or raw errors."""

    if not data or len(data) > max_bytes:
        raise CheckError(EVIDENCE_INVALID)
    try:
        value = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise CheckError(EVIDENCE_INVALID) from None
    if not isinstance(value, dict):
        raise CheckError(EVIDENCE_INVALID)
    return value


def _unique_object(items: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in items:
        if key in value:
            raise ValueError(EVIDENCE_INVALID)
        value[key] = item
    return value


def _invalid_constant(_value: str) -> NoReturn:
    raise ValueError(EVIDENCE_INVALID)


def require_sku_eligibility(selections: tuple[PlannedVmSku, ...], rows: list[object]) -> None:
    """Reject applicable restrictions or incomplete exact-SKU evidence; do not reserve capacity."""

    expected = {selection.size for selection in selections}
    by_size: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise CheckError(EVIDENCE_INVALID)
        name = row.get("name")
        if (
            not isinstance(name, str)
            or name not in expected
            or name in by_size
            or row.get("resourceType") != "virtualMachines"
        ):
            raise CheckError(EVIDENCE_INVALID)
        by_size[name] = row
    if set(by_size) != expected:
        raise CheckError(EVIDENCE_INVALID)
    for selection in selections:
        row = by_size[selection.size]
        if selection.region not in _locations(row.get("locations")):
            raise CheckError(EVIDENCE_INVALID)
        restrictions = row.get("restrictions")
        if not isinstance(restrictions, list) or len(restrictions) > 64:
            raise CheckError(EVIDENCE_INVALID)
        if selection.zone is not None:
            _require_offered_zone(row, selection)
        if any(_restriction_applies(item, selection) for item in restrictions):
            raise CheckError(SKU_RESTRICTED, 3)


def _locations(value: object) -> set[str]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 64
        or any(not isinstance(item, str) or _LOCATION.fullmatch(item) is None for item in value)
    ):
        raise CheckError(EVIDENCE_INVALID)
    return {item.casefold() for item in value}


def _zones(value: object) -> set[str]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 64
        or any(not isinstance(item, str) or _ZONE.fullmatch(item) is None for item in value)
    ):
        raise CheckError(EVIDENCE_INVALID)
    return set(value)


def _require_offered_zone(row: dict[str, object], selection: PlannedVmSku) -> None:
    info = row.get("locationInfo")
    if not isinstance(info, list) or not 1 <= len(info) <= 64:
        raise CheckError(EVIDENCE_INVALID)
    matches = []
    for entry in info:
        if not isinstance(entry, dict) or not isinstance(entry.get("location"), str):
            raise CheckError(EVIDENCE_INVALID)
        if entry["location"].casefold() == selection.region:
            matches.append(entry)
    if len(matches) != 1 or selection.zone not in _zones(matches[0].get("zones")):
        raise CheckError(EVIDENCE_INVALID)


def _restriction_applies(value: object, selection: PlannedVmSku) -> bool:
    """A zone-only restriction does not silently become a regional restriction."""

    if not isinstance(value, dict) or value.get("reasonCode") not in (
        "NotAvailableForSubscription",
        "QuotaId",
    ):
        raise CheckError(EVIDENCE_INVALID)
    kind = value.get("type")
    info = value.get("restrictionInfo", {})
    if not isinstance(info, dict):
        raise CheckError(EVIDENCE_INVALID)
    if kind == "Location":
        locations = _locations(info.get("locations", value.get("values")))
        if "values" in value and _locations(value["values"]) != locations:
            raise CheckError(EVIDENCE_INVALID)
        return selection.region in locations
    if kind == "Zone":
        locations = _locations(info.get("locations"))
        # ARM defines zone scope in restrictionInfo, not the generic values field.
        zones = _zones(info.get("zones"))
        return selection.region in locations and selection.zone in zones
    raise CheckError(EVIDENCE_INVALID)
