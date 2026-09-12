"""Choose a reviewed small-VM pair before planning; never authorize or retry an effect."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from itertools import product

from genesis_checks import CheckError
from genesis_runner_image_skus import (
    EVIDENCE_INVALID,
    SKU_RESTRICTED,
    PlannedVmSku,
    load_sku_json,
    require_sku_eligibility,
)

_SMALL_SKU = re.compile(r"Standard_(?:B2s|D2(?:s|ds|as|ads)_v5)")
_FAMILY = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,79}")
_NUMBER = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,3})?")
_POLICY_INVALID = "runner_image_sku_policy_invalid"
NO_COMPATIBLE = "runner_image_no_compatible_sku_in_selected_region"
NO_HEADROOM = "runner_image_sku_pair_quota_insufficient"


@dataclass(frozen=True)
class SkuPolicy:
    """Signed-root preferences inside the fixed 2-vCPU, 4-8-GiB review envelope."""

    builder: tuple[str, ...]
    verifier: tuple[str, ...]
    verifier_min_memory_gib: int
    digest: str

    @property
    def candidates(self) -> tuple[str, ...]:
        """Return the complete unique candidate set for one bounded provider read."""

        return tuple(sorted(set(self.builder + self.verifier)))


@dataclass(frozen=True)
class VmCandidate:
    """A compatible, region-eligible SKU with an observed quota family."""

    size: str
    memory_gib: Decimal
    family: str


def parse_sku_policy(raw: bytes) -> SkuPolicy:
    """Validate a bounded policy; larger, GPU, ARM, and burstable builders are not candidates."""

    value = load_sku_json(raw, max_bytes=16_384)
    if (
        set(value)
        != {
            "schema_version",
            "architecture",
            "hyper_v_generation",
            "os_disk_gib",
            "vcpu_count",
            "max_memory_gib",
            "roles",
        }
        or value["schema_version"] != "fdai.runner-image-sku-policy.v1"
        or value["architecture"] != "x64"
        or value["hyper_v_generation"] != "V2"
        or any(
            type(value[key]) is not int or value[key] != expected
            for key, expected in (
                ("os_disk_gib", 64),
                ("vcpu_count", 2),
                ("max_memory_gib", 8),
            )
        )
    ):
        raise CheckError(_POLICY_INVALID, 3)
    roles = value["roles"]
    if not isinstance(roles, dict) or set(roles) != {"builder", "verifier"}:
        raise CheckError(_POLICY_INVALID, 3)
    candidates: dict[str, tuple[str, ...]] = {}
    for role in ("builder", "verifier"):
        entry = roles[role]
        if not isinstance(entry, dict) or set(entry) != {"min_memory_gib", "candidates"}:
            raise CheckError(_POLICY_INVALID, 3)
        minimum, sizes = entry["min_memory_gib"], entry["candidates"]
        if (
            type(minimum) is not int
            or not (minimum == 8 if role == "builder" else 4 <= minimum <= 8)
            or not isinstance(sizes, list)
            or not 1 <= len(sizes) <= 5
            or any(
                not isinstance(size, str) or _SMALL_SKU.fullmatch(size) is None for size in sizes
            )
            or len(set(sizes)) != len(sizes)
            or (role == "builder" and "Standard_B2s" in sizes)
        ):
            raise CheckError(_POLICY_INVALID, 3)
        candidates[role] = tuple(sizes)
    return SkuPolicy(
        candidates["builder"],
        candidates["verifier"],
        roles["verifier"]["min_memory_gib"],
        hashlib.sha256(raw).hexdigest(),
    )


def choose_image_vm_pair(
    policy: SkuPolicy, *, region: str, rows: list[object], usages: list[object]
) -> tuple[str, str]:
    """Select in policy order only after both roles fit aggregate regional/family headroom.

    A complete scan can prove that a candidate is absent. Malformed or ambiguous evidence
    cannot be skipped as though that candidate were merely unavailable. No price or capacity
    reservation is implied by this small hardware envelope and the existing cost review.
    """

    available = _compatible_candidates(policy, region=region, rows=rows)
    builders = [
        available[size]
        for size in policy.builder
        if size in available and available[size].memory_gib >= 8
    ]
    verifiers = [
        available[size]
        for size in policy.verifier
        if size in available and available[size].memory_gib >= policy.verifier_min_memory_gib
    ]
    if not builders or not verifiers:
        raise CheckError(NO_COMPATIBLE, 3)
    headroom = _quota_headroom(usages, families={item.family for item in builders + verifiers})
    for builder, verifier in product(builders, verifiers):
        if _pair_fits(builder, verifier, headroom):
            return builder.size, verifier.size
    raise CheckError(NO_HEADROOM, 3)


def require_selected_pair(
    policy: SkuPolicy,
    *,
    region: str,
    rows: list[object],
    usages: list[object],
    builder: str,
    verifier: str,
) -> None:
    """Recheck only the sealed pair, never rerank or replace it at the apply boundary."""

    if builder not in policy.builder or verifier not in policy.verifier:
        raise CheckError(_POLICY_INVALID, 3)
    available = _compatible_candidates(policy, region=region, rows=rows)
    if (
        builder not in available
        or verifier not in available
        or available[builder].memory_gib < 8
        or available[verifier].memory_gib < policy.verifier_min_memory_gib
    ):
        raise CheckError(NO_COMPATIBLE, 3)
    pair = available[builder], available[verifier]
    headroom = _quota_headroom(usages, families={item.family for item in pair})
    if not _pair_fits(*pair, headroom):
        raise CheckError(NO_HEADROOM, 3)


def _compatible_candidates(
    policy: SkuPolicy, *, region: str, rows: list[object]
) -> dict[str, VmCandidate]:
    available: dict[str, VmCandidate] = {}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise CheckError(EVIDENCE_INVALID)
        size = row.get("name")
        if not isinstance(size, str) or size not in policy.candidates or size in seen:
            raise CheckError(EVIDENCE_INVALID)
        seen.add(size)
        try:
            require_sku_eligibility((PlannedVmSku(size, region.casefold(), None),), [row])
        except CheckError as exc:
            if exc.reason_code == SKU_RESTRICTED:
                continue
            raise
        family, raw_caps = row.get("family"), row.get("capabilities")
        if (
            not isinstance(family, str)
            or _FAMILY.fullmatch(family) is None
            or not isinstance(raw_caps, list)
            or len(raw_caps) > 128
        ):
            raise CheckError(EVIDENCE_INVALID)
        caps: dict[str, str] = {}
        for item in raw_caps:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str)
                or not isinstance(item.get("value"), str)
                or item["name"] in caps
            ):
                raise CheckError(EVIDENCE_INVALID)
            caps[item["name"]] = item["value"]
        arch, generations = caps.get("CpuArchitectureType"), caps.get("HyperVGenerations")
        if (
            arch not in ("x64", "Arm64")
            or not isinstance(generations, str)
            or not set(generations.split(",")) <= {"V1", "V2"}
        ):
            raise CheckError(EVIDENCE_INVALID)
        vcpus = _number(caps.get("vCPUs"))
        memory = _number(caps.get("MemoryGB"))
        os_disk = _number(caps.get("OSVhdSizeMB"))
        if (
            arch == "x64"
            and "V2" in generations.split(",")
            and vcpus == 2
            and 4 <= memory <= 8
            and os_disk >= 64 * 1024
        ):
            available[size] = VmCandidate(size, memory, family.casefold())
    return available


def _number(value: object) -> Decimal:
    if not isinstance(value, str) or _NUMBER.fullmatch(value) is None:
        raise CheckError(EVIDENCE_INVALID)
    return Decimal(value)


def _quota_headroom(rows: list[object], *, families: set[str]) -> dict[str, int]:
    required = families | {"cores"}
    result: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise CheckError(EVIDENCE_INVALID)
        name = row["name"].casefold()
        if name not in required:
            continue
        if name in result:
            raise CheckError(EVIDENCE_INVALID)
        used, limit = row.get("current"), row.get("limit")
        for value in (used, limit):
            if not (
                (type(value) is int and 0 <= value <= 10**9)
                or (isinstance(value, str) and re.fullmatch(r"[0-9]{1,9}", value))
            ):
                raise CheckError(EVIDENCE_INVALID)
        result[name] = max(0, int(str(limit)) - int(str(used)))
    if set(result) != required:
        raise CheckError(EVIDENCE_INVALID)
    return result


def _pair_fits(builder: VmCandidate, verifier: VmCandidate, headroom: dict[str, int]) -> bool:
    demand = Counter({"cores": 4})
    demand[builder.family] += 2
    demand[verifier.family] += 2
    return all(headroom[name] >= count for name, count in demand.items())
