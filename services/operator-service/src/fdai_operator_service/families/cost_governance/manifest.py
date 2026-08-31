"""Stable Operator Cost Governance route manifest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class CostGovernanceRoute:
    """One package route owned by the Cost Governance family."""

    method: Literal["GET", "PUT"]
    path: str
    name: str
    surface: Literal[
        "availability",
        "overview",
        "resource-efficiency",
        "optimization-cases",
        "outcomes",
        "settings",
    ]
    legacy_alias: bool = False


COST_GOVERNANCE_ROUTE_MANIFEST = (
    CostGovernanceRoute(
        "GET",
        "/cost-governance/availability",
        "cost_governance_availability",
        "availability",
    ),
    CostGovernanceRoute(
        "GET",
        "/cost-governance/overview",
        "cost_governance_overview",
        "overview",
    ),
    CostGovernanceRoute(
        "GET",
        "/cost-governance/resource-efficiency",
        "cost_governance_resource_efficiency",
        "resource-efficiency",
    ),
    CostGovernanceRoute(
        "GET",
        "/cost-governance/optimization-cases",
        "cost_governance_optimization_cases",
        "optimization-cases",
    ),
    CostGovernanceRoute(
        "GET",
        "/cost-governance/outcomes",
        "cost_governance_outcomes",
        "outcomes",
    ),
    CostGovernanceRoute(
        "GET",
        "/finops",
        "cost_governance_finops_alias",
        "overview",
        True,
    ),
    CostGovernanceRoute(
        "GET",
        "/cost-governance/settings",
        "cost_governance_settings",
        "settings",
    ),
    CostGovernanceRoute(
        "PUT",
        "/cost-governance/settings",
        "cost_governance_settings",
        "settings",
    ),
)


__all__ = ["COST_GOVERNANCE_ROUTE_MANIFEST", "CostGovernanceRoute"]
