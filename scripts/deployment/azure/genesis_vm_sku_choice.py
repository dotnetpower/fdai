"""Choose actual compatible VM roles from complete metadata, without provider effects."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from itertools import product

from genesis_checks import CheckError
from genesis_runner_image_sku_choice import _number, _quota_headroom
from genesis_runner_image_skus import (
    EVIDENCE_INVALID,
    SKU_RESTRICTED,
    PlannedVmSku,
    require_sku_eligibility,
)
from genesis_vm_sku_policy import VmPolicy, VmRole

ALL_RESTRICTED = "deployment_vm_skus_restricted_in_selected_region"
NO_HARDWARE = "deployment_vm_no_compatible_hardware"
NO_QUOTA = "deployment_vm_combined_quota_insufficient"
_STANDARD = re.compile(r"Standard_([BDF])[0-9]+[a-z]*(?:_v[1-9][0-9]*)?")
_NAME = re.compile(r"[A-Za-z0-9_-]{1,100}")
_FAMILY = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,79}")
_MAX_CANDIDATES = 128


@dataclass(frozen=True)
class VmCandidate:
    """One complete compatible VM option; eligibility is not allocation or execution authority."""

    size: str
    family: str
    vcpus: int
    memory_gib: Decimal
    series: str
    resource_disk_mb: Decimal
    ephemeral: bool


@dataclass(frozen=True)
class CatalogOptions:
    """Deterministically ordered role pools and non-identifying completeness counters."""

    builder: tuple[VmCandidate, ...]
    verifier: tuple[VmCandidate, ...]
    foundation: tuple[VmCandidate, ...]
    total: int
    restricted: int
    excluded: int


@dataclass(frozen=True)
class VmSelection:
    """The complete no-authority three-VM selection for one new deployment context."""

    builder: VmCandidate
    verifier: VmCandidate
    foundation: VmCandidate


def catalog_options(policy: VmPolicy, *, region: str, rows: list[object]) -> CatalogOptions:
    """Reject ambiguous evidence; filter known incompatibility rather than a fixed name list."""
    if not rows or len(rows) > 4096:
        raise CheckError(EVIDENCE_INVALID, 3)
    candidates: list[VmCandidate] = []
    names: set[str] = set()
    restricted = excluded = 0
    for row in rows:
        if not isinstance(row, dict):
            raise CheckError(EVIDENCE_INVALID, 3)
        name = row.get("name")
        if not isinstance(name, str) or _NAME.fullmatch(name) is None or name in names:
            raise CheckError(EVIDENCE_INVALID, 3)
        names.add(name)
        try:
            require_sku_eligibility((PlannedVmSku(name, region.casefold(), None),), [row])
        except CheckError as exc:
            if exc.reason_code != SKU_RESTRICTED:
                raise
            restricted += 1
            continue
        candidate = _hardware(row, policy)
        if candidate is None:
            excluded += 1
        else:
            candidates.append(candidate)
    pools: dict[str, tuple[VmCandidate, ...]] = {}
    for role in (policy.builder, policy.verifier, policy.foundation):
        pool = [
            candidate for candidate in candidates if _fits_role(candidate, role, policy.os_disk_gib)
        ]
        if len(pool) > _MAX_CANDIDATES:
            raise CheckError(EVIDENCE_INVALID, 3)
        pools[role.name] = tuple(sorted(pool, key=lambda item: _rank(item, role)))
    return CatalogOptions(
        pools["builder"], pools["verifier"], pools["foundation"], len(rows), restricted, excluded
    )


def choose_deployment_vms(
    policy: VmPolicy,
    *,
    region: str,
    rows: list[object],
    usages: list[object],
    foundation_size: str | None = None,
) -> VmSelection:
    """Choose three roles with aggregate quota; an explicit host remains fixed, never replaced."""
    options = catalog_options(policy, region=region, rows=rows)
    hosts = options.foundation
    if foundation_size is not None:
        hosts = tuple(item for item in hosts if item.size == foundation_size)
    if not options.builder or not options.verifier or not hosts:
        raise CheckError(ALL_RESTRICTED if options.restricted == options.total else NO_HARDWARE, 3)
    families = {item.family for item in (*options.builder, *options.verifier, *hosts)}
    headroom = _quota_headroom(usages, families=families)
    if headroom["cores"] < 8:
        raise CheckError(NO_QUOTA, 3)
    # Keep the deployment host stable first, then prefer the reviewed image pair. Provider order
    # never participates; every role has the same fixed CPU count inside this policy version.
    for host, builder, verifier in product(hosts, options.builder, options.verifier):
        if _fits_quota((builder, verifier, host), headroom):
            return VmSelection(builder, verifier, host)
    raise CheckError(NO_QUOTA, 3)


def require_deployment_vms(
    policy: VmPolicy,
    *,
    region: str,
    rows: list[object],
    usages: list[object],
    builder: str,
    verifier: str,
    foundation: str,
) -> None:
    """Recheck the exact sealed triplet without running ranking or selecting an alternative."""
    options = catalog_options(policy, region=region, rows=rows)
    selected = (
        _exact(options.builder, builder),
        _exact(options.verifier, verifier),
        _exact(options.foundation, foundation),
    )
    headroom = _quota_headroom(usages, families={item.family for item in selected})
    if not _fits_quota(selected, headroom):
        raise CheckError(NO_QUOTA, 3)


def require_foundation_vm(
    policy: VmPolicy,
    *,
    region: str,
    rows: list[object],
    usages: list[object],
    size: str,
    image_disk_gib: int,
) -> None:
    """Verify one sealed host against the observed image size, not the image-builder disk model."""
    if type(image_disk_gib) is not int or not 1 <= image_disk_gib <= 2048:
        raise CheckError(EVIDENCE_INVALID, 3)
    options = catalog_options(policy, region=region, rows=rows)
    selected = _exact(options.foundation, size)
    if selected.resource_disk_mb < image_disk_gib * 1024:
        raise CheckError(NO_HARDWARE, 3)
    headroom = _quota_headroom(usages, families={selected.family})
    if not _fits_quota((selected,), headroom):
        raise CheckError(NO_QUOTA, 3)


def _hardware(row: dict[str, object], policy: VmPolicy) -> VmCandidate | None:
    name = str(row["name"])
    match = _STANDARD.fullmatch(name)
    if match is None:
        return None
    raw = row.get("capabilities")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 128:
        raise CheckError(EVIDENCE_INVALID, 3)
    caps: dict[str, str] = {}
    for item in raw:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("value"), str)
            or item["name"] in caps
        ):
            raise CheckError(EVIDENCE_INVALID, 3)
        caps[item["name"]] = item["value"]
    architecture, generations = caps.get("CpuArchitectureType"), caps.get("HyperVGenerations")
    if (
        architecture not in ("x64", "Arm64")
        or not generations
        or not set(generations.split(",")) <= {"V1", "V2"}
    ):
        raise CheckError(EVIDENCE_INVALID, 3)
    if architecture != "x64" or "V2" not in generations.split(","):
        return None
    cpu, available, memory = (
        _number(caps.get("vCPUs")),
        _number(caps.get("vCPUsAvailable")),
        _number(caps.get("MemoryGB")),
    )
    if cpu not in (2, 4) or cpu != available or not 4 <= memory <= 16:
        return None
    if _number(caps.get("OSVhdSizeMB")) < policy.os_disk_gib * 1024:
        return None
    if "GPUs" in caps and _number(caps["GPUs"]) != 0:
        return None
    if caps.get("ConfidentialComputingType", "None") not in ("None", "Disabled"):
        return None
    family = row.get("family")
    if not isinstance(family, str) or _FAMILY.fullmatch(family) is None:
        raise CheckError(EVIDENCE_INVALID, 3)
    disk = Decimal(0)
    ephemeral = False
    if cpu == 4:
        supported = caps.get("EphemeralOSDiskSupported")
        if supported not in ("True", "False"):
            raise CheckError(EVIDENCE_INVALID, 3)
        disk = _number(caps.get("MaxResourceVolumeMB"))
        placements = caps.get("EphemeralOSDiskPlacement")
        ephemeral = supported == "True" and (
            placements is None or "ResourceDisk" in placements.split(",")
        )
    return VmCandidate(name, family.casefold(), int(cpu), memory, match[1], disk, ephemeral)


def _fits_role(value: VmCandidate, role: VmRole, disk_gib: int) -> bool:
    return (
        value.series in role.series
        and value.vcpus == role.vcpus
        and role.min_memory_gib <= value.memory_gib <= role.max_memory_gib
        and (
            role.disk_mode == "managed"
            or (value.ephemeral and value.resource_disk_mb >= disk_gib * 1024)
        )
    )


def _rank(value: VmCandidate, role: VmRole) -> tuple[int, Decimal, str]:
    position = (
        role.preferred.index(value.size) if value.size in role.preferred else len(role.preferred)
    )
    return position, value.memory_gib, value.size


def _exact(options: tuple[VmCandidate, ...], size: str) -> VmCandidate:
    for value in options:
        if value.size == size:
            return value
    raise CheckError(NO_HARDWARE, 3)


def _fits_quota(values: tuple[VmCandidate, ...], headroom: dict[str, int]) -> bool:
    demand = Counter({"cores": sum(value.vcpus for value in values)})
    for value in values:
        demand[value.family] += value.vcpus
    return all(headroom[key] >= count for key, count in demand.items())
