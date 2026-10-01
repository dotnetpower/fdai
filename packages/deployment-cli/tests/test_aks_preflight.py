"""Capacity preflight never treats quota or SKU uncertainty as readiness."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
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


def _postgres_capabilities(*versions: str, reason: str | None = None) -> list[dict[str, object]]:
    offered = versions or ("15", "16", "17")
    return [
        {
            "name": "FlexibleServerCapabilities",
            "reason": reason,
            "restricted": None,
            "supportedServerVersions": [{"name": version, "reason": None} for version in offered],
        }
    ]


_RESTRICTED = (
    "Subscriptions are restricted from provisioning in this region. "
    "Please choose a different region."
)


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


def test_preflight_serializes_exact_selected_skus_from_one_catalog_read(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    inputs = _inputs()

    def provider(command, **_kwargs):
        calls.append(command)
        if command[1:3] == ("account", "show"):
            stdout = (
                b'{"id":"00000000-0000-0000-0000-000000000000",'
                b'"tenantId":"00000000-0000-0000-0000-000000000000",'
                b'"state":"Enabled","userType":"user"}'
            )
        elif command[1:3] == ("vm", "list-skus"):
            assert command[command.index("--query") + 1] == ("[?name=='Standard_D4as_v5']")
            stdout = json.dumps(inputs["skus"]).encode()
        elif command[1:4] == ("postgres", "flexible-server", "list-skus"):
            stdout = json.dumps(_postgres_capabilities()).encode()
        else:
            assert command[1:3] == ("vm", "list-usage")
            stdout = json.dumps(inputs["usage"]).encode()
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(aks_preflight.subprocess, "run", provider)

    result = aks_preflight.inspect_aks_target(
        profile=inputs["profile"],
        region="eastus",
    )

    sku_calls = [command for command in calls if command[1:3] == ("vm", "list-skus")]
    assert result["state"] == "feasible"
    assert len(sku_calls) == 1
    assert "--size" not in sku_calls[0]
    assert "--query" in sku_calls[0]
    assert [command[1:3] for command in calls[-2:]] == [
        ("vm", "list-usage"),
        ("postgres", "flexible-server"),
    ]


def test_distinct_overlapping_sku_names_use_one_exact_query(monkeypatch) -> None:
    inputs = _inputs()
    inputs["profile"] = replace(
        inputs["profile"],
        system_node_sku="Standard_D4",
        user_node_sku="Standard_D4_v2",
    )
    queries: list[str] = []

    def provider(command, **_kwargs):
        if command[1:3] == ("account", "show"):
            stdout = (
                b'{"id":"00000000-0000-0000-0000-000000000000",'
                b'"tenantId":"00000000-0000-0000-0000-000000000000",'
                b'"state":"Enabled","userType":"user"}'
            )
        elif command[1:3] == ("vm", "list-skus"):
            queries.append(command[command.index("--query") + 1])
            rows = []
            for name in ("Standard_D4", "Standard_D4_v2"):
                row = copy.deepcopy(inputs["skus"][0])
                row["name"] = name
                rows.append(row)
            stdout = json.dumps(rows).encode()
        elif command[1:4] == ("postgres", "flexible-server", "list-skus"):
            stdout = json.dumps(_postgres_capabilities()).encode()
        else:
            stdout = json.dumps(inputs["usage"]).encode()
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(aks_preflight.subprocess, "run", provider)

    result = aks_preflight.inspect_aks_target(
        profile=inputs["profile"],
        region="eastus",
    )

    assert result["state"] == "feasible"
    assert queries == ["[?name=='Standard_D4' || name=='Standard_D4_v2']"]


def test_offered_postgres_major_version_passes() -> None:
    result = aks_preflight.assess_postgres_flex_region(_postgres_capabilities())

    assert result["blockers"] == []
    assert result["required_version"] == "16"
    assert result["offered_versions"] == ["15", "16", "17"]


def test_restricted_postgres_region_blocks_with_a_specific_reason() -> None:
    # A restricted subscription gets an empty catalog and a reason instead of an error.
    observation = _postgres_capabilities(reason=_RESTRICTED)
    observation[0]["supportedServerVersions"] = []

    result = aks_preflight.assess_postgres_flex_region(observation)

    assert result["blockers"] == ["postgres_flex_region_restricted"]
    assert result["offered_versions"] == []
    assert "reason" not in result


def test_missing_postgres_major_version_blocks() -> None:
    result = aks_preflight.assess_postgres_flex_region(_postgres_capabilities("14", "15"))

    assert result["blockers"] == ["postgres_flex_version_unavailable"]


@pytest.mark.parametrize(
    "observation",
    [
        None,
        {},
        [],
        ["FlexibleServerCapabilities"],
        [{"name": "FlexibleServerCapabilities"}],
        [{"supportedServerVersions": "16"}],
    ],
)
def test_incomplete_postgres_evidence_blocks(observation: object) -> None:
    result = aks_preflight.assess_postgres_flex_region(observation)

    assert result["blockers"] == ["postgres_flex_evidence_incomplete"]


def test_required_postgres_version_matches_the_state_store_module() -> None:
    variables = (
        Path(__file__).resolve().parents[3] / "infra/modules/state-store/postgres-flex/variables.tf"
    ).read_text(encoding="utf-8")
    block = variables.split('variable "postgres_version"', 1)[1].split("\n}", 1)[0]

    assert f'default     = "{aks_preflight.POSTGRES_FLEX_MAJOR_VERSION}"' in block


def _provider(calls: list[tuple[str, ...]], postgres: list[dict[str, object]]):
    inputs = _inputs()

    def provider(command, **_kwargs):
        calls.append(command)
        if command[1:3] == ("account", "show"):
            stdout = (
                b'{"id":"00000000-0000-0000-0000-000000000000",'
                b'"tenantId":"00000000-0000-0000-0000-000000000000",'
                b'"state":"Enabled","userType":"user"}'
            )
        elif command[1:3] == ("vm", "list-skus"):
            stdout = json.dumps(inputs["skus"]).encode()
        elif command[1:4] == ("postgres", "flexible-server", "list-skus"):
            assert command[command.index("--location") + 1] == "eastus"
            stdout = json.dumps(postgres).encode()
        else:
            stdout = json.dumps(inputs["usage"]).encode()
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    return provider


def test_restricted_postgres_region_blocks_an_otherwise_feasible_aks_target(
    monkeypatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    restricted = _postgres_capabilities(reason=_RESTRICTED)
    restricted[0]["supportedServerVersions"] = []
    monkeypatch.setattr(aks_preflight.subprocess, "run", _provider(calls, restricted))

    result = aks_preflight.inspect_aks_target(profile=_inputs()["profile"], region="eastus")

    assert result["state"] == "blocked"
    assert result["blockers"] == ["postgres_flex_region_restricted"]
    assert result["database"] == {
        "placement": "postgres-flex",
        "required_version": "16",
        "offered_versions": [],
        "blockers": ["postgres_flex_region_restricted"],
    }
    assert result["mutation_performed"] is False


def test_postgres_aks_profile_does_not_read_the_flexible_server_catalog(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(aks_preflight.subprocess, "run", _provider(calls, []))
    profile = RuntimeDeploymentProfile.create(
        runtime_platform="aks",
        database_placement="postgres-aks",
        system_node_sku="Standard_D4as_v5",
        user_node_min_count=4,
    )

    result = aks_preflight.inspect_aks_target(profile=profile, region="eastus")

    assert result["state"] == "feasible"
    assert "database" not in result
    assert all(command[1] != "postgres" for command in calls)
