"""Inspect the AKS compute portion of deployment cost without claiming a complete budget."""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING

from fdai_deployment_cli.azure_retail_prices import read_linux_vm_price
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile


def inspect_aks_compute_cost(
    *,
    profile: RuntimeDeploymentProfile,
    region: str,
    monthly_cost_ceiling: int,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Price maximum steady-state nodes for 730 hours; unpriced components remain explicit.

    This is a partial projection, not a quote for the installation. It may block
    an over-budget profile but cannot approve one, reserve capacity or cap bills.
    """
    if (
        profile.runtime_platform.value != "aks"
        or type(monthly_cost_ceiling) is not int
        or monthly_cost_ceiling <= 0
    ):
        raise ValueError("AKS cost review requires an AKS profile and a positive ceiling")
    deadline = DeploymentDeadline(timeout_seconds)
    quotes = {
        sku: read_linux_vm_price(sku=sku, region=region, timeout_seconds=deadline.remaining(90))
        for sku in sorted({profile.system_node_sku, profile.user_node_sku})
    }
    lines = []
    for pool, sku, count in (
        ("system", profile.system_node_sku, profile.system_node_count),
        ("user", profile.user_node_sku, profile.user_node_max_count),
    ):
        hourly = Decimal(str(quotes[sku]["hourly_rate"]))
        monthly = (hourly * count * 730).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
        lines.append(
            {
                "pool": pool,
                "sku": sku,
                "node_count": count,
                "hours": 730,
                "hourly_rate_usd": str(hourly),
                "monthly_estimate_usd": str(monthly),
            }
        )
    total = sum((Decimal(str(line["monthly_estimate_usd"])) for line in lines), Decimal(0))
    exceeded = total > monthly_cost_ceiling
    result: dict[str, object] = {
        "schema_version": "fdai.deployment-compute-cost.v1",
        "stage": "cost-review",
        "state": "blocked" if exceeded else "partial",
        "reason_code": "aks_compute_exceeds_monthly_ceiling"
        if exceeded
        else "whole_installation_cost_incomplete",
        "runtime_profile_digest": profile.digest,
        "region": region,
        "monthly_cost_ceiling_usd": monthly_cost_ceiling,
        "monthly_compute_estimate_usd": str(total),
        "lines": lines,
        "quotes": quotes,
        "excluded_costs": [
            "surge-and-setup",
            "foundation",
            "aks-control-plane",
            "disks",
            "database",
            "network",
            "registry",
            "storage",
            "monitoring",
            "event-bus",
            "models",
            "taxes",
        ],
        "whole_installation_cost_verified": False,
        "setup_cost_verified": False,
        "billing_cap_enforced": False,
        "apply_authorized": False,
        "deployment_ready": False,
        "mutation_performed": False,
    }
    deadline.remaining()
    result["receipt_digest"] = canonical_digest(result)
    return result
