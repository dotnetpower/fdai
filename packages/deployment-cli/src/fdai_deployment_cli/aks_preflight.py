"""Bounded read-only AKS feasibility checks; no provider registration or resource mutation."""

from __future__ import annotations

import json
import math
import re
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.target import compute_target_binding

# Major version created by infra/modules/state-store/postgres-flex; a parity test keeps them equal.
POSTGRES_FLEX_MAJOR_VERSION = "16"


def _active_human_target(deadline: DeploymentDeadline) -> tuple[str, str]:
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
        raise ValueError("AKS preflight target binding is incomplete")  # noqa: TRY004
    return subscription, tenant


def current_target_binding(*, timeout_seconds: int = 60) -> str:
    """Bind the active human Azure target before any provider read, without retaining either id."""

    subscription, tenant = _active_human_target(DeploymentDeadline(timeout_seconds))
    return compute_target_binding(subscription_id=subscription, tenant_id=tenant)


def inspect_aks_target(
    *,
    profile: RuntimeDeploymentProfile,
    region: str,
    timeout_seconds: int = 180,
    owned_resource_group: str | None = None,
) -> dict[str, object]:
    """Inspect the current human target once, returning sanitized feasibility evidence.

    Quota covers both pools at autoscaler maximum plus simultaneous 33-percent surge,
    not Foundation or other future resources. When a resumed installation already owns AKS
    pools in ``owned_resource_group``, the vCPUs those pools use are not new demand and are
    credited back; an unreadable group earns no credit. A ``postgres-flex`` profile also requires the
    regional Flexible Server catalog to offer the deployed major version. The report never
    claims full readiness, reserves capacity, logs target IDs, or retries a failed provider call.
    """
    if profile.runtime_platform.value != "aks" or re.fullmatch(r"[a-z][a-z0-9]+", region) is None:
        raise ValueError("AKS preflight requires an AKS profile and valid region")
    deadline = DeploymentDeadline(timeout_seconds)
    subscription, tenant = _active_human_target(deadline)
    target_binding = compute_target_binding(subscription_id=subscription, tenant_id=tenant)
    skus = _selected_skus(
        subscription=subscription,
        region=region,
        names={profile.system_node_sku, profile.user_node_sku},
        deadline=deadline,
    )
    usage = _json(
        ("vm", "list-usage", "--subscription", subscription, "--location", region), deadline
    )
    owned = (
        _owned_pool_vcpus(subscription, owned_resource_group, skus, deadline)
        if owned_resource_group is not None
        else {}
    )
    assessment = assess_aks_capacity(
        profile=profile, region=region, skus=skus, usage=usage, owned_vcpus=owned
    )
    if profile.database_placement.value == "postgres-flex":
        capabilities = _json(
            (
                "postgres",
                "flexible-server",
                "list-skus",
                "--subscription",
                subscription,
                "--location",
                region,
            ),
            deadline,
        )
        database = assess_postgres_flex_region(capabilities)
        blockers = sorted(
            {str(item) for item in cast(list[object], assessment["blockers"])}
            | {str(item) for item in cast(list[object], database["blockers"])}
        )
        assessment = {
            **assessment,
            "state": "blocked" if blockers else "feasible",
            "blockers": blockers,
            "database": database,
        }
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


def _selected_skus(
    *,
    subscription: str,
    region: str,
    names: set[str],
    deadline: DeploymentDeadline,
) -> list[object]:
    """Read the regional catalog once while serializing only exact selected SKUs."""

    ordered = sorted(names)
    if not ordered or any(
        re.fullmatch(r"Standard_[A-Za-z0-9_]{1,80}", name) is None for name in ordered
    ):
        raise ValueError("AKS selected SKU names are invalid")
    query = "[?" + " || ".join(f"name=='{name}'" for name in ordered) + "]"
    rows = _json(
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
            "--query",
            query,
        ),
        deadline,
    )
    if not isinstance(rows, list):
        raise ValueError("AKS selected SKU observation must be a list")  # noqa: TRY004
    return rows


