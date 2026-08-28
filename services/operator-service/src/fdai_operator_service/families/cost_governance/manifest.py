"""Stable Operator Cost Governance route manifest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class CostGovernanceRoute:
    """One read-only package route."""

    path: str
    name: str
    surface: Literal[
        "availability",
        "overview",
        "resource-efficiency",
        "optimization-cases",
        "outcomes",
    ]
    legacy_alias: bool = False


COST_GOVERNANCE_ROUTE_MANIFEST = (
    CostGovernanceRoute(
        "/cost-governance/availability",
        "cost_governance_availability",
        "availability",
    ),
    CostGovernanceRoute(
        "/cost-governance/overview",
        "cost_governance_overview",
        "overview",
    ),
    CostGovernanceRoute(
        "/cost-governance/resource-efficiency",
        "cost_governance_resource_efficiency",
        "resource-efficiency",
    ),
    CostGovernanceRoute(
        "/cost-governance/optimization-cases",
        "cost_governance_optimization_cases",
        "optimization-cases",
    ),
    CostGovernanceRoute(
        "/cost-governance/outcomes",
        "cost_governance_outcomes",
        "outcomes",
    ),
    CostGovernanceRoute("/finops", "cost_governance_finops_alias", "overview", True),
)


__all__ = ["COST_GOVERNANCE_ROUTE_MANIFEST", "CostGovernanceRoute"]
