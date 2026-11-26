"""Synthetic auto-selection evidence; no Azure calls or allocation-capacity claims."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

from genesis_checks import CheckError  # noqa: E402
from genesis_runner_image_sku_choice import (  # noqa: E402
    NO_COMPATIBLE,
    NO_HEADROOM,
    choose_image_vm_pair,
    parse_sku_policy,
    require_selected_pair,
)
from genesis_runner_image_skus import EVIDENCE_INVALID  # noqa: E402

POLICY_PATH = ROOT / "infra/genesis-runner-image/sku-policy.json"
REGION = "eastus"


def sku_rows() -> list[dict[str, Any]]:
    return [
        {
            "resourceType": "virtualMachines",
            "name": size,
            "locations": ["EastUS"],
            "restrictions": [],
            "family": family,
            "capabilities": [
                {"name": key, "value": value}
                for key, value in {
                    "CpuArchitectureType": "x64",
                    "HyperVGenerations": "V1,V2",
                    "vCPUs": "2",
                    "MemoryGB": memory,
                    "OSVhdSizeMB": "1047552",
                }.items()
            ],
        }
        for size, memory, family in (
            ("Standard_B2s", "4", "standardBSFamily"),
            ("Standard_D2ds_v5", "8", "standardDDSv5Family"),
            ("Standard_D2s_v5", "8", "standardDSv5Family"),
            ("Standard_D2ads_v5", "8", "standardDADSv5Family"),
            ("Standard_D2as_v5", "8", "standardDASv5Family"),
        )
    ]


def usage_rows() -> list[dict[str, Any]]:
    return [
        {"name": name, "current": "0", "limit": "100"}
        for name in (
            "cores",
            "standardBSFamily",
            "standardDDSv5Family",
            "standardDSv5Family",
            "standardDADSv5Family",
            "standardDASv5Family",
        )
    ]


def restricted(row: dict[str, Any]) -> None:
    row["restrictions"] = [
        {
            "type": "Location",
            "values": ["EastUS"],
            "reasonCode": "NotAvailableForSubscription",
        }
    ]


def select(rows: list[object], usage: list[object] | None = None) -> tuple[str, str]:
    return choose_image_vm_pair(
        parse_sku_policy(POLICY_PATH.read_bytes()),
        region=REGION,
        rows=rows,
        usages=usage_rows() if usage is None else usage,
    )


def test_available_defaults_are_preferred_without_changing_input() -> None:
    rows, usages = sku_rows(), usage_rows()
    before = copy.deepcopy((rows, usages))
    assert select(rows, usages) == ("Standard_D2ds_v5", "Standard_B2s")
    assert (rows, usages) == before


def test_restricted_b2s_automatically_selects_compatible_d2ds() -> None:
    rows = sku_rows()
    restricted(rows[0])
    assert select(rows) == ("Standard_D2ds_v5", "Standard_D2ds_v5")


def test_builder_and_verifier_can_both_choose_an_available_alternative() -> None:
    rows = sku_rows()
    for row in rows[:2]:
        restricted(row)
    assert select(rows) == ("Standard_D2s_v5", "Standard_D2s_v5")
    assert select(list(reversed(rows))) == select(rows)


def test_complete_snapshot_absence_skips_only_missing_candidates() -> None:
    assert select(sku_rows()[2:]) == ("Standard_D2s_v5", "Standard_D2s_v5")


def test_all_restricted_does_not_change_region_or_ignore_restrictions() -> None:
    rows = sku_rows()
    for row in rows:
        restricted(row)
    with pytest.raises(CheckError, match=NO_COMPATIBLE):
        select(rows)


def test_same_family_usage_is_aggregated_across_both_vm_roles() -> None:
    rows = sku_rows()
    restricted(rows[0])
    usages = usage_rows()
    usages[2]["limit"] = 2
    assert select(rows, usages) == ("Standard_D2ds_v5", "Standard_D2s_v5")


def test_exhausted_preferred_family_selects_next_pair() -> None:
    usages = usage_rows()
    usages[2]["current"] = "100"
    assert select(sku_rows(), usages) == ("Standard_D2s_v5", "Standard_B2s")


def test_total_regional_headroom_is_required_even_for_different_families() -> None:
    usages = usage_rows()
    usages[0]["limit"] = 3
    with pytest.raises(CheckError, match=NO_HEADROOM):
        select(sku_rows(), usages)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CpuArchitectureType", "Arm64"),
        ("HyperVGenerations", "V1"),
        ("MemoryGB", "2"),
        ("MemoryGB", "16"),
        ("vCPUs", "4"),
        ("OSVhdSizeMB", "32768"),
    ],
)
def test_incompatible_candidate_is_not_selected(name: str, value: str) -> None:
    rows = sku_rows()
    caps = rows[1]["capabilities"]
    next(cap for cap in caps if cap["name"] == name)["value"] = value
    assert select(rows) == ("Standard_D2s_v5", "Standard_B2s")


@pytest.mark.parametrize("value", [None, True, "nan", "-1", "Infinity", "two", "1e1000"])
def test_unknown_capability_is_not_silently_skipped(value: object) -> None:
    rows = sku_rows()
    next(cap for cap in rows[1]["capabilities"] if cap["name"] == "MemoryGB")["value"] = value
    with pytest.raises(CheckError, match=EVIDENCE_INVALID):
        select(rows)


@pytest.mark.parametrize(
    "mutation",
    [
        "no_rows",
        "duplicate",
        "null",
        "wrong_size",
        "unknown_restriction",
        "family",
        "caps_missing",
        "caps_duplicate",
        "arch_missing",
        "generation_invalid",
        "location_invalid",
    ],
)
def test_partial_or_ambiguous_evidence_never_becomes_an_available_fallback(mutation: str) -> None:
    rows = sku_rows()
    if mutation == "no_rows":
        rows = []
    elif mutation == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif mutation == "null":
        rows.append(None)
    elif mutation == "wrong_size":
        rows[1]["name"] = "Standard_NC24s_v3"
    elif mutation == "unknown_restriction":
        rows[0]["restrictions"] = None
    elif mutation == "family":
        rows[1]["family"] = None
    elif mutation == "caps_missing":
        rows[1]["capabilities"] = None
    elif mutation == "caps_duplicate":
        rows[1]["capabilities"] *= 2
    elif mutation == "arch_missing":
        rows[1]["capabilities"] = rows[1]["capabilities"][1:]
    elif mutation == "generation_invalid":
        rows[1]["capabilities"][1]["value"] = "V3"
    else:
        rows[1]["locations"] = ["different-region"]
    with pytest.raises(
        CheckError, match=NO_COMPATIBLE if mutation == "no_rows" else EVIDENCE_INVALID
    ):
        select(rows)


@pytest.mark.parametrize("value", [True, None, "1.5", -1, float("inf")])
def test_unknown_quota_is_not_treated_as_unlimited(value: object) -> None:
    usages = usage_rows()
    usages[0]["limit"] = value
    with pytest.raises(CheckError, match=EVIDENCE_INVALID):
        select(sku_rows(), usages)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "null"])
def test_quota_snapshot_must_cover_the_available_families(mutation: str) -> None:
    usages = usage_rows()
    if mutation == "missing":
        usages.pop()
    elif mutation == "duplicate":
        usages.append(usages[0])
    else:
        usages.append(None)
    with pytest.raises(CheckError, match=EVIDENCE_INVALID):
        select(sku_rows(), usages)


def test_apply_rechecks_the_sealed_pair_without_selecting_a_new_preferred_pair() -> None:
    policy = parse_sku_policy(POLICY_PATH.read_bytes())
    rows = sku_rows()
    require_selected_pair(
        policy,
        region=REGION,
        rows=rows[1:2],
        usages=usage_rows(),
        builder="Standard_D2ds_v5",
        verifier="Standard_D2ds_v5",
    )
    restricted(rows[1])
    with pytest.raises(CheckError, match=NO_COMPATIBLE):
        require_selected_pair(
            policy,
            region=REGION,
            rows=rows,
            usages=usage_rows(),
            builder="Standard_D2ds_v5",
            verifier="Standard_D2ds_v5",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "extra",
        "large",
        "architecture",
        "generation",
        "disk",
        "memory",
        "roles",
        "minimum",
        "burst_builder",
        "duplicate",
        "empty",
        "gpu",
        "string",
    ],
)
def test_policy_cannot_widen_the_reviewed_small_vm_envelope(mutation: str) -> None:
    value = json.loads(POLICY_PATH.read_bytes())
    if mutation == "schema":
        value["schema_version"] = "future"
    elif mutation == "extra":
        value["fallback_region"] = "westus"
    elif mutation == "large":
        value["vcpu_count"] = 32
    elif mutation == "architecture":
        value["architecture"] = "Arm64"
    elif mutation == "generation":
        value["hyper_v_generation"] = "V1"
    elif mutation == "disk":
        value["os_disk_gib"] = False
    elif mutation == "memory":
        value["max_memory_gib"] = 64
    elif mutation == "roles":
        value["roles"] = []
    elif mutation == "minimum":
        value["roles"]["builder"]["min_memory_gib"] = 2
    elif mutation == "burst_builder":
        value["roles"]["builder"]["candidates"] = ["Standard_B2s"]
    elif mutation == "duplicate":
        value["roles"]["verifier"]["candidates"] = ["Standard_B2s"] * 2
    elif mutation == "empty":
        value["roles"]["verifier"]["candidates"] = []
    elif mutation == "gpu":
        value["roles"]["verifier"]["candidates"] = ["Standard_NC24s_v3"]
    else:
        value["roles"]["builder"] = "auto"
    with pytest.raises(CheckError, match="runner_image_sku_policy_invalid"):
        parse_sku_policy(json.dumps(value).encode())
