"""Explicit route-parity manifest for incremental Operator implementation extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class RouteParity:
    """Record whether one frozen route has a complete service-local implementation."""

    path: str
    status: Literal["service-owned", "blocked"]
    remaining_debt: str | None = None


ROUTE_PARITY: tuple[RouteParity, ...] = (
    RouteParity("/audit", "service-owned"),
    RouteParity("/audit/{correlation_id}/trace", "service-owned"),
    RouteParity("/healthz", "service-owned"),
    RouteParity("/hil-queue", "service-owned"),
    RouteParity("/incidents", "service-owned"),
    RouteParity("/incidents/stream", "service-owned"),
    RouteParity("/kpi", "service-owned"),
    RouteParity("/kpi/llm-cost", "service-owned"),
    RouteParity("/notification-templates/incident-opened", "service-owned"),
    RouteParity("/rca", "service-owned"),
    RouteParity("/system/data-sources", "service-owned"),
)

BLOCKED_ROUTE_PATHS = frozenset(route.path for route in ROUTE_PARITY if route.status == "blocked")
PARITY_COMPLETE = not BLOCKED_ROUTE_PATHS

__all__ = ["BLOCKED_ROUTE_PATHS", "PARITY_COMPLETE", "ROUTE_PARITY", "RouteParity"]