def assess_aks_capacity(
    *,
    profile: RuntimeDeploymentProfile,
    region: str,
    skus: object,
    usage: object,
    owned_vcpus: Mapping[str, int] | None = None,
) -> dict[str, object]:
    """Evaluate complete provider observations and report missing evidence as a blocker.

    ``owned_vcpus`` maps a lower-case quota family to vCPUs already consumed by this
    installation's own pools, so a resumed run does not count them as new demand."""
    if not isinstance(skus, list) or not isinstance(usage, list):
        raise ValueError("AKS feasibility observations must be lists")  # noqa: TRY004
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
        current = _quota_integer(matches[0].get("currentValue"))
        limit = _quota_integer(matches[0].get("limit"))
        if current is None or limit is None:
            blockers.append(f"quota_{family}_invalid")
            continue
        remaining = limit - current + (owned_vcpus or {}).get(family, 0)
        quotas.append({"family": family, "required_vcpus": required, "remaining_vcpus": remaining})
        if required > remaining:
            blockers.append(f"quota_{family}_insufficient")
    return {
        "state": "blocked" if blockers else "feasible",
        "blockers": sorted(set(blockers)),
        "pools": pools,
        "quotas": quotas,
    }


def assess_postgres_flex_region(
    observation: object,
    *,
    required_version: str = POSTGRES_FLEX_MAJOR_VERSION,
) -> dict[str, object]:
    """Require the regional Flexible Server catalog to offer the deployed major version.

    A subscription restricted from a region receives an empty version list and a reason
    instead of an error, so the server create fails only after the Foundation and part of
    the substrate exist. Missing or malformed evidence blocks like an unavailable version.
    """
    evidence: dict[str, object] = {
        "placement": "postgres-flex",
        "required_version": required_version,
        "offered_versions": [],
    }
    if (
        not isinstance(observation, list)
        or not observation
        or not all(isinstance(entry, dict) for entry in observation)
    ):
        return {**evidence, "blockers": ["postgres_flex_evidence_incomplete"]}
    offered: set[str] = set()
    restricted = False
    for capability in observation:
        versions = capability.get("supportedServerVersions")
        if not isinstance(versions, list):
            return {**evidence, "blockers": ["postgres_flex_evidence_incomplete"]}
        offered.update(
            entry["name"]
            for entry in versions
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        )
        reason = capability.get("reason")
        restricted = restricted or (isinstance(reason, str) and bool(reason.strip()))
    blockers: list[str] = []
    if required_version not in offered:
        blockers.append(
            "postgres_flex_region_restricted"
            if restricted and not offered
            else "postgres_flex_version_unavailable"
        )
    return {**evidence, "offered_versions": sorted(offered), "blockers": blockers}


def _owned_pool_vcpus(
    subscription: str,
    resource_group: str,
    skus: object,
    deadline: DeploymentDeadline,
) -> dict[str, int]:
    """Return vCPUs this installation's existing AKS pools already use, by quota family."""

    if re.fullmatch(r"[A-Za-z0-9._()-]{1,90}", resource_group) is None or not isinstance(
        skus, list
    ):
        return {}
    try:
        pools = _json(
            (
                "aks",
                "list",
                "--subscription",
                subscription,
                "--resource-group",
                resource_group,
                "--query",
                "[].agentPoolProfiles[].{size:vmSize,count:count}",
            ),
            deadline,
        )
    except ValueError:
        return {}
    if not isinstance(pools, list):
        return {}
    by_size: dict[str, tuple[str, int]] = {}
    for sku in skus:
        if not isinstance(sku, dict) or not isinstance(sku.get("family"), str):
            continue
        capabilities = sku.get("capabilities")
        values = {
            entry.get("name"): entry.get("value")
            for entry in capabilities or []
            if isinstance(entry, dict)
        }
        try:
            by_size[str(sku.get("name"))] = (
                str(sku["family"]).casefold(),
                int(str(values["vCPUs"])),
            )
        except (KeyError, TypeError, ValueError):
            continue
    owned: dict[str, int] = {}
    for pool in pools:
        if not isinstance(pool, dict) or pool.get("size") not in by_size:
            continue
        count = _quota_integer(pool.get("count"))
        if count is None:
            continue
        family, cores = by_size[str(pool["size"])]
        owned[family] = owned.get(family, 0) + count * cores
        owned["cores"] = owned.get("cores", 0) + count * cores
    return owned


def _quota_integer(value: object) -> int | None:
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"(?:0|[1-9][0-9]{0,18})", value):
        return int(value)
    return None


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
