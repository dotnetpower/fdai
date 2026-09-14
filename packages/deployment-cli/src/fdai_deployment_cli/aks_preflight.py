"""Bounded read-only AKS feasibility checks; no provider registration or resource mutation."""

from __future__ import annotations

import json
import math
import re
import subprocess
from datetime import UTC, datetime
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.target import compute_target_binding


def inspect_aks_target(
    *,
    profile: RuntimeDeploymentProfile,
    region: str,
    timeout_seconds: int = 180,
) -> dict[str, object]:
    """Inspect the current human target once, returning sanitized feasibility evidence.

    Quota covers both pools at autoscaler maximum plus simultaneous 33-percent surge,
    not Foundation or other future resources. The report never claims full readiness,
    reserves capacity, logs target IDs, or retries a failed provider call.
    """
    if profile.runtime_platform.value != "aks" or re.fullmatch(r"[a-z][a-z0-9]+", region) is None:
        raise ValueError("AKS preflight requires an AKS profile and valid region")
    deadline = DeploymentDeadline(timeout_seconds)
    account = _json(
        ("account", "show", "--query", "{id:id,tenantId:tenantId,state:state,userType:user.type}"),
        deadline,
    )
    if (
        not isinstance(account, dict)
        or account.get("state") != "Enabled"
        or account.get("userType") != "user"
    ):
        raise ValueError("AKS preflight requires an enabled subscription and active human identity")
    subscription, tenant = account.get("id"), account.get("tenantId")
    if not isinstance(subscription, str) or not isinstance(tenant, str):
        raise ValueError("AKS preflight target binding is incomplete")
    target_binding = compute_target_binding(subscription_id=subscription, tenant_id=tenant)
    skus = _json(
        (
            "vm",
            "list-skus",
            "--subscription",
            subscription,
            "--location",
            region,
            "--resource-type",
            "virtualMachines",
            "--all",
        ),
        deadline,
    )
    usage = _json(
        ("vm", "list-usage", "--subscription", subscription, "--location", region), deadline
    )
    assessment = assess_aks_capacity(profile=profile, region=region, skus=skus, usage=usage)
    result = {
        "schema_version": "fdai.aks-capacity-preflight.v1",
        "target_binding": target_binding,
        "runtime_profile_digest": profile.digest,
        "region": region,
        "observed_at": datetime.now(UTC).isoformat(),
        **assessment,
        "deployment_ready": False,
        "apply_authorized": False,
        "mutation_performed": False,
    }
    deadline.remaining()
    result["receipt_digest"] = canonical_digest(result)
    return result


def assess_aks_capacity(
    *,
    profile: RuntimeDeploymentProfile,
    region: str,
    skus: object,
    usage: object,
) -> dict[str, object]:
    """Evaluate complete provider observations and report missing evidence as a blocker."""
    if not isinstance(skus, list) or not isinstance(usage, list):
        raise ValueError("AKS feasibility observations must be lists")
    blockers: list[str] = []
    demand: dict[str, int] = {}
    pools: list[dict[str, object]] = []
    for role, name, nodes in (
        ("system", profile.system_node_sku, profile.system_node_count),
        ("user", profile.user_node_sku, profile.user_node_max_count),
    ):
        matches = [
            sku
            for sku in skus
            if isinstance(sku, dict)
            and sku.get("name") == name
            and sku.get("resourceType") == "virtualMachines"
        ]
        if len(matches) != 1:
            blockers.append(f"{role}_sku_missing_or_ambiguous")
            continue
        sku = matches[0]
        family = sku.get("family")
        capabilities = sku.get("capabilities")
        locations = sku.get("locationInfo")
        if (
            not isinstance(family, str)
            or not isinstance(capabilities, list)
            or not isinstance(locations, list)
        ):
            blockers.append(f"{role}_sku_evidence_incomplete")
            continue
        values = {
            entry.get("name"): entry.get("value")
            for entry in capabilities
            if isinstance(entry, dict)
        }
        try:
            cores = int(str(values.get("vCPUs")))
            memory = float(str(values.get("MemoryGB")))
        except (TypeError, ValueError):
            blockers.append(f"{role}_sku_capacity_unknown")
            continue
        if cores <= 0 or not math.isfinite(memory) or memory <= 0:
            blockers.append(f"{role}_sku_capacity_invalid")
            continue
        if role == "system" and (cores < 4 or memory < 4 or name.startswith("Standard_B")):
            blockers.append("system_pool_minimum_not_met")
        if str(values.get("EncryptionAtHostSupported", "")).casefold() != "true":
            blockers.append(f"{role}_host_encryption_unavailable")
        if str(values.get("CpuArchitectureType", "")).casefold() != "x64":
            blockers.append(f"{role}_architecture_not_x64")
        regional = [
            entry
            for entry in locations
            if isinstance(entry, dict)
            and str(entry.get("location", "")).casefold() == region.casefold()
        ]
        if (
            len(regional) != 1
            or not isinstance(regional[0].get("zones"), list)
            or not {"1", "2", "3"}.issubset(regional[0]["zones"])
        ):
            blockers.append(f"{role}_required_zones_unavailable")
        restrictions = sku.get("restrictions")
        if not isinstance(restrictions, list) or restrictions:
            blockers.append(f"{role}_sku_restricted_or_unknown")
        surge = math.ceil(nodes * 33 / 100)
        required = (nodes + surge) * cores
        demand[family.casefold()] = demand.get(family.casefold(), 0) + required
        pools.append(
            {
                "pool": role,
                "sku": name,
                "nodes": nodes,
                "surge_nodes": surge,
                "required_vcpus": required,
            }
        )
    if len(pools) == 2:
        demand["cores"] = sum(demand.values())
    quotas = []
    for family, required in sorted(demand.items()):
        matches = [
            entry
            for entry in usage
            if isinstance(entry, dict)
            and isinstance(entry.get("name"), dict)
            and str(entry["name"].get("value", "")).casefold() == family
        ]
        if len(matches) != 1:
            blockers.append(f"quota_{family}_missing_or_ambiguous")
            continue
        current, limit = matches[0].get("currentValue"), matches[0].get("limit")
        if type(current) is not int or type(limit) is not int or current < 0 or limit < 0:
            blockers.append(f"quota_{family}_invalid")
            continue
        remaining = limit - current
        quotas.append({"family": family, "required_vcpus": required, "remaining_vcpus": remaining})
        if required > remaining:
            blockers.append(f"quota_{family}_insufficient")
    return {
        "state": "blocked" if blockers else "feasible",
        "blockers": sorted(set(blockers)),
        "pools": pools,
        "quotas": quotas,
    }


def _json(arguments: tuple[str, ...], deadline: DeploymentDeadline) -> Any:
    try:
        result = subprocess.run(
            ("az", *arguments, "--output", "json", "--only-show-errors"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=deadline.remaining(90),
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError(
            "AKS preflight provider unavailable; no retry or mutation performed"
        ) from None
    if result.returncode != 0 or len(result.stdout) > 16 * 1024 * 1024:
        raise ValueError("AKS preflight provider observation failed or exceeded its bound")
    try:
        return json.loads(result.stdout)
    except (UnicodeDecodeError, ValueError):
        raise ValueError("AKS preflight provider observation is not valid JSON") from None
