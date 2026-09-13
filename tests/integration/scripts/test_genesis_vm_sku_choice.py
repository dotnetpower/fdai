"""Capability-based VM discovery with synthetic provider facts, not fabricated live capacity."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

from genesis_checks import CheckError  # noqa: E402
from genesis_runner_image_skus import EVIDENCE_INVALID  # noqa: E402
from genesis_vm_sku_choice import (  # noqa: E402
    ALL_RESTRICTED,
    NO_HARDWARE,
    NO_QUOTA,
    catalog_options,
    choose_deployment_vms,
    require_deployment_vms,
    require_foundation_vm,
)
from genesis_vm_sku_policy import parse_vm_policy  # noqa: E402

POLICY = ROOT / "infra/genesis-runner-image/vm-sku-policy.json"


def policy():
    return parse_vm_policy(POLICY.read_bytes())


def sku(
    name="Standard_D2ds_v4",
    *,
    cpu=2,
    memory=8,
    disk=0,
    region="eastus",
    family="standardDDSv4Family",
):
    return {
        "name": name,
        "resourceType": "virtualMachines",
        "locations": [region.upper()],
        "restrictions": [],
        "family": family,
        "capabilities": [
            {"name": key, "value": value}
            for key, value in {
                "CpuArchitectureType": "x64",
                "HyperVGenerations": "V1,V2",
                "vCPUs": str(cpu),
                "vCPUsAvailable": str(cpu),
                "MemoryGB": str(memory),
                "OSVhdSizeMB": "1047552",
                "EphemeralOSDiskSupported": "True" if disk else "False",
                "MaxResourceVolumeMB": str(disk),
            }.items()
        ],
    }


def capabilities(row):
    return {item["name"]: item for item in row["capabilities"]}


def rows(region="eastus"):
    return [
        sku(region=region),
        sku("Standard_D4ds_v4", cpu=4, memory=16, disk=153600, region=region),
    ]


def usages(*, family="standardDDSv4Family", limit=100):
    return [
        {"name": "cores", "current": "0", "limit": str(limit)},
        {"name": family, "current": "0", "limit": str(limit)},
    ]


def restrict(row):
    row["restrictions"] = [
        {
            "type": "Location",
            "values": row["locations"],
            "reasonCode": "NotAvailableForSubscription",
        }
    ]


def test_unlisted_compatible_skus_are_selected_and_inputs_are_immutable():
    catalog, quota = rows(), usages()
    before = copy.deepcopy((catalog, quota))
    selected = choose_deployment_vms(policy(), region="eastus", rows=catalog, usages=quota)
    assert selected.builder.size == selected.verifier.size == "Standard_D2ds_v4"
    assert selected.foundation.size == "Standard_D4ds_v4"
    assert (catalog, quota) == before
    assert (
        choose_deployment_vms(policy(), region="eastus", rows=catalog[::-1], usages=quota)
        == selected
    )


def test_restricted_preferred_names_do_not_exclude_other_generations():
    catalog = [sku("Standard_D2ds_v5"), sku("Standard_B2s", memory=4), *rows()]
    for item in catalog[:2]:
        restrict(item)
    selected = choose_deployment_vms(policy(), region="eastus", rows=catalog, usages=usages())
    assert selected.builder.size == selected.verifier.size == "Standard_D2ds_v4"


def test_image_pair_does_not_require_the_hosts_local_disk():
    catalog = rows()
    assert capabilities(catalog[0])["EphemeralOSDiskSupported"]["value"] == "False"
    selected = choose_deployment_vms(policy(), region="eastus", rows=catalog, usages=usages())
    assert selected.builder.resource_disk_mb == 0
    assert selected.foundation.resource_disk_mb >= 64 * 1024


def test_aggregate_quota_counts_all_three_vms_in_one_family():
    with pytest.raises(CheckError, match=NO_QUOTA):
        choose_deployment_vms(policy(), region="eastus", rows=rows(), usages=usages(limit=7))
    choose_deployment_vms(policy(), region="eastus", rows=rows(), usages=usages(limit=8))


def test_regional_quota_does_not_become_three_independent_checks():
    quota = usages()
    quota[0]["limit"] = 6
    with pytest.raises(CheckError, match=NO_QUOTA):
        choose_deployment_vms(policy(), region="eastus", rows=rows(), usages=quota)


def test_all_restricted_produces_explicit_counts_without_choosing_hardware():
    catalog = rows()
    for row in catalog:
        restrict(row)
    options = catalog_options(policy(), region="eastus", rows=catalog)
    assert options.total == options.restricted == 2
    assert not options.builder and not options.foundation
    with pytest.raises(CheckError, match=ALL_RESTRICTED):
        choose_deployment_vms(policy(), region="eastus", rows=catalog, usages=usages())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("CpuArchitectureType", "Arm64"),
        ("HyperVGenerations", "V1"),
        ("vCPUsAvailable", "1"),
        ("MemoryGB", "2"),
        ("OSVhdSizeMB", "32768"),
        ("GPUs", "1"),
        ("ConfidentialComputingType", "SNP"),
    ],
)
def test_incompatible_hardware_never_becomes_a_fallback(field, value):
    catalog = rows()
    caps = capabilities(catalog[0])
    if field in caps:
        caps[field]["value"] = value
    else:
        catalog[0]["capabilities"].append({"name": field, "value": value})
    with pytest.raises(CheckError, match=NO_HARDWARE):
        choose_deployment_vms(policy(), region="eastus", rows=catalog, usages=usages())


@pytest.mark.parametrize(
    "name",
    ["Standard_NC2s_v3", "Standard_DC2s_v3", "Standard_D4-2s_v5", "Basic_A2", "Standard_M2s"],
)
def test_specialized_and_constrained_variants_are_not_normal_small_vms(name):
    catalog = [sku(name), rows()[1]]
    with pytest.raises(CheckError, match=NO_HARDWARE):
        choose_deployment_vms(policy(), region="eastus", rows=catalog, usages=usages())


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "numeric_type",
        "infinite",
        "unknown_arch",
        "missing_available",
        "quota_missing",
        "duplicate_name",
        "foreign_region",
    ],
)
def test_incomplete_evidence_is_never_reported_as_zero_available(change):
    catalog, quota = rows(), usages()
    if change == "missing":
        catalog[0]["capabilities"] = []
    elif change == "duplicate":
        catalog[0]["capabilities"] *= 2
    elif change in {"numeric_type", "infinite"}:
        capabilities(catalog[0])["MemoryGB"]["value"] = (
            8 if change == "numeric_type" else "Infinity"
        )
    elif change == "unknown_arch":
        capabilities(catalog[0])["CpuArchitectureType"]["value"] = "unknown"
    elif change == "missing_available":
        catalog[0]["capabilities"] = [
            x for x in catalog[0]["capabilities"] if x["name"] != "vCPUsAvailable"
        ]
    elif change == "quota_missing":
        quota.pop()
    elif change == "duplicate_name":
        catalog.append(copy.deepcopy(catalog[0]))
    else:
        catalog[0]["locations"] = ["westus"]
    with pytest.raises(CheckError, match=EVIDENCE_INVALID):
        choose_deployment_vms(policy(), region="eastus", rows=catalog, usages=quota)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("EphemeralOSDiskSupported", "False"),
        ("MaxResourceVolumeMB", "32768"),
        ("EphemeralOSDiskPlacement", "NvmeDisk"),
        ("EphemeralOSDiskPlacement", "CacheDisk"),
    ],
)
def test_host_requires_resource_disk_not_cache_or_nvme(field, value):
    catalog = rows()
    caps = capabilities(catalog[1])
    if field in caps:
        caps[field]["value"] = value
    else:
        catalog[1]["capabilities"].append({"name": field, "value": value})
    with pytest.raises(CheckError, match=NO_HARDWARE):
        choose_deployment_vms(policy(), region="eastus", rows=catalog, usages=usages())


def test_actual_image_disk_must_fit_the_sealed_host():
    host = rows()[1]
    require_foundation_vm(
        policy(),
        region="eastus",
        rows=[host],
        usages=usages(),
        size=host["name"],
        image_disk_gib=64,
    )
    with pytest.raises(CheckError, match=NO_HARDWARE):
        require_foundation_vm(
            policy(),
            region="eastus",
            rows=[host],
            usages=usages(),
            size=host["name"],
            image_disk_gib=256,
        )


def test_explicit_host_is_not_silently_replaced_and_apply_never_reranks():
    with pytest.raises(CheckError, match=NO_HARDWARE):
        choose_deployment_vms(
            policy(),
            region="eastus",
            rows=rows(),
            usages=usages(),
            foundation_size="Standard_D4ds_v5",
        )
    require_deployment_vms(
        policy(),
        region="eastus",
        rows=rows(),
        usages=usages(),
        builder="Standard_D2ds_v4",
        verifier="Standard_D2ds_v4",
        foundation="Standard_D4ds_v4",
    )
    with pytest.raises(CheckError, match=NO_HARDWARE):
        require_deployment_vms(
            policy(),
            region="eastus",
            rows=rows(),
            usages=usages(),
            builder="Standard_D2ds_v5",
            verifier="Standard_D2ds_v4",
            foundation="Standard_D4ds_v4",
        )


def test_zone_only_restriction_does_not_forbid_unzoned_regional_selection():
    catalog = rows()
    catalog[0]["restrictions"] = [
        {
            "type": "Zone",
            "reasonCode": "NotAvailableForSubscription",
            "restrictionInfo": {"locations": ["EastUS"], "zones": ["1"]},
            "values": ["EastUS"],
        }
    ]
    assert (
        choose_deployment_vms(policy(), region="eastus", rows=catalog, usages=usages()).builder.size
        == "Standard_D2ds_v4"
    )


@pytest.mark.parametrize(
    "change",
    [
        "cpu",
        "memory",
        "disk",
        "architecture",
        "roles",
        "burst_host",
        "extra",
        "duplicate_preference",
    ],
)
def test_policy_remains_inside_reviewed_cost_and_hardware_envelope(change):
    value = json.loads(POLICY.read_bytes())
    if change == "cpu":
        value["roles"]["builder"]["vcpus"] = 32
    elif change == "memory":
        value["roles"]["foundation"]["max_memory_gib"] = 64
    elif change == "disk":
        value["os_disk_gib"] = 256
    elif change == "architecture":
        value["architecture"] = "Arm64"
    elif change == "roles":
        value["roles"].pop("foundation")
    elif change == "burst_host":
        value["roles"]["foundation"]["series"] = ["B"]
    elif change == "extra":
        value["fallback_region"] = "westus"
    else:
        value["roles"]["verifier"]["preferred"] = ["Standard_B2s"] * 2
    with pytest.raises(CheckError, match="policy_invalid"):
        parse_vm_policy(json.dumps(value).encode())
