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
    RouteParity("/audit", "blocked", "authoritative audit projection adapter"),
    RouteParity(
        "/audit/{correlation_id}/trace",
        "blocked",
        "service-local rule-fire trace projection",
    ),
    RouteParity("/healthz", "service-owned"),
    RouteParity("/hil-queue", "blocked", "authoritative approval projection adapter"),
    RouteParity("/incidents", "blocked", "service-local incident projection"),
    RouteParity("/incidents/stream", "blocked", "durable event replay and SSE relay"),
    RouteParity("/kpi", "blocked", "authoritative KPI projection adapter"),
    RouteParity("/notification-templates/incident-opened", "service-owned"),
    RouteParity("/rca", "blocked", "service-local RCA projection"),
    RouteParity("/system/data-sources", "service-owned"),
)

BLOCKED_ROUTE_PATHS = frozenset(route.path for route in ROUTE_PARITY if route.status == "blocked")
PARITY_COMPLETE = not BLOCKED_ROUTE_PATHS

__all__ = ["BLOCKED_ROUTE_PATHS", "PARITY_COMPLETE", "ROUTE_PARITY", "RouteParity"]
