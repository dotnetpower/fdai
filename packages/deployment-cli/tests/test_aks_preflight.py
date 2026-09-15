"""Capacity preflight never treats quota or SKU uncertainty as readiness."""

from __future__ import annotations

import copy
import subprocess
from dataclasses import replace

import pytest

from fdai_deployment_cli import aks_preflight
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile


def _inputs():
    profile = RuntimeDeploymentProfile.create(
        runtime_platform="aks",
        database_placement="postgres-flex",
        system_node_sku="Standard_D4as_v5",
    )
    skus = [
        {
            "name": "Standard_D4as_v5",
            "resourceType": "virtualMachines",
            "family": "standardDASv5Family",
            "capabilities": [
                {"name": "vCPUs", "value": "4"},
                {"name": "MemoryGB", "value": "16"},
                {"name": "EncryptionAtHostSupported", "value": "True"},
                {"name": "CpuArchitectureType", "value": "x64"},
            ],
            "locationInfo": [{"location": "eastus", "zones": ["1", "2", "3"]}],
            "restrictions": [],
        }
    ]
    usage = [
        {"name": {"value": name}, "currentValue": 0, "limit": 100}
        for name in ("standardDASv5Family", "cores")
    ]
    return {"profile": profile, "region": "eastus", "skus": skus, "usage": usage}


def test_quota_includes_both_pools_maximum_and_surge() -> None:
    result = aks_preflight.assess_aks_capacity(**_inputs())
    assert result["state"] == "feasible"
    assert all(quota["required_vcpus"] == 44 for quota in result["quotas"])


def test_azure_cli_string_quota_is_normalized_without_ignoring_restrictions() -> None:
    arguments = _inputs()
    for entry in arguments["usage"]:
        entry["currentValue"] = "0"
        entry["limit"] = "100"
    result = aks_preflight.assess_aks_capacity(**arguments)
    assert result["state"] == "feasible"
    assert all(quota["remaining_vcpus"] == 100 for quota in result["quotas"])
    arguments["skus"][0]["restrictions"] = [
        {"type": "Location", "reasonCode": "NotAvailableForSubscription"}
    ]
    result = aks_preflight.assess_aks_capacity(**arguments)
    assert result["state"] == "blocked"
    assert result["blockers"] == [
        "system_sku_restricted_or_unknown",
        "user_sku_restricted_or_unknown",
    ]


@pytest.mark.parametrize(
    "value", [True, False, -1, 1.5, "-1", "1.0", "1e2", "+10", " 10", "00", "9" * 20, None]
)
def test_invalid_quota_representation_remains_blocked(value) -> None:
    arguments = _inputs()
    arguments["usage"][0]["limit"] = value
    assert (
        "quota_standarddasv5family_invalid"
        in aks_preflight.assess_aks_capacity(**arguments)["blockers"]
    )


@pytest.mark.parametrize(
    "defect",
    [
        "absent",
        "restricted",
        "zones",
        "cpu",
        "encryption",
        "architecture",
        "quota",
        "duplicate-quota",
        "quota-bool",
        "memory-nan",
    ],
)
def test_capacity_uncertainty_blocks_deployment(defect: str) -> None:
    arguments = copy.deepcopy(_inputs())
    sku = arguments["skus"][0]
    if defect == "absent":
        arguments["skus"] = []
    elif defect == "restricted":
        sku["restrictions"] = [{"type": "Location"}]
    elif defect == "zones":
        sku["locationInfo"][0]["zones"] = ["1"]
    elif defect == "cpu":
        sku["capabilities"][0]["value"] = "2"
    elif defect == "encryption":
        sku["capabilities"][2]["value"] = "False"
    elif defect == "architecture":
        sku["capabilities"][3]["value"] = "Arm64"
    elif defect == "quota":
        arguments["usage"][0]["limit"] = 40
    elif defect == "duplicate-quota":
        arguments["usage"].append(arguments["usage"][0])
    elif defect == "quota-bool":
        arguments["usage"][0]["limit"] = True
    else:
        sku["capabilities"][1]["value"] = "nan"
    assert aks_preflight.assess_aks_capacity(**arguments)["state"] == "blocked"


def test_two_cpu_system_default_cannot_pass() -> None:
    arguments = _inputs()
    arguments["profile"] = replace(arguments["profile"], system_node_sku="Standard_D2as_v5")
    sku = copy.deepcopy(arguments["skus"][0])
    sku["name"] = "Standard_D2as_v5"
    sku["capabilities"][0]["value"] = "2"
    arguments["skus"].append(sku)
    assert (
        "system_pool_minimum_not_met" in aks_preflight.assess_aks_capacity(**arguments)["blockers"]
    )


def test_failed_provider_is_not_retried(monkeypatch) -> None:
    calls = []

    def fail(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(aks_preflight.subprocess, "run", fail)
    with pytest.raises(ValueError, match="no retry"):
        aks_preflight.inspect_aks_target(profile=_inputs()["profile"], region="eastus")
    assert len(calls) == 1
