"""Validate the signed, capability-based small VM policy independently of provider I/O."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from genesis_checks import CheckError
from genesis_runner_image_skus import load_sku_json

POLICY_INVALID = "deployment_vm_sku_policy_invalid"
_PREFERENCE = re.compile(r"Standard_[A-Za-z0-9_]{1,64}")


@dataclass(frozen=True)
class VmRole:
    """One reviewed hardware envelope; preferences never substitute for actual capabilities."""

    name: str
    vcpus: int
    min_memory_gib: int
    max_memory_gib: int
    series: tuple[str, ...]
    disk_mode: str
    preferred: tuple[str, ...]


@dataclass(frozen=True)
class VmPolicy:
    """Immutable policy for the exact three-role generated-image deployment path."""

    builder: VmRole
    verifier: VmRole
    foundation: VmRole
    os_disk_gib: int
    digest: str


def parse_vm_policy(raw: bytes) -> VmPolicy:
    """Keep discovery within existing small CPU/memory/disk and x64 Gen2 constraints."""
    value = load_sku_json(raw, max_bytes=16_384)
    if (
        set(value)
        != {"schema_version", "architecture", "hyper_v_generation", "os_disk_gib", "roles"}
        or value["schema_version"] != "fdai.deployment-vm-sku-policy.v2"
        or value["architecture"] != "x64"
        or value["hyper_v_generation"] != "V2"
        or type(value["os_disk_gib"]) is not int
        or value["os_disk_gib"] != 64
        or not isinstance(value["roles"], dict)
        or set(value["roles"]) != {"builder", "verifier", "foundation"}
    ):
        raise CheckError(POLICY_INVALID, 3)
    roles: dict[str, VmRole] = {}
    for name, cpu, low, high, series, disk in (
        ("builder", 2, 8, 8, {"D", "F"}, "managed"),
        ("verifier", 2, 4, 8, {"B", "D", "F"}, "managed"),
        ("foundation", 4, 8, 16, {"D", "F"}, "resource-disk"),
    ):
        entry = value["roles"][name]
        if not isinstance(entry, dict) or set(entry) != {
            "vcpus",
            "min_memory_gib",
            "max_memory_gib",
            "series",
            "disk_mode",
            "preferred",
        }:
            raise CheckError(POLICY_INVALID, 3)
        if (
            any(type(entry[k]) is not int for k in ("vcpus", "min_memory_gib", "max_memory_gib"))
            or entry["vcpus"] != cpu
            or not low <= entry["min_memory_gib"] <= entry["max_memory_gib"] <= high
            or entry["disk_mode"] != disk
        ):
            raise CheckError(POLICY_INVALID, 3)
        families, preferred = entry["series"], entry["preferred"]
        if (
            not isinstance(families, list)
            or not families
            or any(not isinstance(item, str) or item not in series for item in families)
            or len(set(families)) != len(families)
            or not isinstance(preferred, list)
            or len(preferred) > 16
            or any(
                not isinstance(item, str) or _PREFERENCE.fullmatch(item) is None
                for item in preferred
            )
            or len(set(preferred)) != len(preferred)
        ):
            raise CheckError(POLICY_INVALID, 3)
        roles[name] = VmRole(
            name,
            cpu,
            entry["min_memory_gib"],
            entry["max_memory_gib"],
            tuple(families),
            disk,
            tuple(preferred),
        )
    return VmPolicy(
        roles["builder"],
        roles["verifier"],
        roles["foundation"],
        64,
        hashlib.sha256(raw).hexdigest(),
    )
